from app.services.inbox_service import _extract_invoice_no


def test_extract_invoice_no_from_typical_reply_subject():
    assert _extract_invoice_no("Re: Invoice #2127") == "2127"


def test_extract_invoice_no_is_case_insensitive_and_tolerates_spacing():
    assert _extract_invoice_no("invoice # 2127 - payment question") == "2127"


def test_extract_invoice_no_returns_none_when_absent():
    assert _extract_invoice_no("Just saying hello") is None
