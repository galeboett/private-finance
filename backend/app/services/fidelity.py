from __future__ import annotations

import json
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..models import Account, AuditEvent, HoldingSnapshot, ImportBatch, NetWorthSnapshot, StagingRow
from ..money import parse_decimal_to_cents
from .accounts import merge_account_into
from .mutation_log import MutationChange, changed_values, full_values, journal_mutation
from .snapshots import refresh_holding_net_worth_snapshot


FIDELITY_HISTORY_REPAIR_EVENT = "fidelity_holding_repair_v1"


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


def repair_fidelity_holding_history(db: Session, actor: str = "system:migration") -> dict:
    if db.scalar(select(AuditEvent.id).where(AuditEvent.event_type == FIDELITY_HISTORY_REPAIR_EVENT)):
        return {"repaired": False, "operation_id": None}

    batches = db.scalars(
        select(ImportBatch)
        .where(ImportBatch.status == "committed")
        .order_by(ImportBatch.id.asc())
    ).all()
    latest_by_filename: dict[str, ImportBatch] = {}
    for batch in batches:
        if "portfolio_positions" in batch.filename.casefold():
            latest_by_filename[batch.filename.casefold()] = batch

    changes: list[MutationChange] = []
    affected_scopes: set[tuple[int, date]] = set()
    fidelity_accounts = _fidelity_accounts(db)
    metadata_before: dict[int, dict] = {}

    for batch in latest_by_filename.values():
        staging_rows = db.scalars(
            select(StagingRow).where(StagingRow.import_batch_id == batch.id).order_by(StagingRow.row_index.asc())
        ).all()
        interpreted_rows = [_interpreted_row(row) for row in staging_rows]
        interpreted_rows = [row for row in interpreted_rows if row is not None]
        matched_dates = []

        for row in interpreted_rows:
            target = resolve_fidelity_category_account(fidelity_accounts, row.get("account_name"))
            if not target:
                continue
            _repair_account_metadata(target, row, metadata_before)
            if row["row_kind"] == "ignore":
                continue
            match = _matching_holding(db, batch, row)
            if not match:
                continue
            matched_dates.append(match.snapshot_date)
            if match.account_id != target.id:
                before = changed_values(match, ["account_id"])
                affected_scopes.add((match.account_id, match.snapshot_date))
                match.account_id = target.id
                affected_scopes.add((target.id, match.snapshot_date))
                changes.append(MutationChange(match.id, before, changed_values(match, ["account_id"]), entity_type="holding_snapshot"))

        if not matched_dates:
            continue
        snapshot_date = Counter(matched_dates).most_common(1)[0][0]
        db.flush()
        for row in interpreted_rows:
            if row["row_kind"] == "ignore":
                continue
            target = resolve_fidelity_category_account(fidelity_accounts, row.get("account_name"))
            if not target or _matching_holding_on_date(db, target.id, snapshot_date, row):
                continue
            market_value_cents = _optional_money(row.get("market_value"))
            if market_value_cents is None:
                continue
            holding = HoldingSnapshot(
                account_id=target.id,
                snapshot_date=snapshot_date,
                symbol=(row.get("symbol") or "").strip() or None,
                description=(row.get("description") or "").strip() or None,
                quantity_basis_points=_basis_points(row.get("quantity")),
                price_cents=_optional_money(row.get("price")),
                market_value_cents=market_value_cents,
                cost_basis_cents=_optional_money(row.get("cost_basis")),
                asset_class=(row.get("asset_class") or "").strip() or None,
            )
            db.add(holding)
            db.flush()
            affected_scopes.add((target.id, snapshot_date))
            changes.append(MutationChange(holding.id, None, full_values(holding), entity_type="holding_snapshot"))

    for account_id, before in metadata_before.items():
        account = db.get(Account, account_id)
        changes.append(MutationChange(account_id, before, changed_values(account, ["account_type", "last_four"]), entity_type="account"))

    retirement = next((account for account in fidelity_accounts if "401k" in _normalize(account.display_name)), None)
    brokerage_link_accounts = [account for account in fidelity_accounts if _normalize(account.display_name) == "brokeragelink"]
    if retirement:
        for source in brokerage_link_accounts:
            _, merge_changes = merge_account_into(db, source, retirement, actor)
            changes.extend(merge_changes)

    db.flush()
    for account_id, snapshot_date in sorted(affected_scopes, key=lambda item: (item[1], item[0])):
        snapshot = db.scalar(
            select(NetWorthSnapshot).where(
                NetWorthSnapshot.account_id == account_id,
                NetWorthSnapshot.snapshot_date == snapshot_date,
            )
        )
        before = full_values(snapshot) if snapshot else None
        refresh_holding_net_worth_snapshot(db, account_id=account_id, snapshot_date=snapshot_date)
        db.flush()
        refreshed = db.scalar(
            select(NetWorthSnapshot).where(
                NetWorthSnapshot.account_id == account_id,
                NetWorthSnapshot.snapshot_date == snapshot_date,
            )
        )
        after = full_values(refreshed) if refreshed else None
        if before != after:
            entity_id = refreshed.id if refreshed else snapshot.id
            changes.append(MutationChange(entity_id, before, after, entity_type="net_worth_snapshot"))

    operation_id = None
    if changes:
        operation_id = journal_mutation(
            db,
            kind="cleanup",
            entity_type="mixed",
            actor=actor,
            description="Corrected Fidelity account routing and cash holdings",
            changes=changes,
        )
    record_audit_event(
        db,
        FIDELITY_HISTORY_REPAIR_EVENT,
        actor,
        "holding_snapshot",
        "fidelity-history",
        {"changes": len(changes), "operation_id": operation_id},
    )
    return {"repaired": bool(changes), "operation_id": operation_id}


