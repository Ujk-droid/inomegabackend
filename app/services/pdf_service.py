"""Section 9.2 — Invoice/Purchase PDF generation via ReportLab, pixel-matching
Section 2.3's layout with Section 9.2's light-theme color treatment (white
page, dark text, one accent color used sparingly — never the app's dark
glassmorphic look). Purchase bills (Section 5.4.B, "same layout discipline as
Invoice Builder") share this exact renderer via _render_bill_pdf below, only
swapping the labels that differ (Invoice # vs Purchase Bill #, "To M/S" vs
"Supplier"). Section 16.2 documents this refactor."""

from io import BytesIO
from pathlib import Path

import httpx
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# Section 9.2's exact palette
COLOR_HEADER_BAND = colors.HexColor("#E4F3F4")
COLOR_ACCENT = colors.HexColor("#0F6B7C")
COLOR_ZEBRA = colors.HexColor("#F5F7FA")
COLOR_BORDER = colors.HexColor("#D0D7DE")
COLOR_TEXT = colors.HexColor("#1A1A1A")

# Section 16.6 polish pass — thumbnail large enough to actually recognize the
# product (was 12mm/~34pt, closer to an abstract icon than a photo); 22mm
# (~62pt) matches the requested 60-70px range while still leaving row height
# reasonable for a table with many lines.
THUMBNAIL_SIZE = 22 * mm
_THUMBNAIL_FETCH_TIMEOUT = 5.0

# Copied from omega-frontend/public/logo.png at build time — kept inside this
# repo (not read cross-repo) so PDF generation never depends on the frontend
# checkout existing on the same machine/deploy target.
LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"
LOGO_SIZE = 16 * mm

# Section 2.3's fixed line-item columns; the Item Name column fills whatever
# width is left of doc.width so the table always spans the full page margin
# to margin, in both invoice and purchase PDFs.
_THUMB_COL = THUMBNAIL_SIZE + 4 * mm
# Wide enough that a realistic item_code ("ACC-RC-RAMP", "P-EP-1000-BL", …)
# never wraps mid-word — confirmed via reportlab.pdfmetrics.stringWidth
# against the longest real codes currently in inventory (~23mm of text at
# 9pt Helvetica; 24mm previously left no room for the cell's own padding).
_CODE_COL = 30 * mm
_UNIT_COL = 14 * mm
_RATE_COL = 22 * mm
_QTY_COL = 14 * mm
_TOTAL_COL = 24 * mm

# One consistent rhythm for the gaps between major sections (header band,
# party/meta block, items table, totals block) — premium invoices read as
# "designed," not cramped, when the vertical spacing doesn't waver section
# to section.
_SECTION_SPACING = 8 * mm

_styles = getSampleStyleSheet()
_style_body = ParagraphStyle("OmegaBody", parent=_styles["Normal"], textColor=COLOR_TEXT, fontSize=9, leading=13)
_style_muted = ParagraphStyle("OmegaMuted", parent=_styles["Normal"], textColor=COLOR_TEXT, fontSize=8, leading=11)
_style_tagline = ParagraphStyle(
    "OmegaTagline", parent=_styles["Normal"], textColor=COLOR_ACCENT, fontSize=8, leading=10, fontName="Helvetica-Oblique"
)
_style_draft_pill = ParagraphStyle(
    "OmegaDraftPill", parent=_styles["Normal"], textColor=COLOR_ACCENT, fontName="Helvetica-Bold", fontSize=9, leading=11, alignment=TA_CENTER
)


def _fetch_thumbnail(url: str | None) -> Image | None:
    """Best-effort — a slow/unreachable/missing Cloudinary image must never
    break invoice generation, it just means that row's thumbnail cell is blank."""
    if not url:
        return None
    try:
        resp = httpx.get(url, timeout=_THUMBNAIL_FETCH_TIMEOUT)
        resp.raise_for_status()
        return Image(BytesIO(resp.content), width=THUMBNAIL_SIZE, height=THUMBNAIL_SIZE)
    except (httpx.HTTPError, Exception):  # noqa: BLE001
        return None


