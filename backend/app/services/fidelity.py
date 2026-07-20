from __future__ import annotations

from ..models import Account


def fidelity_account_category(account_name: str | None) -> str | None:
    normalized = _normalize(account_name or "")
    if normalized == "401k" or "brokeragelink" in normalized or ("amazon" in normalized and "401k" in normalized):
        return "401k"
    if normalized == "hsa" or "healthsavingsaccount" in normalized:
        return "hsa"
    if normalized == "individual" or "individualbrokerage" in normalized:
        return "individual"
    return None


def fidelity_position_row_kind(*, account_name: str | None, symbol: str | None, description: str | None) -> str:
    category = fidelity_account_category(account_name)
    normalized_symbol = (symbol or "").strip()
    normalized_description = _normalize(description or "")
    if category == "401k" and not normalized_symbol and normalized_description == "brokeragelink":
        return "ignore"
    return "position"


def resolve_fidelity_category_account(candidates: list[Account], account_name: str | None) -> Account | None:
    category = fidelity_account_category(account_name)
    if not category:
        return None
    for candidate in candidates:
        normalized = _normalize(candidate.display_name)
        if category == "401k" and "401k" in normalized:
            return candidate
        if category == "hsa" and (normalized == "hsa" or "healthsavingsaccount" in normalized):
            return candidate
        if category == "individual" and "individual" in normalized:
            return candidate
    return None


def _normalize(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())
