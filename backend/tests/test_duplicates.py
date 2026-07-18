from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, Category, DuplicatePairDecision, ImportBatch, Institution, Operation, RefundLink, Transaction, TransactionSplit
from app.services.duplicates import duplicate_queue_summary, link_historical_refund_pairs, pending_duplicate_pairs, preview_duplicate_selection, preview_historical_refund_links, preview_safe_duplicate_resolution, resolve_all_exact_duplicates, resolve_duplicate, resolve_duplicate_selection, resolve_safe_duplicate_reimports
from app.services.operation_history import undo_operation


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _pair(db: Session, *, exact: bool = False, suffix: str = "") -> tuple[Transaction, Transaction, Category]:
    institution = Institution(name=f"Example Bank{suffix}")
    account = Account(institution=institution, display_name=f"Rewards Card{suffix}", account_type="credit_card", last_four="1234")
    category = Category(key=f"groceries{suffix}", label="Groceries")
    db.add_all([account, category])
    db.flush()
    batch = ImportBatch(account_id=account.id, filename="statement.csv", file_hash=f"batch{suffix}", status="committed")
    db.add(batch)
    db.flush()
    original = Transaction(
        account_id=account.id,
        import_batch_id=batch.id,
        transaction_date=date(2026, 7, 1),
        posted_date=date(2026, 7, 2),
        amount_cents=-1200,
        raw_description="Market purchase",
        normalized_payee="Market purchase",
        user_note="Weekly groceries",
        labels="shared,food",
        transaction_type="expense",
        category_id=category.id,
        review_status="confirmed",
        source_hash=f"original{suffix}",
        source_reference="REF-1",
    )
    db.add(original)
    db.flush()
    candidate = Transaction(
        account_id=account.id,
        import_batch_id=batch.id,
        transaction_date=original.transaction_date if exact else date(2026, 7, 3),
        posted_date=original.posted_date if exact else date(2026, 7, 4),
        amount_cents=original.amount_cents if exact else -1250,
        raw_description=original.raw_description if exact else "MARKET PURCHASE UPDATED",
        normalized_payee=original.normalized_payee if exact else "MARKET PURCHASE UPDATED",
        user_note=original.user_note if exact else None,
        labels=original.labels if exact else None,
        transaction_type="expense",
        category_id=original.category_id if exact else None,
        review_status="possible_duplicate",
        source_hash=f"candidate{suffix}",
        source_reference=original.source_reference if exact else "REF-2",
        duplicate_of_transaction_id=original.id,
    )
    db.add(candidate)
    db.flush()
    return candidate, original, category


def test_pending_duplicates_return_side_by_side_context_and_diff_fields():
    with _session() as db:
        candidate, original, _ = _pair(db)
        pair = pending_duplicate_pairs(db)[0]
        assert pair["candidate"]["id"] == candidate.id
        assert pair["original"]["id"] == original.id
        assert pair["candidate"]["account"] == "Rewards Card"
        assert pair["candidate"]["institution"] == "Example Bank"
        assert pair["original"]["category"] == "Groceries"
        assert {"reference", "date", "amount", "description", "category", "notes", "labels"}.issubset(pair["diff_fields"])
        assert pair["exact_match"] is False


def test_pending_duplicates_can_be_scoped_to_one_account():
    with _session() as db:
        first_candidate, _, _ = _pair(db, suffix="-first")
        second_candidate, _, _ = _pair(db, suffix="-second")

        pairs = pending_duplicate_pairs(db, account_id=second_candidate.account_id)

        assert [pair["candidate"]["id"] for pair in pairs] == [second_candidate.id]
        assert first_candidate.id not in {pair["candidate"]["id"] for pair in pairs}


def test_remove_new_is_one_undoable_operation():
    with _session() as db:
        candidate, _, _ = _pair(db)
        result = resolve_duplicate(db, transaction_id=candidate.id, action="remove_new", actor="user:7")
        db.commit()
        assert candidate.deleted_at is not None
        assert db.get(Operation, result["operation_id"]).kind == "resolve_duplicate"

        undo_operation(db, operation_id=result["operation_id"], actor="user:7")
        db.commit()
        assert db.get(Transaction, candidate.id).deleted_at is None


