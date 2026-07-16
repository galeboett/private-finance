from __future__ import annotations

import re
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..models import Account, CategoryRule, HoldingSnapshot, ImportBatch, NetWorthSnapshot, StatementCheckpoint, StagingRow, Transaction
from ..money import parse_decimal_to_cents
from .dedupe import canonical_source_hash, find_reference_matches
from .mutation_log import MutationChange, changed_values, full_values, journal_mutation


@dataclass(frozen=True)
class OfxParseResult:
    rows: list[dict]
    warnings: list[str]
    account: dict[str, str | None]


POSITION_TAGS = ("POSSTOCK", "POSMF", "POSDEBT", "POSOPT", "POSOTHER")
SECURITY_INFO_TAGS = ("STOCKINFO", "MFINFO", "DEBTINFO", "OPTINFO", "OTHERINFO")


def parse_ofx(content: bytes) -> OfxParseResult:
    """Parse the small, useful subset shared by OFX 1.x SGML and OFX 2.x XML.

    OFX 1.x commonly omits closing tags for leaf values, so a strict XML parser
    cannot read many real bank downloads. The tokenizer below deliberately reads
    container blocks and leaf values without trying to model the whole standard.
    """
    text = _decode_ofx(content)
    body = _normalize_tags(text[text.upper().find("<OFX>") :] if "<OFX>" in text.upper() else text)
    if "<OFX" not in body.upper():
        raise ValueError("This file does not contain an OFX document")

    account = _account_metadata(body)
    rows: list[dict] = []
    warnings: list[str] = []

    for index, block in enumerate(_blocks(body, "STMTTRN"), start=1):
        posted = _ofx_date(_value(block, "DTPOSTED"))
        amount = _decimal_text(_value(block, "TRNAMT"))
        fitid = _value(block, "FITID")
        description = " ".join(filter(None, (_value(block, "NAME"), _value(block, "MEMO"))))
        if not posted or amount is None or not fitid:
            warnings.append(f"Skipped OFX transaction {index} because its date, amount, or FITID was missing.")
            continue
        rows.append(
            {
                "row_index": len(rows) + 1,
                "row_kind": "transaction",
                "transaction_date": posted.isoformat(),
                "raw_description": description or _value(block, "TRNTYPE") or "OFX transaction",
                "amount": amount,
                "source_reference": fitid,
                "bank_category": _value(block, "TRNTYPE"),
            }
        )

    balance_block = next(iter(_blocks(body, "LEDGERBAL")), None)
    balance_kind = "ledger"
    if balance_block is None:
        balance_block = next(iter(_blocks(body, "AVAILBAL")), None)
        balance_kind = "available"
    if balance_block:
        balance = _decimal_text(_value(balance_block, "BALAMT"))
        as_of = _ofx_date(_value(balance_block, "DTASOF"))
        if balance is not None and as_of:
            rows.append(
                {
                    "row_index": len(rows) + 1,
                    "row_kind": "balance_anchor",
                    "statement_date": as_of.isoformat(),
                    "statement_balance": balance,
                    "balance_kind": balance_kind,
                }
            )
        else:
            warnings.append("The OFX balance block was present but did not contain both BALAMT and DTASOF.")

    securities = _security_registry(body)
    for position_tag in POSITION_TAGS:
        for block in _blocks(body, position_tag):
            unique_id = _value(block, "UNIQUEID")
            security = securities.get(unique_id or "", {})
            units = _decimal_text(_value(block, "UNITS"))
            price = _decimal_text(_value(block, "UNITPRICE"))
            market_value = _decimal_text(_value(block, "MKTVAL"))
            as_of = _ofx_date(_value(block, "DTPRICEASOF"))
            if market_value is None and units is not None and price is not None:
                market_value = _multiply_decimal_text(units, price)
            if market_value is None or not as_of:
                warnings.append(f"Skipped OFX position {unique_id or position_tag} because value or as-of date was missing.")
                continue
            rows.append(
                {
                    "row_index": len(rows) + 1,
                    "row_kind": "position",
                    "snapshot_date": as_of.isoformat(),
                    "symbol": security.get("symbol") or unique_id,
                    "description": security.get("description") or unique_id or "OFX position",
                    "quantity": units,
                    "price": price,
                    "market_value": market_value,
                    "cost_basis": None,
                    "asset_class": position_tag.removeprefix("POS").title(),
                    "account_number": account.get("account_id"),
                    "account_name": account.get("account_name"),
                }
            )

    if not rows:
        raise ValueError("The OFX file did not contain transactions, a statement balance, or investment positions")
    return OfxParseResult(rows=rows, warnings=warnings, account=account)


