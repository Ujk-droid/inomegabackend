"""Real bug fixed alongside the PDF preview feature: pdf_service.py's item
table reads item["unit_name"], but fetch_item_by_code's raw row only ever had
an embedded unit_ref: {name} — unit_name never existed, so every invoice PDF's
Unit column silently fell back to "pcs" regardless of the item's real unit."""

from app.services.invoice_dispatch_service import _items_by_code


def test_items_by_code_flattens_unit_ref_into_unit_name(fake_supabase):
    fake_supabase.seed("units", "box")
    unit_id = fake_supabase.tables["units"][-1]["id"]
    fake_supabase.tables["inventory_items"].append(
        {
            "id": "item-1",
            "item_code": "ZZ-BOX-ITEM",
            "item_name": "Boxed Item",
            "unit": unit_id,
            "rate": 100,
            "cloudinary_image_url": None,
        }
    )

    result = _items_by_code(fake_supabase, [{"item_code": "ZZ-BOX-ITEM"}])

    assert result["ZZ-BOX-ITEM"]["unit_name"] == "box"
