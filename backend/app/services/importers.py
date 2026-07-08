from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..models import Account, CategoryRule, HoldingSnapshot, ImportBatch, ImportPreset, StagingRow, Transaction
from ..money import parse_decimal_to_cents


CARD_REFERENCE_HEADER = "Posted Date,Reference Number,Payee,Address,Amount"
CHASE_ACTIVITY_HEADER = "Transaction Date,Post Date,Description,Category,Type,Amount,Memo"
CHECKING_HEADER = "Date,Description,Amount,Running Bal."
FIDELITY_HEADER = "Account Number,Account Name,Symbol,Description,Quantity,Last Price,Last Price Change,Current Value"


@dataclass
class PreviewResult:
    rows: list[dict]
    warnings: list[str]
    detected_preset: str | None


def detect_preset_from_content(text: str) -> str | None:
    for marker, preset in (
        (CARD_REFERENCE_HEADER, "card_reference"),
        (CHASE_ACTIVITY_HEADER, "card_activity"),
        (CHECKING_HEADER, "checking_running_balance"),
        (FIDELITY_HEADER, "brokerage_positions"),
    ):
        if marker in text:
            return preset
    return None


def parse_csv_preview(content: bytes, preset_type: str) -> PreviewResult:
    text = content.decode("utf-8-sig")
    reader = list(csv.reader(io.StringIO(text)))
    warnings: list[str] = []

    if preset_type == "checking_running_balance":
        header_index = next((i for i, row in enumerate(reader) if row[:4] == ["Date", "Description", "Amount", "Running Bal."]), -1)
        if header_index < 0:
            raise ValueError("Could not find checking ledger header")
        rows = []
        for idx, row in enumerate(reader[header_index + 1 :], start=header_index + 2):
            if not any(cell.strip() for cell in row):
                continue
            if len(row) < 4:
                warnings.append(f"Row {idx} is incomplete")
                continue
            if row[1].startswith("Beginning balance"):
                kind = "balance_marker"
            else:
                kind = "transaction"
            rows.append(
                {
                    "row_index": idx,
                    "row_kind": kind,
                    "transaction_date": row[0],
                    "raw_description": row[1],
                    "amount": row[2],
                    "running_balance": row[3],
                }
            )
        return PreviewResult(rows=rows, warnings=warnings, detected_preset=preset_type)

    header_index = next((i for i, row in enumerate(reader) if ",".join(row).startswith(CARD_REFERENCE_HEADER) or ",".join(row).startswith(CHASE_ACTIVITY_HEADER) or ",".join(row).startswith(FIDELITY_HEADER)), 0)
    dict_reader = csv.DictReader(io.StringIO(text))
    rows = []
    for idx, row in enumerate(dict_reader, start=2):
        if not any((value or "").strip() for value in row.values()):
            continue
        row_kind = "transaction"
        if preset_type == "brokerage_positions":
            if row.get("Account Number", "").startswith("Date downloaded") or not row.get("Account Number"):
                continue
            description = row.get("Description") or ""
            if not description and not row.get("Symbol") and not row.get("Current Value"):
                continue
            upper_description = description.upper()
            if upper_description.startswith("BROKERAGELINK") or upper_description.startswith("HELD IN"):
                row_kind = "ignore"
            else:
                row_kind = "position"
            rows.append(
                {
                    "row_index": idx,
                    "row_kind": row_kind,
                    "snapshot_date": None,
                    "account_number": row.get("Account Number"),
                    "symbol": row.get("Symbol"),
                    "description": description,
                    "quantity": row.get("Quantity"),
                    "price": row.get("Last Price"),
                    "market_value": row.get("Current Value"),
                    "asset_class": row.get("Type"),
                    "account_name": row.get("Account Name"),
                }
            )
        elif preset_type == "card_activity":
            rows.append(
                {
                    "row_index": idx,
                    "row_kind": row_kind,
                    "transaction_date": row.get("Transaction Date"),
                    "posted_date": row.get("Post Date"),
                    "raw_description": row.get("Description"),
                    "amount": row.get("Amount"),
                    "source_reference": row.get("Memo"),
                    "bank_category": row.get("Category"),
                }
            )
        else:
            rows.append(
                {
                    "row_index": idx,
                    "row_kind": row_kind,
                    "transaction_date": row.get("Posted Date"),
                    "raw_description": row.get("Payee"),
                    "amount": row.get("Amount"),
                    "source_reference": row.get("Reference Number"),
                }
            )
    return PreviewResult(rows=rows, warnings=warnings, detected_preset=preset_type)


