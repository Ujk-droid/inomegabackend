"""Section 9.2 — 'Share on WhatsApp' is a wa.me click-to-chat link the app
constructs; there's no Meta Business API call, no per-message cost, and no
automated dispatch here — Admin/Staff reviews and presses Send themselves."""

from urllib.parse import quote


class MissingPhoneNumberError(Exception):
    """Raised when the party has no phone number on file — there's nothing to
    build a wa.me link against."""


def build_whatsapp_link(phone: str | None, invoice_no: str | None, pdf_url: str, total_amount: float) -> str:
    if not phone:
        raise MissingPhoneNumberError("This party has no phone number on file")

    digits_only = "".join(ch for ch in phone if ch.isdigit())
    invoice_label = f"#{invoice_no}" if invoice_no else "(draft)"
    message = (
        f"Omega Scales Invoice {invoice_label} — Total Rs. {total_amount:,.2f}\n"
        f"View/download your invoice PDF: {pdf_url}\n"
        f"Thank you for your business!"
    )
    return f"https://wa.me/{digits_only}?text={quote(message)}"