def _fidelity_accounts(db: Session) -> list[Account]:
    accounts = db.scalars(select(Account).where(Account.status == "active").order_by(Account.id.asc())).all()
    return [
        account
        for account in accounts
        if (account.institution and account.institution.name.casefold() == "fidelity")
        or fidelity_account_category(account.display_name)
        or _normalize(account.display_name) == "brokeragelink"
    ]


def _interpreted_row(staging_row: StagingRow) -> dict | None:
    try:
        row = json.loads(staging_row.normalized_json or staging_row.raw_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if not row.get("account_name"):
        return None
    row["row_kind"] = fidelity_position_row_kind(
        account_name=row.get("account_name"),
        symbol=row.get("symbol"),
        description=row.get("description"),
    )
    return row


def _repair_account_metadata(account: Account, row: dict, before_by_account: dict[int, dict]) -> None:
    category = fidelity_account_category(row.get("account_name"))
    account_number = "".join(character for character in str(row.get("account_number") or "") if character.isdigit())
    next_type = "retirement" if category == "401k" else account.account_type
    next_last_four = account.last_four
    if category in {"hsa", "individual"} and len(account_number) >= 4:
        next_last_four = account_number[-4:]
    elif category == "401k" and "amazon" in _normalize(row.get("account_name") or "") and len(account_number) >= 4:
        next_last_four = account_number[-4:]
    if next_type == account.account_type and next_last_four == account.last_four:
        return
    before_by_account.setdefault(account.id, changed_values(account, ["account_type", "last_four"]))
    account.account_type = next_type
    account.last_four = next_last_four


def _matching_holding(db: Session, batch: ImportBatch, row: dict) -> HoldingSnapshot | None:
    earliest = batch.created_at - timedelta(minutes=1)
    latest = batch.created_at + timedelta(minutes=5)
    candidates = db.scalars(
        select(HoldingSnapshot).where(HoldingSnapshot.created_at >= earliest, HoldingSnapshot.created_at <= latest)
    ).all()
    matches = [holding for holding in candidates if _holding_values_match(holding, row)]
    return matches[0] if len(matches) == 1 else None


def _matching_holding_on_date(db: Session, account_id: int, snapshot_date: date, row: dict) -> HoldingSnapshot | None:
    candidates = db.scalars(
        select(HoldingSnapshot).where(
            HoldingSnapshot.account_id == account_id,
            HoldingSnapshot.snapshot_date == snapshot_date,
        )
    ).all()
    return next((holding for holding in candidates if _holding_values_match(holding, row)), None)


def _holding_values_match(holding: HoldingSnapshot, row: dict) -> bool:
    symbol = (row.get("symbol") or "").strip().upper() or None
    description = (row.get("description") or "").strip().casefold()
    market_value_cents = _optional_money(row.get("market_value"))
    quantity_basis_points = _basis_points(row.get("quantity"))
    if ((holding.symbol or "").strip().upper() or None) != symbol:
        return False
    if (holding.description or "").strip().casefold() != description:
        return False
    if holding.market_value_cents != market_value_cents:
        return False
    return quantity_basis_points is None or holding.quantity_basis_points == quantity_basis_points


def _basis_points(value) -> int | None:
    if value is None or str(value).strip() in {"", "--"}:
        return None
    try:
        return int((Decimal(str(value).replace(",", "").strip()) * Decimal("10000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return None


def _optional_money(value) -> int | None:
    if value is None or str(value).strip() in {"", "--"}:
        return None
    try:
        return parse_decimal_to_cents(value)
    except ValueError:
        return None


def _normalize(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())
