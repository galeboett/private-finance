from app.money import cents_to_decimal_string, escape_csv_formula, parse_decimal_to_cents


def test_parse_decimal_to_cents():
    assert parse_decimal_to_cents("12.34") == 1234
    assert parse_decimal_to_cents("-5.50") == -550


def test_cents_to_decimal_string():
    assert cents_to_decimal_string(1234) == "12.34"


def test_escape_csv_formula():
    assert escape_csv_formula("=2+2") == "'=2+2"
    assert escape_csv_formula("Coffee Shop") == "Coffee Shop"