def _logo_image() -> Image | None:
    """Same best-effort convention as _fetch_thumbnail — a missing/corrupt
    logo asset must never break PDF generation, the header just loses the mark."""
    try:
        return Image(str(LOGO_PATH), width=LOGO_SIZE, height=LOGO_SIZE)
    except Exception:  # noqa: BLE001
        return None


def _company_watermark(canvas, doc) -> None:
    """Section 9.2 (new) — a permanent, very faint branding/anti-forgery mark
    on every generated PDF, not just duplicates: much fainter than the
    DUPLICATE watermark below (6-8% vs 15% opacity) so it never competes with
    the actual invoice content for attention."""
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 66)
    canvas.setFillColor(COLOR_ACCENT, alpha=0.07)
    canvas.translate(doc.pagesize[0] / 2, doc.pagesize[1] / 2)
    canvas.rotate(45)
    canvas.drawCentredString(0, 0, "OMEGA SCALES")
    canvas.restoreState()


def _duplicate_watermark(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 90)
    canvas.setFillColor(COLOR_ACCENT, alpha=0.15)
    canvas.translate(doc.pagesize[0] / 2, doc.pagesize[1] / 2)
    canvas.rotate(45)
    canvas.drawCentredString(0, 0, "DUPLICATE")
    canvas.restoreState()


def _page_decorations(duplicate: bool):
    """Company watermark always draws first (background layer); the
    DUPLICATE stamp, when present, layers on top of it — Section 9.2: 'this
    is layered on top of the fainter company watermark, not a replacement.'"""

    def _draw(canvas, doc):
        _company_watermark(canvas, doc)
        if duplicate:
            _duplicate_watermark(canvas, doc)

    return _draw