def suggest_ofx_account(db: Session, content: bytes) -> tuple[Account | None, int, str, dict]:
    parsed = parse_ofx(content)
    metadata = parsed.account
    proposed = {
        "institution_name": metadata.get("institution"),
        "display_name": metadata.get("account_name") or "OFX Account",
        "account_type": metadata.get("account_type") or "checking",
        "currency": metadata.get("currency") or "USD",
        "last_four": metadata.get("last_four"),
    }
    accounts = db.scalars(select(Account).where(Account.status == "active", Account.account_type != "external")).all()
    last_four = metadata.get("last_four")
    matching_last_four = [account for account in accounts if last_four and account.last_four == last_four]
    if len(matching_last_four) == 1:
        return matching_last_four[0], 100, "Matched the OFX account number to this account's last four digits.", proposed
    typed = [account for account in accounts if account.account_type == metadata.get("account_type")]
    institution = (metadata.get("institution") or "").casefold()
    institution_matches = [
        account for account in typed
        if account.institution and institution and (institution in account.institution.name.casefold() or account.institution.name.casefold() in institution)
    ]
    if len(institution_matches) == 1:
        return institution_matches[0], 85, "Matched the OFX institution and account type.", proposed
    if len(typed) == 1 and not last_four:
        return typed[0], 70, "Matched the only active account of this OFX account type.", proposed
    return None, 0, "Choose the account for this OFX/QFX statement once; its account number will match future downloads.", proposed


