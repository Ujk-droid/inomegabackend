import pytest

from app.services.whatsapp_service import MissingPhoneNumberError, build_whatsapp_link


def test_build_whatsapp_link_strips_non_digits_and_encodes_message():
    link = build_whatsapp_link("0333-2218892", "2127", "https://cdn.example.com/inv.pdf", 184500.0)
    assert link.startswith("https://wa.me/03332218892?text=")
    assert "184%2C500.00" in link or "184%2C500" in link  # URL-encoded comma from f-string formatting


def test_build_whatsapp_link_requires_a_phone_number():
    with pytest.raises(MissingPhoneNumberError):
        build_whatsapp_link(None, "2127", "https://cdn.example.com/inv.pdf", 184500.0)