def _draft_doc_meta(doc_no_label: str, transaction_date, col_width: float) -> Table:
    """Section 9.2 (new) — a draft's document number isn't real yet (Section
    5.3 only assigns one on finalize); rendering 'DRAFT' as a bordered accent
    pill instead of plain inline text makes an unfinalized PDF unmistakable
    at a glance. Uses only colors already in this file's palette (COLOR_ACCENT,
    COLOR_HEADER_BAND) — once finalized, this is never used again; the real
    number prints exactly as it always has."""
    pill_col = 20 * mm
    label_col = col_width - pill_col

    pill = Table([[Paragraph("DRAFT", _style_draft_pill)]], colWidths=[pill_col])
    pill.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1, COLOR_ACCENT),
                ("BACKGROUND", (0, 0), (-1, -1), COLOR_HEADER_BAND),
                ("ROUNDEDCORNERS", [6, 6, 6, 6]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    label = Paragraph(
        f"<b><font color='#0F6B7C' size='11'>{doc_no_label} :</font></b>",
        ParagraphStyle("draftLabel", parent=_style_body, alignment=TA_RIGHT, leading=15),
    )
    date_line = Paragraph(
        f"DATE : {transaction_date}",
        ParagraphStyle("draftDate", parent=_style_body, alignment=TA_RIGHT, leading=15),
    )

    block = Table([[label, pill], [date_line, ""]], colWidths=[label_col, pill_col])
    block.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 1), (1, 1)),
                ("ALIGN", (0, 0), (0, 0), "RIGHT"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("ALIGN", (0, 1), (0, 1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return block


def _render_bill_pdf(
    *,
    doc_no_label: str,
    doc_no: str | None,
    party_name: str,
    party_phone: str | None,
    party_address: str | None,
    party_label: str,
    transaction_date,
    line_items: list[dict],
    items_by_code: dict[str, dict],
    total_amount: float = 0.0,
    previous_balance: float = 0.0,
    discount_amount: float = 0.0,
    current_balance: float = 0.0,
    received_amount: float = 0.0,
    received_label: str = "Received (Rs.)",
    duplicate: bool = False,
    # Section 16.5 — Delivery Challan's "sibling mode": same header, watermark,
    # party block, and item table as an invoice/purchase bill, but with every
    # pricing/totals element stripped out (a challan proves what was delivered,
    # not what it cost). Everything below defaults to the original bill layout.
    pricing: bool = True,
    footer_note: str | None = "Note: Pay Dues within 15 Days",
    signature_labels: tuple[str, str] = ("Receiver's Signature", "Signature"),
) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm, leftMargin=15 * mm, rightMargin=15 * mm
    )
    story = []

    # ── Header band (Section 9.2: light tint, ~90%-lightened accent, + logo) ─
    text_block = Table(
        [
            [Paragraph("<b>OMEGA SCALES</b>", ParagraphStyle("title", parent=_style_body, fontSize=17, leading=20, textColor=COLOR_ACCENT))],
            [Paragraph("TR1/20/2, Marston Road, Near Gul Plaza, 74400, Karachi", _style_muted)],
            [Paragraph("Mobile: 0321-2175034, 03100884427 &nbsp;|&nbsp; Ptcl: 0213-32751125", _style_muted)],
            [Paragraph("Industrial &amp; Digital Weighing Systems", _style_tagline)],
        ],
        colWidths=[doc.width - LOGO_SIZE - 12 * mm],
    )
    text_block.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )

    logo = _logo_image()
    header_table = Table(
        [[logo or "", text_block]],
        colWidths=[LOGO_SIZE + 8 * mm, doc.width - LOGO_SIZE - 8 * mm],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), COLOR_HEADER_BAND),
                ("BOX", (0, 0), (-1, -1), 0.5, COLOR_ACCENT),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, _SECTION_SPACING))

    # ── Party + document meta (Section 2.3) ─────────────────────────────────
    party_col_width = doc.width * 0.6
    doc_col_width = doc.width * 0.4

    # Section 9.2 (new) — the Name/Phone/Address block groups into a subtly
    # bordered box instead of plain stacked text, using the same neutral
    # `#D0D7DE` border already used for the item table and totals block below
    # (no new color introduced).
    party_lines = [f"<b>{party_label}</b> {party_name}"]
    if party_phone:
        party_lines.append(party_phone)
    if party_address:
        party_lines.append(party_address)

    party_box = Table([[Paragraph("<br/>".join(party_lines), _style_body)]], colWidths=[party_col_width])
    party_box.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    if doc_no:
        doc_meta = Paragraph(
            f"<b><font color='#0F6B7C' size='11'>{doc_no_label} : {doc_no}</font></b><br/>DATE : {transaction_date}",
            ParagraphStyle("meta", parent=_style_body, alignment=TA_RIGHT, leading=15),
        )
    else:
        # Section 9.2 (new) — a draft's "invoice number" isn't a real one yet
        # (Section 5.3 only assigns one on finalize); rendering "DRAFT" as a
        # bordered accent pill instead of plain text makes an unfinalized PDF
        # unmistakable, using the same accent already used for a real number.
        doc_meta = _draft_doc_meta(doc_no_label, transaction_date, doc_col_width)

    meta_table = Table([[party_box, doc_meta]], colWidths=[party_col_width, doc_col_width])
    meta_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, COLOR_ACCENT),
            ]
        )
    )
    story.append(meta_table)
    story.append(Spacer(1, _SECTION_SPACING))

    # ── Line items table (Section 2.3 + product thumbnail addition) ───────
    if pricing:
        header_row = ["", "Item Code", "Item Name", "Unit", "Rate", "Qty", "Total"]
    else:
        header_row = ["", "Item Code", "Item Name", "Unit", "Qty"]
    rows = [header_row]
    for line in sorted(line_items, key=lambda r: r["line_number"]):
        item = items_by_code.get(line["item_code"], {})
        thumb = _fetch_thumbnail(item.get("cloudinary_image_url"))
        row = [
            thumb or "",
            Paragraph(line["item_code"], _style_body),
            Paragraph(item.get("item_name", ""), _style_body),
            item.get("unit_name", "pcs"),
        ]
        if pricing:
            row.append(f"{float(line['rate']):,.2f}")
        row.append(str(line["qty"]))
        if pricing:
            row.append(f"{float(line['line_total']):,.2f}")
        rows.append(row)

    if pricing:
        col_widths = [_THUMB_COL, _CODE_COL, doc.width - (_THUMB_COL + _CODE_COL + _UNIT_COL + _RATE_COL + _QTY_COL + _TOTAL_COL), _UNIT_COL, _RATE_COL, _QTY_COL, _TOTAL_COL]
        right_align_from = 4
    else:
        col_widths = [_THUMB_COL, _CODE_COL, doc.width - (_THUMB_COL + _CODE_COL + _UNIT_COL + _QTY_COL), _UNIT_COL, _QTY_COL]
        right_align_from = 4
    items_table = Table(
        rows,
        colWidths=col_widths,
        repeatRows=1,
        rowHeights=[10 * mm] + [None] * (len(rows) - 1),
    )
    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.white),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_ACCENT),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, COLOR_ACCENT),
        # Premium-invoice borders: a thin, neutral outer box (never the
        # accent color, which reads as "heavy branded line" at full-table
        # scale) and no full grid — just a hairline under each data row, so
        # the table reads as clean horizontal rhythm rather than a
        # spreadsheet. No vertical rules at all.
        ("BOX", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (right_align_from, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for row_index in range(1, len(rows) - 1):
        style_commands.append(("LINEBELOW", (0, row_index), (-1, row_index), 0.4, COLOR_BORDER))
    for row_index in range(1, len(rows)):
        if row_index % 2 == 0:
            style_commands.append(("BACKGROUND", (0, row_index), (-1, row_index), COLOR_ZEBRA))
    items_table.setStyle(TableStyle(style_commands))
    story.append(items_table)
    story.append(Spacer(1, _SECTION_SPACING))

    # ── Totals block (Section 2.3's exact fields) — skipped entirely in
    # Delivery Challan's "sibling mode," a challan proves delivery, not cost.
    if pricing:
        total_payable = total_amount - received_amount

        # Visual hierarchy (Section 16.6 polish pass): Total Payable must be
        # the single most prominent figure on the page — a full-width,
        # accent-filled bar with white text well above the body font size,
        # not just a slightly-bolder line among several similar-looking
        # totals. "Total (Rs.)" (the pre-payment subtotal) is deliberately
        # plain now so it no longer competes with it for attention.
        totals_table = Table(
            [
                ["Previous Balance:", f"{previous_balance:,.2f}", "Special Discount", f"{discount_amount:,.2f}"],
                ["This Bill Balance:", f"{total_amount:,.2f}", "Total (Rs.)", f"{total_amount:,.2f}"],
                ["Current Balance:", f"{current_balance:,.2f}", received_label, f"{received_amount:,.2f}"],
                [
                    "",
                    "",
                    Paragraph(
                        "<b>TOTAL PAYABLE (Rs.)</b>",
                        ParagraphStyle("payableLabel", parent=_style_body, textColor=colors.white, fontSize=10),
                    ),
                    Paragraph(
                        f"<b>{total_payable:,.2f}</b>",
                        ParagraphStyle(
                            "payableValue", parent=_style_body, textColor=colors.white, fontSize=16, alignment=TA_RIGHT
                        ),
                    ),
                ],
            ],
            # Value column sized generously (confirmed via stringWidth against
            # 7-digit totals at this font size) so a large real total never
            # wraps a digit outside the accent bar the way a narrower column
            # did during testing.
            colWidths=[doc.width * 0.22, doc.width * 0.20, doc.width * 0.28, doc.width * 0.30],
        )
        totals_table.setStyle(
            TableStyle(
                [
                    ("TEXTCOLOR", (0, 0), (-1, 2), COLOR_TEXT),
                    ("FONTSIZE", (0, 0), (-1, 2), 9),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("ALIGN", (3, 0), (3, -1), "RIGHT"),
                    ("BOX", (0, 0), (-1, 2), 0.5, COLOR_BORDER),
                    ("LINEAFTER", (1, 0), (1, 2), 0.5, COLOR_BORDER),
                    ("LINEABOVE", (2, 1), (3, 1), 0.5, COLOR_BORDER),
                    ("BACKGROUND", (0, 3), (-1, 3), COLOR_ACCENT),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, 2), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, 2), 5),
                    ("TOPPADDING", (0, 3), (-1, 3), 8),
                    ("BOTTOMPADDING", (0, 3), (-1, 3), 8),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        # KeepTogether: a bare Table can split across a page boundary between
        # any two rows by default — confirmed live on a 6-line invoice, where
        # the accent Total Payable bar landed alone at the top of page 2,
        # separated from the balances it summarizes. The whole totals block
        # is small enough to always keep together on one page.
        story.append(KeepTogether([totals_table, Spacer(1, _SECTION_SPACING + 2 * mm)]))

    if footer_note:
        story.append(Paragraph(footer_note, _style_body))
        story.append(Spacer(1, 3 * mm))
    story.append(
        Paragraph(
            "<b>THANK YOU FOR YOUR BUSINESS!</b>",
            ParagraphStyle("thanks", parent=_style_body, alignment=TA_CENTER, textColor=COLOR_ACCENT, fontSize=10),
        )
    )
    story.append(Spacer(1, 16 * mm))

    signature_table = Table(
        [["_________________________", "_________________________"], list(signature_labels)],
        colWidths=[doc.width / 2, doc.width / 2],
    )
    signature_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TEXTCOLOR", (0, 0), (-1, -1), COLOR_TEXT),
                ("FONTSIZE", (0, 1), (-1, 1), 8),
                ("TOPPADDING", (0, 1), (-1, 1), 2),
            ]
        )
    )
    story.append(signature_table)

    doc.build(story, onFirstPage=_page_decorations(duplicate), onLaterPages=_page_decorations(duplicate))
    return buffer.getvalue()