def semantic_ofx_hash(content: bytes) -> str:
    parsed = parse_ofx(content)
    canonical = [
        json.dumps({key: value for key, value in row.items() if key != "row_index"}, sort_keys=True, separators=(",", ":"))
        for row in parsed.rows
    ]
    payload = json.dumps({"preset_type": "ofx_statement", "rows": sorted(canonical)}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def commit_ofx_import(
    db: Session,
    account: Account,
    filename: str,
    content: bytes,
    *,
    actor: str,
    existing_batch: ImportBatch | None = None,
) -> dict:
    parsed = parse_ofx(content)
    file_hash = hashlib.sha256(content).hexdigest()
    semantic_hash = semantic_ofx_hash(content)
    if existing_batch:
        batch = existing_batch
        batch.account_id = account.id
        batch.filename = filename
        batch.file_hash = file_hash
        batch.semantic_hash = semantic_hash
        batch.status = "committed"
        batch.detected_preset = "ofx_statement"
        batch.sign_convention = "preset"
        db.execute(delete(StagingRow).where(StagingRow.import_batch_id == batch.id))
    else:
        batch = ImportBatch(
            account_id=account.id,
            filename=filename,
            file_hash=file_hash,
            semantic_hash=semantic_hash,
            status="committed",
            detected_preset="ofx_statement",
            sign_convention="preset",
        )
        db.add(batch)
        db.flush()

    changes: list[MutationChange] = []
    created_transactions: list[Transaction] = []
    created_holdings: list[HoldingSnapshot] = []
    inserted = 0
    skipped = 0
    warnings = list(parsed.warnings)
    rules = db.scalars(select(CategoryRule).order_by(CategoryRule.priority, CategoryRule.id)).all()
    ordinals: Counter[tuple[str, str, str]] = Counter()
    cleared_holding_dates: set[date] = set()

    for row in parsed.rows:
        db.add(
            StagingRow(
                import_batch_id=batch.id,
                account_id=account.id,
                row_index=int(row["row_index"]),
                row_kind=str(row["row_kind"]),
                raw_json=json.dumps(row, default=str),
                normalized_json=json.dumps(row, default=str),
            )
        )
        if row["row_kind"] == "position":
            snapshot_date = date.fromisoformat(str(row["snapshot_date"]))
            if snapshot_date not in cleared_holding_dates:
                stale = db.scalars(
                    select(HoldingSnapshot).where(HoldingSnapshot.account_id == account.id, HoldingSnapshot.snapshot_date == snapshot_date)
                ).all()
                for holding in stale:
                    changes.append(MutationChange(holding.id, full_values(holding), None, entity_type="holding_snapshot"))
                    db.delete(holding)
                if stale:
                    db.flush()
                cleared_holding_dates.add(snapshot_date)
            holding = HoldingSnapshot(
                account_id=account.id,
                snapshot_date=snapshot_date,
                symbol=(str(row.get("symbol") or "").strip().upper() or None),
                description=str(row.get("description") or "").strip() or None,
                quantity_basis_points=_basis_points(row.get("quantity")),
                price_cents=parse_decimal_to_cents(row.get("price")),
                market_value_cents=parse_decimal_to_cents(row.get("market_value")) or 0,
                cost_basis_cents=None,
                asset_class=str(row.get("asset_class") or "").strip() or None,
            )
            db.add(holding)
            created_holdings.append(holding)
            inserted += 1
            continue
        if row["row_kind"] == "balance_anchor":
            _upsert_balance_anchor(db, account, row, changes)
            inserted += 1
            continue
        if row["row_kind"] != "transaction":
            continue

        transaction_date = date.fromisoformat(str(row["transaction_date"]))
        amount_cents = parse_decimal_to_cents(row.get("amount")) or 0
        description = str(row.get("raw_description") or "OFX transaction").strip()
        reference = str(row.get("source_reference") or "").strip()
        exact_reference, reference_conflict = find_reference_matches(
            db,
            account_id=account.id,
            reference=reference,
            transaction_date=transaction_date,
            amount_cents=amount_cents,
        )
        if exact_reference:
            skipped += 1
            continue
        key = (transaction_date.isoformat(), str(amount_cents), description.casefold())
        ordinals[key] += 1
        source_hash = canonical_source_hash(transaction_date, amount_cents, description, reference, ordinals[key])
        if db.scalar(select(Transaction.id).where(Transaction.account_id == account.id, Transaction.source_hash == source_hash)):
            skipped += 1
            continue
        category_id = None
        rule_type = None
        review_status = "needs_review"
        for rule in rules:
            if rule.field_name == "raw_description" and rule.match_text.casefold() in description.casefold():
                category_id = rule.category_id
                rule_type = rule.suggested_transaction_type
                review_status = "suggested"
                break
        transaction = Transaction(
            account_id=account.id,
            import_batch_id=batch.id,
            transaction_date=transaction_date,
            amount_cents=amount_cents,
            raw_description=description,
            normalized_payee=description[:255],
            transaction_type=rule_type or _transaction_type(description, amount_cents, account.account_type),
            category_id=category_id,
            review_status="possible_duplicate" if reference_conflict else review_status,
            source_hash=source_hash,
            source_reference=reference,
            source_ordinal=ordinals[key],
            duplicate_of_transaction_id=reference_conflict.id if reference_conflict else None,
        )
        if reference_conflict:
            warnings.append(f'OFX FITID {reference} already exists with a different date or amount; the new row was flagged for review.')
        db.add(transaction)
        created_transactions.append(transaction)
        inserted += 1

    db.flush()
    for holding in created_holdings:
        changes.append(MutationChange(holding.id, None, full_values(holding), entity_type="holding_snapshot"))
    for transaction in created_transactions:
        changes.append(MutationChange(transaction.id, None, changed_values(transaction, ["deleted_at"]), entity_type="transaction"))
    for snapshot_date in cleared_holding_dates:
        total = db.scalar(
            select(func.sum(HoldingSnapshot.market_value_cents)).where(
                HoldingSnapshot.account_id == account.id,
                HoldingSnapshot.snapshot_date == snapshot_date,
            )
        )
        if total is not None:
            _upsert_net_worth_snapshot(db, account.id, snapshot_date, total, "import", changes)

    batch.imported_rows = inserted
    batch.skipped_duplicates = skipped
    batch.warnings_json = json.dumps(list(dict.fromkeys(warnings)))
    operation_id = None
    if changes:
        operation_id = journal_mutation(
            db,
            kind="import",
            entity_type="import_batch",
            actor=actor,
            description=f'Imported OFX statement "{filename}"',
            changes=changes,
        )
    record_audit_event(
        db,
        "import_commit",
        actor,
        "import_batch",
        str(batch.id),
        {"filename": filename, "inserted": inserted, "skipped": skipped, "operation_id": operation_id, "format": "ofx"},
    )
    return {"batch_id": batch.id, "inserted": inserted, "skipped": skipped, "warnings": list(dict.fromkeys(warnings)), "operation_id": operation_id}


def _upsert_balance_anchor(db: Session, account: Account, row: dict, changes: list[MutationChange]) -> None:
    statement_date = date.fromisoformat(str(row["statement_date"]))
    balance_cents = parse_decimal_to_cents(row.get("statement_balance")) or 0
    checkpoint = db.scalar(
        select(StatementCheckpoint).where(
            StatementCheckpoint.account_id == account.id,
            StatementCheckpoint.statement_date == statement_date,
        )
    )
    before = full_values(checkpoint) if checkpoint else None
    if checkpoint is None:
        checkpoint = StatementCheckpoint(
            account_id=account.id,
            statement_date=statement_date,
            statement_balance_cents=balance_cents,
            source="import",
        )
        db.add(checkpoint)
        db.flush()
    elif checkpoint.source != "manual":
        checkpoint.statement_balance_cents = balance_cents
        checkpoint.source = "import"
        db.flush()
    effective_balance = checkpoint.statement_balance_cents
    after = full_values(checkpoint)
    if before != after:
        changes.append(MutationChange(checkpoint.id, before, after, entity_type="statement_checkpoint"))
    _upsert_net_worth_snapshot(db, account.id, statement_date, effective_balance, checkpoint.source, changes)


def _upsert_net_worth_snapshot(
    db: Session,
    account_id: int,
    snapshot_date: date,
    balance_cents: int,
    source: str,
    changes: list[MutationChange],
) -> None:
    snapshot = db.scalar(
        select(NetWorthSnapshot).where(
            NetWorthSnapshot.account_id == account_id,
            NetWorthSnapshot.snapshot_date == snapshot_date,
        )
    )
    before = full_values(snapshot) if snapshot else None
    if snapshot is None:
        snapshot = NetWorthSnapshot(account_id=account_id, snapshot_date=snapshot_date, balance_cents=balance_cents, source=source)
        db.add(snapshot)
        db.flush()
    else:
        snapshot.balance_cents = balance_cents
        snapshot.source = source
        db.flush()
    after = full_values(snapshot)
    if before != after:
        changes.append(MutationChange(snapshot.id, before, after, entity_type="net_worth_snapshot"))


def _basis_points(value: object) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int((Decimal(str(value)) * Decimal("10000")).quantize(Decimal("1")))
    except (InvalidOperation, ValueError):
        return None


def _transaction_type(description: str, amount_cents: int, account_type: str) -> str:
    folded = description.casefold()
    if account_type == "credit_card" and amount_cents > 0 and ("payment" in folded or "autopay" in folded):
        return "credit_card_payment"
    if "transfer" in folded:
        return "transfer"
    if account_type == "credit_card" and amount_cents > 0:
        return "refund"
    if account_type in {"checking", "savings"} and amount_cents > 0:
        return "income"
    return "investment_flow" if account_type in {"brokerage", "retirement"} else "expense"


def _decode_ofx(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("The OFX file uses an unsupported text encoding")


def _normalize_tags(text: str) -> str:
    # Strip optional XML namespace prefixes while preserving container text.
    return re.sub(r"<(/?)(?:[A-Za-z_][\w.-]*:)([A-Za-z0-9_.-]+)", r"<\1\2", text)


def _blocks(text: str, tag: str) -> list[str]:
    upper = text.upper()
    start_token = f"<{tag}>"
    end_token = f"</{tag}>"
    starts = [match.start() for match in re.finditer(re.escape(start_token), upper)]
    blocks: list[str] = []
    for index, start in enumerate(starts):
        content_start = start + len(start_token)
        explicit_end = upper.find(end_token, content_start)
        next_start = starts[index + 1] if index + 1 < len(starts) else len(text)
        if explicit_end >= 0 and explicit_end < next_start:
            end = explicit_end
        else:
            parent_end_candidates = [
                position for marker in ("</BANKTRANLIST>", "</CCSTMTRS>", "</INVTRANLIST>", "</INVPOSLIST>", "</SECLIST>")
                if (position := upper.find(marker, content_start)) >= 0
            ]
            end = min([next_start, *parent_end_candidates]) if parent_end_candidates else next_start
        blocks.append(text[content_start:end])
    return blocks


def _value(text: str, tag: str) -> str | None:
    match = re.search(rf"<{re.escape(tag)}>\s*([^<\r\n]+)", text, flags=re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _ofx_date(value: str | None) -> date | None:
    digits = "".join(character for character in (value or "") if character.isdigit())
    if len(digits) < 8:
        return None
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None


def _decimal_text(value: str | None) -> str | None:
    cleaned = (value or "").strip().replace(",", "")
    if not cleaned:
        return None
    try:
        parsed = Decimal(cleaned)
    except InvalidOperation:
        return None
    return format(parsed, "f")


def _multiply_decimal_text(left: str, right: str) -> str:
    return format(Decimal(left) * Decimal(right), "f")


def _account_metadata(text: str) -> dict[str, str | None]:
    account_id = _value(text, "ACCTID")
    account_type = _value(text, "ACCTTYPE")
    if "<CCACCTFROM>" in text.upper():
        normalized_type = "credit_card"
    elif "<INVACCTFROM>" in text.upper():
        normalized_type = "brokerage"
    else:
        normalized_type = {
            "CHECKING": "checking",
            "SAVINGS": "savings",
            "MONEYMRKT": "savings",
            "CREDITLINE": "credit_card",
        }.get((account_type or "").upper(), "checking")
    institution = _value(text, "ORG") or _value(text, "FIORG") or _value(text, "BANKID") or _value(text, "BROKERID")
    return {
        "account_id": account_id,
        "last_four": account_id[-4:] if account_id and len(account_id) >= 4 else account_id,
        "account_type": normalized_type,
        "institution": institution,
        "currency": _value(text, "CURDEF") or "USD",
        "account_name": " ".join(filter(None, (institution, normalized_type.replace("_", " ").title()))),
    }


def _security_registry(text: str) -> dict[str, dict[str, str | None]]:
    registry: dict[str, dict[str, str | None]] = {}
    for tag in SECURITY_INFO_TAGS:
        for block in _blocks(text, tag):
            unique_id = _value(block, "UNIQUEID")
            if not unique_id:
                continue
            registry[unique_id] = {
                "symbol": _value(block, "TICKER") or _value(block, "FIID"),
                "description": _value(block, "SECNAME"),
            }
    return registry
