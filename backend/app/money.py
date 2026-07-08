from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def parse_decimal_to_cents(value: str | int | float | Decimal | None) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    try:
        normalized = str(value).replace("$", "").replace(",", "").strip()
        cents = (Decimal(normalized) * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid money value: {value}") from exc
    return int(cents)


def cents_to_decimal_string(value: int | None) -> str | None:
    if value is None:
        return None
    dollars = Decimal(value) / Decimal("100")
    return format(dollars.quantize(Decimal("0.01")), "f")


def escape_csv_formula(value: str) -> str:
    if value and value[0] in {"=", "+", "-", "@"}:
        return f"'{value}"
    return value