def build_invoice_pdf(
    invoice: dict,
    party: dict,
    line_items: list[dict],
    items_by_code: dict[str, dict],
    *,
    duplicate: bool = False,
) -> bytes:
    """invoice/party/line_items are raw table rows (customer_ledgers /
    parties / invoice_line_items), items_by_code maps item_code ->
    inventory_items row (for item_name + cloudinary_image_url per line)."""
    return _render_bill_pdf(
        doc_no_label="INVOICE #",
        doc_no=invoice.get("invoice_no"),
        party_name=party["party_name"],
        party_phone=party.get("phone"),
        party_address=party.get("address"),
        party_label="To M/S:",
        transaction_date=invoice["transaction_date"],
        line_items=line_items,
        items_by_code=items_by_code,
        total_amount=float(invoice["total_amount"]),
        previous_balance=float(invoice.get("previous_balance") or 0),
        discount_amount=float(invoice.get("discount_amount") or 0),
        current_balance=float(invoice["current_balance"]),
        received_amount=float(invoice.get("received_at_sale") or 0),
        received_label="Received (Rs.)",
        duplicate=duplicate,
    )


def build_purchase_pdf(
    purchase: dict,
    party: dict,
    line_items: list[dict],
    items_by_code: dict[str, dict],
    *,
    duplicate: bool = False,
) -> bytes:
    """Section 5.4.B — same renderer as build_invoice_pdf ("same layout
    discipline as Invoice Builder"), purchase/party/line_items are raw table
    rows (purchases / parties / purchase_line_items)."""
    return _render_bill_pdf(
        doc_no_label="PURCHASE BILL #",
        doc_no=purchase.get("purchase_bill_no"),
        party_name=party["party_name"],
        party_phone=party.get("phone"),
        party_address=party.get("address"),
        party_label="Supplier:",
        transaction_date=purchase["transaction_date"],
        line_items=line_items,
        items_by_code=items_by_code,
        total_amount=float(purchase["total_amount"]),
        previous_balance=float(purchase.get("previous_balance") or 0),
        discount_amount=float(purchase.get("discount_amount") or 0),
        current_balance=float(purchase["current_balance"]),
        received_amount=float(purchase.get("received_amount") or 0),
        received_label="Paid (Rs.)",
        duplicate=duplicate,
    )


def build_delivery_challan_pdf(
    challan: dict,
    invoice: dict,
    party: dict,
    line_items: list[dict],
    items_by_code: dict[str, dict],
) -> bytes:
    """Section 16.5 — the shared renderer's 'sibling mode': same header,
    watermark, party block, and item table as an invoice, no pricing/totals
    at all — just Item, Qty, delivered-to address, and a signature line."""
    return _render_bill_pdf(
        doc_no_label="CHALLAN #",
        doc_no=challan.get("challan_no"),
        party_name=party["party_name"],
        party_phone=party.get("phone"),
        party_address=party.get("address"),
        party_label="Deliver To:",
        transaction_date=challan.get("delivered_at") or invoice["transaction_date"],
        line_items=line_items,
        items_by_code=items_by_code,
        pricing=False,
        footer_note="Please verify quantities and condition of goods upon receipt.",
        signature_labels=("Receiver's Signature", "Delivered By"),
    )
