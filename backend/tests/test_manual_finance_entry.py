import json
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.db import Base
from app.main import create_holding_lot, create_manual_transaction, delete_holding_lot, export_app_data, get_investment_holdings, update_holding_lot
from app.models import Account, Category, HoldingLot, HoldingSnapshot, SessionToken, Transaction
from app.schemas import HoldingLotCreate, HoldingLotUpdate, ManualTransactionCreate
from app.services.operation_history import undo_operation


def _request() -> Request:
    return Request({"type": "http", "headers": [(b"x-csrf-token", b"csrf")]})


def _session_token() -> SessionToken:
    return SessionToken(user_id=7, csrf_token="csrf")


def test_manual_money_out_is_canonical_confirmed_and_undoable():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = Account(display_name="Checking", account_type="checking")
        category = Category(key="groceries", label="Groceries")
        db.add_all([account, category])
        db.commit()

        result = create_manual_transaction(
            ManualTransactionCreate(account_id=account.id, transaction_date=date(2026, 7, 14), amount_cents=-4250, category_id=category.id, description="  Farmers   market  ", labels=["Food", "food", "Weekend"]),
            _request(),
            _session_token(),
            db,
        )

        transaction = db.get(Transaction, result["transaction_id"])
        assert transaction.amount_cents == -4250
        assert transaction.raw_description == "Farmers market"
        assert transaction.transaction_type == "expense"
        assert transaction.review_status == "confirmed"
        assert transaction.category_id == category.id
        assert transaction.labels == "|food|weekend|"
        assert transaction.source_hash.startswith("manual:")

        undo_operation(db, operation_id=result["operation_id"], actor="user:7")
        db.commit()
        assert transaction.deleted_at is not None
        with pytest.raises(HTTPException, match="Amount must be greater than zero"):
            create_manual_transaction(ManualTransactionCreate(account_id=account.id, transaction_date=date(2026, 7, 14), amount_cents=0, category_id=category.id, description="Invalid"), _request(), _session_token(), db)


def test_holding_lot_adds_basis_gain_and_age_and_can_be_undone():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = Account(display_name="Brokerage", account_type="brokerage")
        db.add(account)
        db.flush()
        db.add(HoldingSnapshot(account_id=account.id, snapshot_date=date(2026, 7, 14), symbol="VTI", quantity_basis_points=100000, price_cents=10000, market_value_cents=100000, cost_basis_cents=85000))
        db.commit()

        aggregate_payload = get_investment_holdings(_session_token(), db)[0]
        assert aggregate_payload["lot_count"] == 0
        assert aggregate_payload["cost_basis_cents"] == 85000
        assert aggregate_payload["unrealized_gain_loss_cents"] == 15000

        result = create_holding_lot(
            HoldingLotCreate(account_id=account.id, symbol="vti", acquisition_date=date(2024, 1, 15), quantity_basis_points=100000, cost_basis_cents=80000, note="Opening basis"),
            _request(),
            _session_token(),
            db,
        )

        payload = get_investment_holdings(_session_token(), db)[0]
        assert payload["lot_count"] == 1
        assert payload["lot_quantity"] == 10
        assert payload["cost_basis_cents"] == 80000
        assert payload["unrealized_gain_loss_cents"] == 20000
        assert payload["oldest_acquisition_date"] == "2024-01-15"
        assert payload["lot_age_days"] == (date.today() - date(2024, 1, 15)).days
        exported = json.loads(export_app_data(_session_token(), db).body)
        assert exported["tables"]["holding_lots"][0]["symbol"] == "VTI"

        undo_operation(db, operation_id=result["operation_id"], actor="user:7")
        db.commit()
        assert db.get(HoldingLot, result["lot_id"]) is None
        with pytest.raises(HTTPException, match="Symbol is required"):
            create_holding_lot(HoldingLotCreate(account_id=account.id, symbol=" ", acquisition_date=date(2024, 1, 15), quantity_basis_points=10000, cost_basis_cents=10000), _request(), _session_token(), db)


def test_holding_lot_edit_and_delete_are_journaled_and_undoable():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = Account(display_name="Brokerage", account_type="brokerage")
        db.add(account)
        db.flush()
        lot = HoldingLot(account_id=account.id, symbol="VTI", acquisition_date=date(2024, 1, 15), quantity_basis_points=100000, cost_basis_cents=80000, note="Opening basis")
        db.add(lot)
        db.commit()

        updated = update_holding_lot(lot.id, HoldingLotUpdate(acquisition_date=date(2024, 2, 1), quantity_basis_points=125000, cost_basis_cents=90000, note="Corrected"), _request(), _session_token(), db)
        assert (lot.acquisition_date, lot.quantity_basis_points, lot.cost_basis_cents, lot.note) == (date(2024, 2, 1), 125000, 90000, "Corrected")

        undo_operation(db, operation_id=updated["operation_id"], actor="user:7")
        db.commit()
        assert (lot.acquisition_date, lot.quantity_basis_points, lot.cost_basis_cents, lot.note) == (date(2024, 1, 15), 100000, 80000, "Opening basis")

        deleted = delete_holding_lot(lot.id, _request(), _session_token(), db)
        assert db.get(HoldingLot, lot.id) is None
        undo_operation(db, operation_id=deleted["operation_id"], actor="user:7")
        db.commit()
        assert db.get(HoldingLot, lot.id) is not None