def test_keep_both_clears_duplicate_relationship_but_leaves_category_review_open():
    with _session() as db:
        candidate, _, _ = _pair(db)
        result = resolve_duplicate(db, transaction_id=candidate.id, action="keep_both", actor="user:7")
        db.commit()
        assert candidate.duplicate_of_transaction_id is None
        assert candidate.review_status == "needs_review"
        assert candidate.deleted_at is None
        assert db.scalar(select(DuplicatePairDecision)) is not None

        undo_operation(db, operation_id=result["operation_id"], actor="user:7")
        db.commit()
        assert candidate.duplicate_of_transaction_id is not None
        assert candidate.review_status == "possible_duplicate"
        assert db.scalar(select(DuplicatePairDecision)) is None


def test_replace_old_copies_bank_fields_and_preserves_user_authored_fields_and_splits():
    with _session() as db:
        candidate, original, category = _pair(db)
        split = TransactionSplit(transaction_id=original.id, category_id=category.id, amount_cents=-1200, note="Keep me")
        db.add(split)
        db.commit()
        old_description = original.raw_description

        result = resolve_duplicate(db, transaction_id=candidate.id, action="replace_old", actor="user:7")
        db.commit()
        assert original.transaction_date == candidate.transaction_date
        assert original.amount_cents == candidate.amount_cents
        assert original.raw_description == candidate.raw_description
        assert original.source_reference == candidate.source_reference
        assert original.user_note == "Weekly groceries"
        assert original.labels == "shared,food"
        assert original.category_id == category.id
        assert db.get(TransactionSplit, split.id).note == "Keep me"
        assert candidate.deleted_at is not None

        undo_operation(db, operation_id=result["operation_id"], actor="user:7")
        db.commit()
        assert original.raw_description == old_description
        assert candidate.deleted_at is None


def test_resolve_all_exact_matches_uses_one_operation_and_one_undo():
    with _session() as db:
        first, _, _ = _pair(db, exact=True, suffix="-1")
        second, second_original, _ = _pair(db, exact=True, suffix="-2")
        assert pending_duplicate_pairs(db)[0]["exact_match"] is True
        result = resolve_all_exact_duplicates(db, actor="user:7")
        db.commit()
        assert result["resolved"] == 2
        assert first.deleted_at is not None and second.deleted_at is not None
        assert db.get(Operation, result["operation_id"]).kind == "resolve_duplicates"

        undo_operation(db, operation_id=result["operation_id"], actor="user:7")
        db.commit()
        assert first.deleted_at is None and second.deleted_at is None
        assert second_original.deleted_at is None


def test_bulk_resolution_only_removes_safe_reimports_and_queue_can_page_by_tier():
    with _session() as db:
        safe, _, _ = _pair(db, exact=True, suffix="-safe")
        needs_review, _, _ = _pair(db, exact=True, suffix="-review")
        needs_review.source_reference = "DIFFERENT-REFERENCE"
        db.commit()

        pairs = pending_duplicate_pairs(db)
        assert [pair["safe_reimport"] for pair in pairs] == [False, True]
        assert len(pending_duplicate_pairs(db, limit=1, offset=1, tier_filter="exact")) == 1
        assert duplicate_queue_summary(db) == {"total": 2, "counts": {"cross_source": 0, "exact": 2, "probable": 0, "mirrored": 0, "import": 0}, "safe_reimports": 1, "historical_refunds": 0}

        result = resolve_all_exact_duplicates(db, actor="user:7")
        db.commit()

        assert result["resolved"] == 1
        assert safe.deleted_at is not None
        assert needs_review.deleted_at is None


