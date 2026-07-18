import json
from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, AuditEvent, DuplicatePairDecision, RefundLink, Transaction, TransferLink
from app.services.duplicate_scan import migrate_keep_both_decisions, scan_ledger_duplicates
from app.services.duplicates import pending_duplicate_pairs, resolve_duplicate


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _transaction(account_id: int, amount_cents: int, description: str, source_hash: str, *, reference: str | None = None, transaction_type: str = "expense") -> Transaction:
    return Transaction(account_id=account_id, transaction_date=date(2026, 5, 21), amount_cents=amount_cents, raw_description=description, transaction_type=transaction_type, review_status="needs_review", source_hash=source_hash, source_reference=reference)


def test_scan_finds_each_confidence_tier_and_flags_existing_review_queue():
    with _session() as db:
        accounts = [Account(display_name=f"Card {index}", account_type="credit_card") for index in range(4)]
        db.add_all(accounts)
        db.flush()
        rows = [
            _transaction(accounts[0].id, -665, "AMAZON MARKETPLACE", "exact-a"),
            _transaction(accounts[0].id, -665, "AMAZON MARKETPLACE", "exact-b"),
            _transaction(accounts[1].id, -593, "AMAZON ORDER", "cross-a", reference="categorized-history-row-9"),
            _transaction(accounts[1].id, -593, "AMAZON ORDER", "cross-b", reference="BANK-88421"),
            _transaction(accounts[2].id, -641, "AMAZON MARKETPLACE ORDER 1234", "probable-a"),
            _transaction(accounts[2].id, -641, "AMAZON MARKETPLACE ORDER 1235", "probable-b"),
            _transaction(accounts[3].id, -2900, "LATE FEE FOR PAYMENT DUE", "mirror-negative"),
            _transaction(accounts[3].id, 2900, "LATE FEE FOR PAYMENT DUE", "mirror-positive", transaction_type="refund"),
        ]
        db.add_all(rows)
        db.commit()

        result = scan_ledger_duplicates(db, actor="user:7")
        db.commit()

        assert result["counts"] == {"cross_source": 1, "mirrored": 1, "exact": 1, "probable": 1}
        pending = pending_duplicate_pairs(db)
        assert {pair["tier"] for pair in pending} == {"cross_source", "mirrored", "exact", "probable"}
        assert next(pair for pair in pending if pair["tier"] == "cross_source")["original"]["reference"].startswith("categorized-history-row-")
        assert sum(row.review_status == "possible_duplicate" for row in rows) == 4


def test_scan_can_refresh_one_account_without_scanning_other_accounts():
    with _session() as db:
        first = Account(display_name="First card", account_type="credit_card")
        second = Account(display_name="Second card", account_type="credit_card")
        db.add_all([first, second])
        db.flush()
        first_rows = [
            _transaction(first.id, -2037, "PAYPAL *WALMART.COM 800-925-6278 CA", "first-a"),
            _transaction(first.id, -2037, "PAYPAL *WALMART.COM 800-925-6278 CA", "first-b"),
        ]
        second_rows = [
            _transaction(second.id, -900, "AMAZON ONEMED 855-684-4722 WA", "second-a"),
            _transaction(second.id, -900, "AMAZON ONEMED 855-684-4722 WA", "second-b"),
        ]
        db.add_all([*first_rows, *second_rows])
        db.commit()

        result = scan_ledger_duplicates(db, actor="user:7", account_id=first.id)
        db.commit()

        assert result["flagged"] == 1
        assert len(pending_duplicate_pairs(db, account_id=first.id)) == 1
        assert pending_duplicate_pairs(db, account_id=second.id) == []
        assert all(row.review_status == "needs_review" for row in second_rows)


def test_keep_both_decision_survives_future_scans():
    with _session() as db:
        card = Account(display_name="Card", account_type="credit_card")
        db.add(card)
        db.flush()
        db.add_all([_transaction(card.id, -665, "AMAZON MARKETPLACE", "keep-a"), _transaction(card.id, -665, "AMAZON MARKETPLACE", "keep-b")])
        db.commit()
        scan_ledger_duplicates(db, actor="user:7")
        pair = pending_duplicate_pairs(db)[0]
        resolve_duplicate(db, transaction_id=pair["candidate"]["id"], action="keep_both", actor="user:7")
        db.commit()

        second_scan = scan_ledger_duplicates(db, actor="user:7")
        db.commit()

        assert second_scan["flagged"] == 0
        assert pending_duplicate_pairs(db) == []
        assert db.scalar(select(DuplicatePairDecision)).decision == "keep_both"


