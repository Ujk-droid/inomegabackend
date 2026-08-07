"""Live re-verification (2026-08-03), per the user's explicit request after
the frontend-only session's route guesses were fixed: Purchase Builder's new
endpoints (preview-pdf, create, get-by-id) run end-to-end against the real
Supabase project, plus the PDF fixes (logo, company watermark, peacock
theme, product thumbnail) proven with a REAL Cloudinary-hosted image — not
the shared `real_env` fixture's stubbed cdn.example.com placeholder, which
would never actually be fetchable by pdf_service._fetch_thumbnail.

Deliberately does not reuse tests/integration_real/conftest.py's `real_env`
fixture for the image step: that fixture patches
`app.services.cloudinary_client.upload_item_image` for the whole module, and
the entire point here is a genuine upload. `real_env` is still used for
party/purchase/invoice CRUD and auth, since those don't need Cloudinary.

Along the way this also renders the Rs. 184,500 golden invoice case (Section
2.3/7.4) with the same real product image attached, and saves both PDFs to
the scratchpad directory so they can be visually reviewed — this file is the
proof, not just an assertion that bytes came back.
"""

import io
from pathlib import Path

import pytest
from PIL import Image as PILImage, ImageDraw

from app.services import pdf_service
from app.services.cloudinary_client import delete_item_image as real_delete_item_image
from app.services.cloudinary_client import upload_item_image as real_upload_item_image
from app.services.invoice_dispatch_service import _items_by_code
from app.services.line_items import fetch_line_items
from app.services.purchase_service import LINE_ITEMS_TABLE, PARENT_COLUMN

SCRATCH_DIR = Path("/tmp/claude-1000/-mnt-d-omega/b7e654b0-4a7e-41e2-ac73-ab5c7651cd4f/scratchpad")


def _synthetic_platform_scale_image() -> bytes:
    """A simple, recognizable placeholder — a stainless deck + indicator head,
    matching Section 2.1's 'visual basis for inventory thumbnails' note — good
    enough to prove the real Cloudinary round trip and the PDF thumbnail cell,
    without needing a real product photo checked into the repo."""
    img = PILImage.new("RGB", (600, 480), color=(238, 241, 243))
    draw = ImageDraw.Draw(img)
    draw.rectangle([70, 260, 530, 400], fill=(150, 158, 166), outline=(90, 98, 106), width=6)  # SS deck
    draw.rectangle([250, 120, 350, 260], fill=(25, 25, 28), outline=(10, 10, 10), width=4)  # indicator head
    draw.rectangle([270, 150, 330, 190], fill=(20, 210, 120))  # LED readout
    draw.text((150, 420), "ZZTEST PLATFORM SCALE", fill=(20, 20, 20))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


@pytest.fixture(scope="module")
def real_product_image(run_id):
    """One genuine Cloudinary upload for the whole module — reused by both
    the purchase-flow test and the golden-invoice render below, then deleted
    once, in teardown."""
    image_bytes = _synthetic_platform_scale_image()
    url, public_id = real_upload_item_image(image_bytes, f"ZZTEST-SCALE-{run_id}")
    yield url, public_id
    real_delete_item_image(public_id)


@pytest.fixture(scope="module")
def supplier_and_item(real_env, run_id, real_product_image):
    client, created = real_env
    image_url, _public_id = real_product_image

    supplier = client.post(
        "/api/v1/parties",
        json={
            "party_name": f"ZZTEST_Supplier_{run_id}",
            "party_type": "both",  # both supplier (Purchase) and customer (golden invoice render)
            "phone": "0333-2218892",
            "address": "Nagan Chowrangi",
        },
    )
    assert supplier.status_code == 201, supplier.text
    party_id = supplier.json()["id"]
    created["party_ids"].append(party_id)

    item = client.post(
        "/api/v1/inventory/create",
        data={
            "item_code": f"ZZTEST-SCALE-{run_id}",
            "item_name": "Platform 400mm x 400mm SS Top Capacity 150Kg 10g Model (MK-03-Omega)",
            "unit": "pcs",
            "rate": "12300",
            "quantity_in_stock": "100",
        },
    )
    assert item.status_code == 201, item.text
    item_code = item.json()["item_code"]
    created["item_codes"].append(item_code)

    # Attach the real Cloudinary URL directly — bypassing the HTTP upload
    # path (which real_env has patched) since we already have a genuine URL.
    from app.database import get_supabase

    get_supabase().table("inventory_items").update(
        {"cloudinary_image_url": image_url}
    ).eq("item_code", item_code).execute()

    return party_id, item_code


def test_purchase_preview_pdf_real_thumbnail(real_env, supplier_and_item):
    client, _created = real_env
    party_id, item_code = supplier_and_item

    resp = client.post(
        "/api/v1/purchases/preview-pdf",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 20, "rate": 9000}],
            "transaction_date": "2026-07-30",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")
    # A real fetched+embedded JPEG thumbnail makes this meaningfully bigger
    # than a no-image bill — a cheap signal the image really was fetched.
    assert len(resp.content) > 900_000


def test_purchase_create_then_pdf_by_id_real_thumbnail(real_env, supplier_and_item):
    client, created = real_env
    party_id, item_code = supplier_and_item

    created_purchase = client.post(
        "/api/v1/purchases",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 20, "rate": 9000}],
            "transaction_date": "2026-07-30",
        },
    )
    assert created_purchase.status_code == 201, created_purchase.text
    body = created_purchase.json()
    assert body["purchase_bill_no"] is not None

    pdf_resp = client.get(f"/api/v1/purchases/{body['id']}/pdf")
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert pdf_resp.content.startswith(b"%PDF")
    assert len(pdf_resp.content) > 900_000

    (SCRATCH_DIR / "live_purchase_verification.pdf").write_bytes(pdf_resp.content)


def test_golden_invoice_184500_with_real_logo_watermark_thumbnail(real_env, supplier_and_item, run_id):
    """The Rs. 184,500 Section 2.3 case, rendered with the real uploaded
    product image, so logo + company watermark + peacock theme + real
    thumbnail + polish can all be reviewed together in one file."""
    client, created = real_env
    party_id, item_code = supplier_and_item

    draft = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 15, "rate": 12300}],
            "transaction_date": "2026-07-23",
        },
    )
    assert draft.status_code == 201, draft.text
    invoice_id = draft.json()["id"]

    finalized = client.post(f"/api/v1/invoices/{invoice_id}/finalize")
    assert finalized.status_code == 200, finalized.text
    finalized_body = finalized.json()
    assert finalized_body["total_amount"] == 184500
    assert finalized_body["approval_status"] == "pending"  # Human Gate, Section 7.4

    approved = client.post(f"/api/v1/invoices/{invoice_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["approval_status"] == "approved"

    from app.database import get_supabase

    supabase = get_supabase()
    invoice_row = supabase.table("customer_ledgers").select("*").eq("id", invoice_id).limit(1).execute().data[0]
    party_row = supabase.table("parties").select("*").eq("id", party_id).limit(1).execute().data[0]
    line_items = fetch_line_items(supabase, "invoice_line_items", "ledger_id", invoice_id)
    items_by_code = _items_by_code(supabase, line_items)

    pdf_bytes = pdf_service.build_invoice_pdf(invoice_row, party_row, line_items, items_by_code)
    assert pdf_bytes.startswith(b"%PDF")
    (SCRATCH_DIR / "golden_invoice_184500_final.pdf").write_bytes(pdf_bytes)

    # invoice_no was only assigned at finalize (Section 5.3) — confirm it's real, not None/DRAFT
    assert invoice_row["invoice_no"] is not None