def test_bulk_preview_discloses_scope_sources_accounts_and_balance_adjustment():
    with _session() as db:
        candidate, original, _ = _pair(db, exact=True, suffix="-preview")
        old_batch = db.get(ImportBatch, original.import_batch_id)
        old_batch.filename = "transaction history.xlsx"
        new_batch = ImportBatch(account_id=original.account_id, filename="bank.csv", file_hash="new-preview", status="committed")
        db.add(new_batch)
        db.flush()
        candidate.import_batch_id = new_batch.id
        db.commit()

        keep_existing = preview_safe_duplicate_resolution(db, strategy="keep_existing")
        use_new = preview_safe_duplicate_resolution(db, strategy="use_new_import")

        assert keep_existing["pair_count"] == 1
        assert keep_existing["account_count"] == 1
        assert keep_existing["balance_change_cents"] == 1200
        assert keep_existing["accounts"][0]["pairs"] == 1
        assert keep_existing["selected_sources"] == [{"source": "transaction history.xlsx", "count": 1}]
        assert use_new["selected_sources"] == [{"source": "bank.csv", "count": 1}]
        assert use_new["annotations_preserved"]["categorized"] == 1
        assert keep_existing["selection_token"] != use_new["selection_token"]


def test_bulk_use_new_import_updates_source_facts_preserves_annotations_and_is_undoable():
    with _session() as db:
        candidate, original, category = _pair(db, exact=True, suffix="-new")
        old_batch_id = original.import_batch_id
        old_posted_date = original.posted_date
        new_batch = ImportBatch(account_id=original.account_id, filename="new-bank.csv", file_hash="new-bank", status="committed")
        db.add(new_batch)
        db.flush()
        candidate.import_batch_id = new_batch.id
        candidate.posted_date = date(2026, 7, 5)
        candidate.running_balance_cents = 432100
        db.commit()

        preview = preview_safe_duplicate_resolution(db, strategy="use_new_import")
        result = resolve_safe_duplicate_reimports(db, strategy="use_new_import", preview_token=preview["selection_token"], actor="user:7")
        db.commit()

        assert result["resolved"] == 1
        assert result["updated"] == 1
        assert original.import_batch_id == new_batch.id
        assert original.posted_date == date(2026, 7, 5)
        assert original.running_balance_cents == 432100
        assert original.category_id == category.id
        assert original.user_note == "Weekly groceries"
        assert original.labels == "shared,food"
        assert candidate.deleted_at is not None

        undo_operation(db, operation_id=result["operation_id"], actor="user:7")
        db.commit()
        assert original.import_batch_id == old_batch_id
        assert original.posted_date == old_posted_date
        assert candidate.deleted_at is None


def test_bulk_resolution_rejects_a_stale_confirmation_preview():
    with _session() as db:
        candidate, _, _ = _pair(db, exact=True, suffix="-stale")
        preview = preview_safe_duplicate_resolution(db, strategy="keep_existing")
        candidate.review_status = "needs_review"
        candidate.duplicate_of_transaction_id = None
        db.commit()

        try:
            resolve_safe_duplicate_reimports(db, strategy="keep_existing", preview_token=preview["selection_token"], actor="user:7")
        except ValueError as error:
            assert "queue changed" in str(error)
        else:
            raise AssertionError("A stale preview should not be applied")


def test_bulk_historical_refund_linking_is_previewed_and_undoable():
    with _session() as db:
        institution = Institution(name="Card Issuer")
        account = Account(institution=institution, display_name="Rewards Card", account_type="credit_card")
        category = Category(key="shopping-refund", label="Shopping")
        db.add_all([account, category])
        db.flush()
        batch = ImportBatch(account_id=account.id, filename="transaction history.csv", file_hash="history-refunds", status="committed")
        db.add(batch)
        db.flush()
        expense = Transaction(
            account_id=account.id,
            import_batch_id=batch.id,
            transaction_date=date(2025, 10, 18),
            amount_cents=-7001,
            raw_description="TARGET FULLERTON CA",
            transaction_type="expense",
            category_id=category.id,
            review_status="confirmed",
            source_hash="history-expense",
            source_reference="categorized-history-row-10259",
        )
        db.add(expense)
        db.flush()
        refund = Transaction(
            account_id=account.id,
            import_batch_id=batch.id,
            transaction_date=expense.transaction_date,
            amount_cents=7001,
            raw_description=expense.raw_description,
            transaction_type="refund",
            category_id=category.id,
            review_status="possible_duplicate",
            source_hash="history-refund",
            source_reference="categorized-history-row-10258",
            duplicate_of_transaction_id=expense.id,
        )
        db.add(refund)
        db.commit()

        preview = preview_historical_refund_links(db)
        assert preview["pair_count"] == 1
        assert preview["refund_total_cents"] == 7001
        assert preview["net_change_cents"] == 0

        result = link_historical_refund_pairs(db, preview_token=preview["selection_token"], actor="user:7")
        db.commit()
        assert result["linked"] == 1
        assert db.scalar(select(RefundLink)).confirmed is True
        assert refund.review_status == "confirmed"
        assert refund.duplicate_of_transaction_id is None

        undo_operation(db, operation_id=result["operation_id"], actor="user:7")
        db.commit()
        assert db.scalar(select(RefundLink)) is None
        assert refund.review_status == "possible_duplicate"
        assert refund.duplicate_of_transaction_id == expense.id


