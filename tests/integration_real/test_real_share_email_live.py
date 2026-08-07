"""Live smoke test (2026-08-06) for Section 9.2's "Send via Email" feature —
run once, deliberately, with ALLOW_LIVE_EXTERNAL_SENDS=true.

Proves the real thing, not just a mocked 200: a genuine SMTP send through the
actual POST /invoices/{id}/share-email endpoint (the same one the new
frontend "Send via Email" button calls), with the real invoice PDF attached
(not just linked in the body) — then fetched back via the real Gmail API
(not just trusted from the send call) to confirm it actually arrived with a
real, well-formed PDF attachment.

Sent to the business's own GMAIL_USER inbox via the new to_email override
(not a third party) — same "harmless, self-directed, disclosed" precedent
already established elsewhere in this file for one-off live checks — then
moved to Gmail Trash afterward, matching Section 9.1's retention rule.

Routine runs of this suite never send real mail: ALLOW_LIVE_EXTERNAL_SENDS
defaults to false (conftest.py), and this file is skipped entirely unless
it's explicitly set to true — no mocked "trivial pass" here, since a mocked
run couldn't prove anything about real arrival anyway.
"""

import os
import time

import pytest

from app.config import settings
from app.services import gmail_client

ALLOW_LIVE_EXTERNAL_SENDS = os.getenv("ALLOW_LIVE_EXTERNAL_SENDS", "false").lower() == "true"

pytestmark = pytest.mark.skipif(
    not ALLOW_LIVE_EXTERNAL_SENDS,
    reason="Live email send+arrival smoke test — only runs with ALLOW_LIVE_EXTERNAL_SENDS=true",
)


@pytest.fixture(scope="module")
def party_and_item(real_env, run_id):
    client, created = real_env

    party = client.post(
        "/api/v1/parties",
        json={
            "party_name": f"ZZTEST_ShareEmailLive_{run_id}",
            "party_type": "customer",
            "email": f"ZZTEST_{run_id}@example.com",  # on-file email — deliberately not used for this send
            "phone": "0333-2218892",
            "address": "Nagan Chowrangi",
        },
    )
    assert party.status_code == 201, party.text
    party_id = party.json()["id"]
    created["party_ids"].append(party_id)

    item = client.post(
        "/api/v1/inventory/create",
        data={
            "item_code": f"ZZTEST-SHAREMAIL-{run_id}",
            "item_name": "ZZTEST Share-Email Live Check Item",
            "unit": "pcs",
            "rate": "5000",
            "quantity_in_stock": "50",
        },
    )
    assert item.status_code == 201, item.text
    item_code = item.json()["item_code"]
    created["item_codes"].append(item_code)

    return party_id, item_code


def test_share_email_sends_real_pdf_attachment_and_it_actually_arrives(real_env, party_and_item, run_id):
    client, _created = real_env
    party_id, item_code = party_and_item

    # Small amount, well under the Rs. 100,000 Human Gate threshold — this
    # test is about the email/attachment mechanics, not the gate, so it
    # finalizes pre-approved and share-email is immediately dispatchable.
    draft = client.post(
        "/api/v1/invoices/draft",
        json={
            "party_id": party_id,
            "line_items": [{"item_code": item_code, "qty": 2}],
            "transaction_date": "2026-08-06",
        },
    )
    assert draft.status_code == 201, draft.text
    invoice_id = draft.json()["id"]

    finalized = client.post(f"/api/v1/invoices/{invoice_id}/finalize")
    assert finalized.status_code == 200, finalized.text
    invoice_no = finalized.json()["invoice_no"]
    assert finalized.json()["approval_status"] == "approved"

    # The real send, through the real endpoint the frontend button calls —
    # to_email overrides the party's on-file @example.com address, since the
    # point here is a real, checkable inbox: the business's own account.
    send = client.post(f"/api/v1/invoices/{invoice_id}/share-email", json={"to_email": settings.gmail_user})
    assert send.status_code == 200, send.text
    assert send.json()["status"] == "sent"

    subject_marker = f"Invoice #{invoice_no}"
    query = f'subject:"{subject_marker}" newer_than:1d'

    # Gmail's search index lags a real delivery by anywhere from a few
    # seconds up to ~90s in practice (observed directly while building this
    # check) — 8x15s gives real delivery comfortable room without the test
    # hanging forever if something is actually wrong.
    message_id = None
    for _attempt in range(8):
        ids = gmail_client.list_message_ids(query, max_results=5)
        if ids:
            message_id = ids[0]
            break
        time.sleep(15)
    assert message_id is not None, f"No message matching {query!r} arrived within ~2 minutes of the send call"

    full = gmail_client.get_full_message(message_id)
    headers = full["payload"]["headers"]

    def header(name):
        return next((h["value"] for h in headers if h["name"].lower() == name.lower()), None)

    assert subject_marker in (header("Subject") or "")
    assert settings.gmail_user in (header("To") or "")

    parts = full["payload"].get("parts", [])
    attachment_part = next(
        (p for p in parts if p.get("filename", "").lower().endswith(".pdf")),
        None,
    )
    assert attachment_part is not None, f"No .pdf attachment part found on the real message (parts: {parts})"
    assert attachment_part["filename"] == f"Invoice-{invoice_no}.pdf"

    attachment_id = attachment_part["body"]["attachmentId"]
    pdf_bytes = gmail_client.get_attachment_bytes(message_id, attachment_id)
    assert pdf_bytes.startswith(b"%PDF-"), "Attachment bytes fetched from the real, delivered message aren't a real PDF"
    assert len(pdf_bytes) > 10_000  # a real rendered invoice, not an empty/truncated stub

    # Section 9.1's retention rule: delete = Gmail Trash, not permanently
    # destroyed — same convention as the app's own Inbox delete action.
    gmail_client.trash_message(message_id)
