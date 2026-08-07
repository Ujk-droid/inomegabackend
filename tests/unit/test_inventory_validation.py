from app.services.inventory_service import parse_and_validate_row


def test_valid_row_parses():
    item, err = parse_and_validate_row(
        {"item_code": "p-16-s-a-mk", "item_name": "Platform Scale", "unit": "pcs", "rate": "12300"}, 2
    )
    assert err is None
    assert item.item_code == "P-16-S-A-MK"  # normalized uppercase, matches Section 2.1's format
    assert item.rate == 12300
    assert item.quantity_in_stock == 0  # default
    assert item.min_threshold == 5  # default


def test_missing_item_code_is_rejected():
    item, err = parse_and_validate_row({"item_name": "X", "unit": "pcs", "rate": "100"}, 2)
    assert item is None
    assert err.row == 2
    assert "item_code" in err.error


def test_missing_item_name_is_rejected():
    item, err = parse_and_validate_row({"item_code": "X-1", "unit": "pcs", "rate": "100"}, 3)
    assert item is None
    assert "item_name" in err.error


def test_missing_unit_is_rejected():
    item, err = parse_and_validate_row({"item_code": "X-1", "item_name": "X", "rate": "100"}, 4)
    assert item is None
    assert "unit" in err.error


def test_non_numeric_rate_is_rejected():
    item, err = parse_and_validate_row({"item_code": "X-1", "item_name": "X", "unit": "pcs", "rate": "abc"}, 5)
    assert item is None
    assert "not a number" in err.error


def test_zero_or_negative_rate_is_rejected():
    item, err = parse_and_validate_row({"item_code": "X-1", "item_name": "X", "unit": "pcs", "rate": "0"}, 6)
    assert item is None
    assert "greater than 0" in err.error


def test_negative_quantity_is_rejected():
    item, err = parse_and_validate_row(
        {"item_code": "X-1", "item_name": "X", "unit": "pcs", "rate": "10", "quantity_in_stock": "-5"}, 7
    )
    assert item is None
    assert "negative" in err.error


def test_non_integer_min_threshold_is_rejected():
    item, err = parse_and_validate_row(
        {"item_code": "X-1", "item_name": "X", "unit": "pcs", "rate": "10", "min_threshold": "five"}, 8
    )
    assert item is None
    assert "min_threshold" in err.error


def test_blank_category_fields_become_none():
    item, err = parse_and_validate_row(
        {"item_code": "X-1", "item_name": "X", "unit": "pcs", "rate": "10", "category_1": "", "category_2": None},
        9,
    )
    assert err is None
    assert item.category_1 is None
    assert item.category_2 is None


def test_item_code_is_trimmed_and_uppercased():
    item, err = parse_and_validate_row(
        {"item_code": "  x-9  ", "item_name": "X", "unit": "pcs", "rate": "10"}, 10
    )
    assert err is None
    assert item.item_code == "X-9"