def test_keep_both_decisions_suppress_transitive_pairs_in_a_duplicate_group():
    with _session() as db:
        card = Account(display_name="Card", account_type="credit_card")
        db.add(card)
        db.flush()
        db.add_all([
            _transaction(card.id, -1000, "REPEATED PURCHASE", "group-a"),
            _transaction(card.id, -1000, "REPEATED PURCHASE", "group-b"),
            _transaction(card.id, -1000, "REPEATED PURCHASE", "group-c"),
        ])
        db.commit()

        scan_ledger_duplicates(db, actor="user:7")
        first_pair = pending_duplicate_pairs(db)[0]
        resolve_duplicate(db, transaction_id=first_pair["candidate"]["id"], action="keep_both", actor="user:7")
        db.commit()

        scan_ledger_duplicates(db, actor="user:7")
        second_pair = pending_duplicate_pairs(db)[0]
        resolve_duplicate(db, transaction_id=second_pair["candidate"]["id"], action="keep_both", actor="user:7")
        db.commit()

        third_scan = scan_ledger_duplicates(db, actor="user:7")
        db.commit()

        assert third_scan["flagged"] == 0
        assert pending_duplicate_pairs(db) == []


def test_scan_clears_queued_pair_covered_by_transitive_keep_both_decisions():
    with _session() as db:
        card = Account(display_name="Card", account_type="credit_card")
        db.add(card)
        db.flush()
        first = _transaction(card.id, -1000, "REPEATED PURCHASE", "queued-a")
        second = _transaction(card.id, -1000, "REPEATED PURCHASE", "queued-b")
        third = _transaction(card.id, -1000, "REPEATED PURCHASE", "queued-c")
        db.add_all([first, second, third])
        db.flush()
        db.add_all([
            DuplicatePairDecision(transaction_a_id=first.id, transaction_b_id=second.id, decision="keep_both"),
            DuplicatePairDecision(transaction_a_id=second.id, transaction_b_id=third.id, decision="keep_both"),
        ])
        third.review_status = "possible_duplicate"
        third.duplicate_of_transaction_id = first.id
        db.commit()

        result = scan_ledger_duplicates(db, actor="user:7")
        db.commit()

        assert result["cleared_reviewed"] == 1
        assert third.review_status == "needs_review"
        assert third.duplicate_of_transaction_id is None
        assert pending_duplicate_pairs(db) == []


def test_migrates_prior_keep_both_audit_events_into_pair_decisions():
    with _session() as db:
        card = Account(display_name="Card", account_type="credit_card")
        db.add(card)
        db.flush()
        first = _transaction(card.id, -665, "AMAZON", "audit-a")
        second = _transaction(card.id, -665, "AMAZON", "audit-b")
        db.add_all([first, second])
        db.flush()
        db.add(AuditEvent(event_type="duplicate_resolve", actor="user:7", entity_type="transaction", entity_id=str(second.id), details_json=json.dumps({"action": "keep_both", "original_transaction_id": first.id})))
        db.commit()

        assert migrate_keep_both_decisions(db) == 1
        db.commit()
        decision = db.scalar(select(DuplicatePairDecision))
        assert (decision.transaction_a_id, decision.transaction_b_id) == (first.id, second.id)


def test_scan_excludes_transactions_in_confirmed_transfer_or_refund_links():
    with _session() as db:
        card = Account(display_name="Card", account_type="credit_card")
        checking = Account(display_name="Checking", account_type="checking")
        db.add_all([card, checking])
        db.flush()
        transfer_duplicates = [_transaction(card.id, 10000, "PAYMENT RECEIVED", f"transfer-{index}") for index in range(2)]
        bank = _transaction(checking.id, -10000, "CARD PAYMENT", "bank")
        refund_duplicates = [_transaction(card.id, 2500, "STORE REFUND", f"refund-{index}", transaction_type="refund") for index in range(2)]
        expense = _transaction(card.id, -5000, "STORE", "expense")
        db.add_all([*transfer_duplicates, bank, *refund_duplicates, expense])
        db.flush()
        db.add_all([
            TransferLink(from_transaction_id=bank.id, to_transaction_id=transfer_duplicates[0].id, match_confidence=100, confirmed=True),
            RefundLink(expense_transaction_id=expense.id, refund_transaction_id=refund_duplicates[0].id, match_confidence=100, confirmed=True),
        ])
        db.commit()

        result = scan_ledger_duplicates(db, actor="user:7")

        assert result["flagged"] == 0


def test_mirrored_resolution_removes_positive_sign_artifact():
    with _session() as db:
        card = Account(display_name="Card", account_type="credit_card")
        db.add(card)
        db.flush()
        negative = _transaction(card.id, -2900, "LATE FEE FOR PAYMENT DUE", "sign-negative")
        positive = _transaction(card.id, 2900, "LATE FEE FOR PAYMENT DUE", "sign-positive", transaction_type="refund")
        db.add_all([negative, positive])
        db.commit()
        scan_ledger_duplicates(db, actor="user:7")
        pair = pending_duplicate_pairs(db)[0]

        result = resolve_duplicate(db, transaction_id=pair["candidate"]["id"], action="remove_sign_artifact", actor="user:7")
        db.commit()

        assert result["affected_card_account"] is True
        assert positive.deleted_at is not None
        assert negative.deleted_at is None
