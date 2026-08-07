import uuid

import cloudinary
import cloudinary.uploader

from app.config import settings

_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )
    _configured = True


def upload_item_image(file_bytes: bytes, item_code: str) -> tuple[str, str]:
    """Upload a product image, auto-resized/compressed per Section 11's free-tier note.

    Returns (secure_url, public_id).
    """
    _configure()
    result = cloudinary.uploader.upload(
        file_bytes,
        folder="omega-scales/inventory",
        public_id=item_code,
        overwrite=True,
        eager=[{"width": 800, "crop": "limit", "fetch_format": "auto", "quality": "auto"}],
    )
    return result["secure_url"], result["public_id"]


def delete_item_image(public_id: str) -> None:
    _configure()
    cloudinary.uploader.destroy(public_id)


def upload_invoice_pdf(pdf_bytes: bytes, invoice_no: str, *, duplicate: bool = False) -> tuple[str, str]:
    """Section 9.2 — the generated invoice PDF lands here, not on local disk.
    A duplicate reprint gets its own public_id (Section 9.2: 'the original
    invoice and its PDF remain untouched, forever') rather than overwriting
    the first PDF's asset."""
    _configure()
    suffix = "-duplicate" if duplicate else ""
    result = cloudinary.uploader.upload(
        pdf_bytes,
        folder="omega-scales/invoices",
        public_id=f"{invoice_no}{suffix}",
        resource_type="raw",
        overwrite=duplicate,  # a fresh reprint request replaces its own prior duplicate asset, never the original
    )
    return result["secure_url"], result["public_id"]


def upload_delivery_challan_pdf(pdf_bytes: bytes, challan_no: str) -> tuple[str, str]:
    """Section 16.5 — same storage pattern as upload_invoice_pdf above, its
    own folder since a challan is a distinct document type, not an invoice."""
    _configure()
    result = cloudinary.uploader.upload(
        pdf_bytes,
        folder="omega-scales/delivery-challans",
        public_id=challan_no,
        resource_type="raw",
        overwrite=True,
    )
    return result["secure_url"], result["public_id"]


def upload_scan_slip_image(file_bytes: bytes) -> tuple[str, str]:
    """Section 5.4.K — the original photographed/uploaded order slip, kept
    attached to whichever invoice ends up built from it (customer_ledgers.
    scan_slip_cloudinary_url) as a reference. A random public_id — unlike an
    item image or an invoice PDF, a scan has no natural stable key of its own
    yet (the invoice doesn't exist until after the review step)."""
    _configure()
    result = cloudinary.uploader.upload(
        file_bytes,
        folder="omega-scales/scan-slips",
        public_id=f"scan-{uuid.uuid4().hex[:16]}",
    )
    return result["secure_url"], result["public_id"]
