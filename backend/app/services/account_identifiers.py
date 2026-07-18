from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Account, AccountIdentifier


CARD_IDENTIFIER_TYPE = "card_last_four"
ACCOUNT_IDENTIFIER_TYPE = "account_last_four"


def normalize_last_four(value: str | None) -> str | None:
    digits = "".join(character for character in (value or "") if character.isdigit())
    return digits[-4:] if len(digits) >= 4 else None


def identifier_type_for_account(account: Account) -> str:
    return CARD_IDENTIFIER_TYPE if account.account_type == "credit_card" else ACCOUNT_IDENTIFIER_TYPE


def record_account_identifier(
    db: Session,
    account: Account,
    last_four: str,
    *,
    make_current: bool = True,
    source: str = "manual",
) -> AccountIdentifier:
    normalized = normalize_last_four(last_four)
    if not normalized:
        raise ValueError("Enter the last four digits of the account or card number")
    identifier_type = identifier_type_for_account(account)
    existing = db.scalar(
        select(AccountIdentifier).where(
            AccountIdentifier.account_id == account.id,
            AccountIdentifier.identifier_type == identifier_type,
            AccountIdentifier.identifier_value == normalized,
        )
    )
    if make_current:
        previous = db.scalars(
            select(AccountIdentifier).where(
                AccountIdentifier.account_id == account.id,
                AccountIdentifier.identifier_type == identifier_type,
                AccountIdentifier.is_current.is_(True),
                AccountIdentifier.identifier_value != normalized,
            )
        ).all()
        for identifier in previous:
            identifier.is_current = False
            identifier.valid_to = date.today()
    if existing is None:
        existing = AccountIdentifier(
            account_id=account.id,
            identifier_type=identifier_type,
            identifier_value=normalized,
            is_current=make_current,
            source=source,
            valid_from=date.today() if make_current else None,
        )
        db.add(existing)
    elif make_current:
        existing.is_current = True
        existing.source = source
        existing.valid_from = existing.valid_from or date.today()
        existing.valid_to = None
    if make_current:
        account.last_four = normalized
    db.flush()
    return existing


def matching_accounts_for_last_four(db: Session, accounts: list[Account], last_four: str | None) -> list[Account]:
    normalized = normalize_last_four(last_four)
    if not normalized:
        return []
    account_ids = {account.id for account in accounts}
    matching_ids = set(
        db.scalars(
            select(AccountIdentifier.account_id).where(
                AccountIdentifier.account_id.in_(account_ids),
                AccountIdentifier.identifier_value == normalized,
            )
        ).all()
    ) if account_ids else set()
    return [account for account in accounts if account.id in matching_ids or normalize_last_four(account.last_four) == normalized]


def replacement_card_candidate(db: Session, accounts: list[Account], proposed: dict) -> Account | None:
    if proposed.get("account_type") != "credit_card" or not normalize_last_four(proposed.get("last_four")):
        return None
    proposed_institution = (proposed.get("institution_name") or "").casefold()
    candidates = [
        account
        for account in accounts
        if account.account_type == "credit_card"
        and account.institution
        and proposed_institution
        and (
            proposed_institution in account.institution.name.casefold()
            or account.institution.name.casefold() in proposed_institution
        )
        and normalize_last_four(account.last_four) != normalize_last_four(proposed.get("last_four"))
    ]
    return candidates[0] if len(candidates) == 1 else None


def backfill_account_identifiers(db: Session) -> int:
    created = 0
    accounts = db.scalars(select(Account).where(Account.last_four.is_not(None))).all()
    for account in accounts:
        normalized = normalize_last_four(account.last_four)
        if not normalized:
            continue
        identifier_type = identifier_type_for_account(account)
        existing = db.scalar(
            select(AccountIdentifier).where(
                AccountIdentifier.account_id == account.id,
                AccountIdentifier.identifier_type == identifier_type,
                AccountIdentifier.identifier_value == normalized,
            )
        )
        if existing is None:
            db.add(
                AccountIdentifier(
                    account_id=account.id,
                    identifier_type=identifier_type,
                    identifier_value=normalized,
                    is_current=True,
                    source="backfill",
                )
            )
            created += 1
    db.flush()
    return created