def _normalize_transaction_type(description: str, amount_cents: int, account_type: str) -> str:
    text = description.upper()
    if "PAYMENT" in text and account_type == "credit_card":
        return "credit_card_payment"
    if "TRANSFER" in text:
        return "transfer"
    if amount_cents > 0 and account_type in {"checking", "savings"}:
        return "income"
    if amount_cents > 0 and account_type == "credit_card":
        return "refund"
    return "expense"


def _source_hash(account_id: int, date_value: str, amount: str, description: str, source_reference: str | None, ordinal: int) -> str:
    payload = "|".join([str(account_id), date_value or "", amount or "", description or "", source_reference or "", str(ordinal)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def preview_import(content: bytes, preset_type: str) -> PreviewResult:
    return parse_csv_preview(content, preset_type)


def commit_import(db: Session, account, preset: ImportPreset | None, filename: str, content: bytes, actor: str = "local-user") -> dict:
    detected = preset.preset_type if preset else detect_preset_from_content(content.decode("utf-8-sig"))
    if not detected:
        raise ValueError("Unable to detect preset type")
    preview = preview_import(content, detected)
    file_hash = hashlib.sha256(content).hexdigest()
    batch = ImportBatch(account_id=account.id, preset_id=preset.id if preset else None, filename=filename, file_hash=file_hash, status="committed")
    db.add(batch)
    db.flush()

    inserted = 0
    skipped = 0
    warnings = list(preview.warnings)
    description_counter: Counter[tuple[str, str, str | None]] = Counter()
    rules = db.scalars(select(CategoryRule).order_by(CategoryRule.priority.asc())).all()

    for row in preview.rows:
        target_account = account
        if detected == "brokerage_positions":
            target_account, routing_warning = _resolve_brokerage_account(db, account, row)
            if routing_warning and routing_warning not in warnings:
                warnings.append(routing_warning)
        db.add(
            StagingRow(
                import_batch_id=batch.id,
                account_id=target_account.id,
                row_index=row["row_index"],
                row_kind=row["row_kind"],
                raw_json=json.dumps(row, default=str),
                normalized_json=json.dumps(row, default=str),
            )
        )
        if detected == "brokerage_positions":
            if row["row_kind"] == "ignore":
                continue
            market_value_cents = parse_decimal_to_cents(row.get("market_value"))
            if market_value_cents is not None:
                db.add(
                    HoldingSnapshot(
                        account_id=target_account.id,
                        snapshot_date=_extract_snapshot_date(filename),
                        symbol=row.get("symbol"),
                        description=row.get("description"),
                        quantity_basis_points=_parse_decimal_to_basis_points(row.get("quantity")),
                        price_cents=parse_decimal_to_cents(row.get("price")),
                        market_value_cents=market_value_cents,
                        asset_class=row.get("asset_class"),
                    )
                )
                inserted += 1
            continue

        if row["row_kind"] != "transaction":
            continue

        key = (row.get("transaction_date") or "", row.get("amount") or "", row.get("raw_description") or "")
        description_counter[key] += 1
        ordinal = description_counter[key]
        source_hash = _source_hash(
            account.id,
            row.get("transaction_date") or "",
            row.get("amount") or "",
            row.get("raw_description") or "",
            row.get("source_reference"),
            ordinal,
        )
        existing = db.scalar(select(Transaction).where(Transaction.account_id == account.id, Transaction.source_hash == source_hash))
        if existing:
            skipped += 1
            continue

        amount_cents = parse_decimal_to_cents(row.get("amount")) or 0
        review_status = "needs_review"
        category_id = None
        normalized = (row.get("raw_description") or "").strip()
        for rule in rules:
            haystack = normalized.upper()
            if rule.field_name == "raw_description" and rule.match_text.upper() in haystack:
                category_id = rule.category_id
                review_status = "suggested"
                break

        transaction = Transaction(
            account_id=account.id,
            import_batch_id=batch.id,
            transaction_date=datetime.strptime(row.get("transaction_date"), "%m/%d/%Y").date(),
            posted_date=datetime.strptime(row.get("posted_date"), "%m/%d/%Y").date() if row.get("posted_date") else None,
            amount_cents=amount_cents,
            raw_description=normalized,
            normalized_payee=normalized[:255],
            transaction_type=_normalize_transaction_type(normalized, amount_cents, account.account_type),
            category_id=category_id,
            review_status=review_status,
            source_hash=source_hash,
            source_reference=row.get("source_reference"),
            source_ordinal=ordinal,
            running_balance_cents=parse_decimal_to_cents(row.get("running_balance")),
        )
        if _is_possible_duplicate(db, account.id, transaction):
            transaction.review_status = "possible_duplicate"
        db.add(transaction)
        inserted += 1

    batch.imported_rows = inserted
    batch.skipped_duplicates = skipped
    batch.warnings_json = json.dumps(warnings)
    record_audit_event(db, "import_commit", actor, "import_batch", str(batch.id), {"filename": filename, "inserted": inserted, "skipped": skipped})
    return {"batch_id": batch.id, "inserted": inserted, "skipped": skipped, "warnings": warnings}


def _resolve_brokerage_account(db: Session, selected_account: Account, row: dict) -> tuple[Account, str | None]:
    account_name = (row.get("account_name") or "").strip()
    account_number = "".join(char for char in (row.get("account_number") or "") if char.isdigit())
    query = select(Account).where(Account.status == "active")
    if selected_account.institution_id:
        query = query.where(Account.institution_id == selected_account.institution_id)
    else:
        query = query.where(Account.id == selected_account.id)
    candidates = db.scalars(query).all()

    for candidate in candidates:
        if candidate.last_four and account_number.endswith(candidate.last_four):
            return candidate, None

    normalized_row_name = _normalize_account_name(account_name)
    for candidate in candidates:
        normalized_display = _normalize_account_name(candidate.display_name)
        if normalized_display and normalized_row_name and (normalized_display in normalized_row_name or normalized_row_name in normalized_display):
            return candidate, None

    label = account_name or row.get("account_number") or "unknown account"
    return selected_account, f'Could not match brokerage account "{label}"; assigned those holdings to the selected account "{selected_account.display_name}".'


def _normalize_account_name(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def _parse_decimal_to_basis_points(value: str | int | float | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        normalized = str(value).replace(",", "").strip()
        return int((Decimal(normalized) * Decimal("10000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid quantity value: {value}") from exc


def _is_possible_duplicate(db: Session, account_id: int, candidate: Transaction) -> bool:
    existing = db.scalars(
        select(Transaction).where(
            Transaction.account_id == account_id,
            Transaction.transaction_date == candidate.transaction_date,
            Transaction.amount_cents == candidate.amount_cents,
            Transaction.raw_description != candidate.raw_description,
        )
    ).all()
    return bool(existing)


def _extract_snapshot_date(filename: str) -> date:
    for token in filename.replace(".", "-").split("-"):
        if token.isdigit() and len(token) == 4:
            # Loose fallback when filename doesn't clearly encode a date.
            return date.today()
    return date.today()
