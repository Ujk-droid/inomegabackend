"""Section 5.4.K — Scan Slip. A photographed/uploaded handwritten or printed
order slip is read via OpenAI Vision (the same OPENAI_API_KEY as Section 9.1's
AI Reply — no separate key needed), matched against the real inventory_items
catalog, and returned as a review list. Nothing is added to an invoice
automatically — same human-in-the-loop principle as the Human Gate and AI
Reply: a person confirms (and can correct/re-match) every line before it ever
becomes a line item.
"""

import json
from difflib import SequenceMatcher

from openai import OpenAI
from supabase import Client

from app.config import settings
from app.models.scan_slip import ScanSlipItemOut, ScanSlipResult
from app.services import cloudinary_client

MODEL = "gpt-4o-mini"

# Empirically reasonable difflib.SequenceMatcher.ratio() cutoffs for
# "handwritten description" vs. "catalog item_name/item_code" — not a
# database extension or ML model, just stdlib string similarity. Good enough
# at this catalog size (dozens to low hundreds of items, not tens of
# thousands) that a wrong high-confidence match would need a genuinely
# ambiguous slip, and the low-confidence band exists precisely to catch that.
HIGH_CONFIDENCE_THRESHOLD = 0.6
LOW_CONFIDENCE_THRESHOLD = 0.35

SYSTEM_PROMPT = (
    "You read a photographed or handwritten order slip for a weighing-scale equipment business "
    "(e.g. 'Omega Scales'). Extract every line item you can find as strict JSON in exactly this shape: "
    '{"items": [{"description": "<item description as written>", "qty": <integer, default 1 if not stated>, '
    '"rate": <number or null if no price is written>}]}. '
    "Never invent an item that is not actually written on the slip. If you can't read the slip at all, "
    'return {"items": []}.'
)


class ScanSlipError(Exception):
    """Raised when the AI call itself fails or its response can't be parsed —
    never silently swallowed into an empty result, since that would look
    indistinguishable from 'the slip had nothing on it'."""


def _extract_line_items(image_url: str) -> list[dict]:
    if not settings.openai_api_key:
        raise ScanSlipError("OPENAI_API_KEY not configured")

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract the line items from this order slip."},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
    )
    try:
        parsed = json.loads(response.choices[0].message.content)
        items = parsed.get("items", [])
    except (json.JSONDecodeError, AttributeError, TypeError) as exc:
        raise ScanSlipError("The AI's response could not be parsed") from exc

    if not isinstance(items, list):
        raise ScanSlipError("The AI's response was not in the expected shape")
    return items


def _best_match(description: str, catalog: list[dict]) -> tuple[dict | None, float]:
    needle = description.lower()
    best_item: dict | None = None
    best_score = 0.0
    for item in catalog:
        score = max(
            SequenceMatcher(None, needle, item["item_name"].lower()).ratio(),
            SequenceMatcher(None, needle, item["item_code"].lower()).ratio(),
        )
        if score > best_score:
            best_score = score
            best_item = item
    return best_item, best_score


def scan_slip(supabase: Client, file_bytes: bytes) -> ScanSlipResult:
    image_url, _public_id = cloudinary_client.upload_scan_slip_image(file_bytes)
    raw_items = _extract_line_items(image_url)
    catalog = supabase.table("inventory_items").select("item_code, item_name").execute().data

    reviewed: list[ScanSlipItemOut] = []
    for raw in raw_items:
        description = str(raw.get("description") or "").strip()
        try:
            qty = int(raw.get("qty") or 1)
        except (TypeError, ValueError):
            qty = 1
        rate = raw.get("rate")

        match, score = _best_match(description, catalog) if description and catalog else (None, 0.0)
        if match and score >= HIGH_CONFIDENCE_THRESHOLD:
            confidence = "high"
        elif match and score >= LOW_CONFIDENCE_THRESHOLD:
            confidence = "low"
        else:
            confidence = "none"
            match = None

        reviewed.append(
            ScanSlipItemOut(
                raw_description=description,
                qty=qty,
                rate=float(rate) if rate is not None else None,
                matched_item_code=match["item_code"] if match else None,
                matched_item_name=match["item_name"] if match else None,
                confidence=confidence,
            )
        )

    return ScanSlipResult(scan_slip_cloudinary_url=image_url, items=reviewed)