def test_historical_refund_bulk_scope_rejects_mismatched_categories():
    with _session() as db:
        candidate, original, _ = _pair(db, suffix="-not-refund")
        candidate.transaction_date = original.transaction_date
        candidate.amount_cents = -original.amount_cents
        candidate.raw_description = original.raw_description
        candidate.transaction_type = "refund"
        candidate.source_reference = "categorized-history-row-2"
        original.source_reference = "categorized-history-row-1"
        candidate.category_id = None
        db.commit()

        assert preview_historical_refund_links(db)["pair_count"] == 0


def test_selected_exact_and_probable_pairs_can_be_kept_in_one_undoable_operation():
    with _session() as db:
        exact, _, _ = _pair(db, exact=True, suffix="-selected-exact")
        probable, probable_original, _ = _pair(db, suffix="-selected-probable")
        probable.transaction_date = probable_original.transaction_date
        probable.amount_cents = probable_original.amount_cents
        probable.raw_description = "MARKET PURCHASES"
        probable.normalized_payee = probable.raw_description
        db.commit()

        preview = preview_duplicate_selection(db, transaction_ids=[exact.id, probable.id], action="keep_both")
        assert preview["tiers"] == {"exact": 1, "probable": 1}
        result = resolve_duplicate_selection(db, transaction_ids=[exact.id, probable.id], action="keep_both", preview_token=preview["selection_token"], actor="user:7")
        db.commit()

        assert result["resolved"] == 2
        assert exact.duplicate_of_transaction_id is None
        assert probable.duplicate_of_transaction_id is None
        assert db.query(DuplicatePairDecision).count() == 2

        undo_operation(db, operation_id=result["operation_id"], actor="user:7")
        db.commit()
        assert exact.duplicate_of_transaction_id is not None
        assert probable.duplicate_of_transaction_id is not None
        assert db.query(DuplicatePairDecision).count() == 0


def test_selected_bulk_removal_accepts_exact_and_probable_pairs():
    with _session() as db:
        exact, _, _ = _pair(db, exact=True, suffix="-remove-exact")
        probable, probable_original, _ = _pair(db, suffix="-remove-probable")
        probable.transaction_date = probable_original.transaction_date
        probable.amount_cents = probable_original.amount_cents
        probable.raw_description = "MARKET PURCHASES"
        db.commit()

        preview = preview_duplicate_selection(db, transaction_ids=[exact.id, probable.id], action="remove_new")
        assert preview["tiers"] == {"exact": 1, "probable": 1}
        result = resolve_duplicate_selection(db, transaction_ids=[exact.id, probable.id], action="remove_new", preview_token=preview["selection_token"], actor="user:7")
        db.commit()
        assert result["resolved"] == 2
        assert exact.deleted_at is not None
        assert probable.deleted_at is not None


def test_selected_bulk_removal_accepts_safe_cross_source_pairs():
    with _session() as db:
        candidate, original, _ = _pair(db, exact=True, suffix="-remove-cross-source")
        original.source_reference = "categorized-history-row-10863"
        candidate.source_reference = "BANK-2403638602307111598855"
        db.commit()

        preview = preview_duplicate_selection(db, transaction_ids=[candidate.id], action="remove_new")
        assert preview["tiers"] == {"cross_source": 1}

        result = resolve_duplicate_selection(db, transaction_ids=[candidate.id], action="remove_new", preview_token=preview["selection_token"], actor="user:7")
        db.commit()

        assert result["resolved"] == 1
        assert candidate.deleted_at is not None
        assert original.deleted_at is None


def test_selected_probable_pair_can_prefer_authoritative_history_and_undo():
    with _session() as db:
        candidate, original, original_category = _pair(db, suffix="-authoritative")
        authoritative_category = Category(key="restaurants-authoritative", label="Restaurants")
        authoritative_batch = ImportBatch(
            account_id=original.account_id,
            filename="transaction history for private finance 7.14.26v2.csv",
            file_hash="authoritative-history",
            status="committed",
        )
        db.add_all([authoritative_category, authoritative_batch])
        db.flush()
        # A prior lineage purge can leave an old ID whose batch no longer
        # exists. Duplicate Review intentionally displays this as Manual entry.
        original.import_batch_id = 999
        candidate.import_batch_id = authoritative_batch.id
        candidate.transaction_date = original.transaction_date
        candidate.amount_cents = original.amount_cents
        candidate.raw_description = "MARKET PURCHASES"
        candidate.normalized_payee = candidate.raw_description
        candidate.category_id = authoritative_category.id
        candidate.source_reference = "categorized-history-row-11363"
        split = TransactionSplit(transaction_id=original.id, category_id=original_category.id, amount_cents=original.amount_cents, note="Preserve this split")
        db.add(split)
        db.commit()

        original_id = original.id
        old_description = original.raw_description
        preview = preview_duplicate_selection(db, transaction_ids=[candidate.id], action="prefer_authoritative_history")
        assert preview["tiers"] == {"probable": 1}
        assert preview["authoritative_source"] == "transaction history for private finance 7.14.26v2.csv"
        assert preview["category_changes"] == 1
        assert preview["annotations_preserved"] == {"notes": 1, "labels": 1, "splits": 1, "allocations": 0}
        assert preview["balance_change_cents"] == 1200

        result = resolve_duplicate_selection(
            db,
            transaction_ids=[candidate.id],
            action="prefer_authoritative_history",
            preview_token=preview["selection_token"],
            actor="user:7",
        )
        db.commit()

        assert original.id == original_id
        assert original.import_batch_id == authoritative_batch.id
        assert original.raw_description == candidate.raw_description
        assert original.source_reference == "categorized-history-row-11363"
        assert original.category_id == authoritative_category.id
        assert original.review_status == "confirmed"
        assert original.user_note == "Weekly groceries"
        assert original.labels == "shared,food"
        assert db.get(TransactionSplit, split.id).note == "Preserve this split"
        assert candidate.deleted_at is not None

        undo_operation(db, operation_id=result["operation_id"], actor="user:7")
        db.commit()
        assert original.import_batch_id == 999
        assert original.raw_description == old_description
        assert original.category_id == original_category.id
        assert candidate.deleted_at is None


def test_prefer_authoritative_history_rejects_mixed_or_wrong_sources():
    with _session() as db:
        candidate, original, _ = _pair(db, exact=True, suffix="-wrong-authority")
        candidate_batch = db.get(ImportBatch, candidate.import_batch_id)
        candidate_batch.filename = "transaction history for private finance 7.14.26v2.csv"
        db.commit()

        try:
            preview_duplicate_selection(db, transaction_ids=[candidate.id], action="prefer_authoritative_history")
        except ValueError as error:
            assert "Manual entry" in str(error)
        else:
            raise AssertionError("An imported established row must not be replaced by the Manual-entry-specific action")

        original.import_batch_id = None
        candidate_batch.filename = "some other history.csv"
        db.commit()
        try:
            preview_duplicate_selection(db, transaction_ids=[candidate.id], action="prefer_authoritative_history")
        except ValueError as error:
            assert "7.14.26v2.csv" in str(error)
        else:
            raise AssertionError("Only the explicitly authoritative history filename should be accepted")
