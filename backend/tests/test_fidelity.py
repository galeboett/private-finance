import json
from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, AuditEvent, HoldingSnapshot, ImportBatch, Institution, NetWorthSnapshot, StagingRow
from app.services.fidelity import FIDELITY_HISTORY_REPAIR_EVENT, repair_fidelity_holding_history


def test_historical_fidelity_repair_moves_brokeragelink_adds_cash_and_updates_totals():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        institution = Institution(name="Fidelity")
        hsa = Account(institution=institution, display_name="HSA", account_type="brokerage", last_four="5265")
        retirement = Account(institution=institution, display_name="401K", account_type="brokerage", last_four="4061")
        individual = Account(institution=institution, display_name="Individual Brokerage", account_type="brokerage", last_four="1047")
        duplicate = Account(institution=institution, display_name="Brokeragelink", account_type="brokerage", last_four="5265")
        db.add_all([hsa, retirement, individual, duplicate])
        db.flush()
        batch = ImportBatch(account_id=individual.id, filename="Portfolio_Positions_Jul-07-2026.csv", file_hash="history", status="committed", imported_rows=5, skipped_duplicates=0, warnings_json="[]")
        db.add(batch)
        db.flush()
        rows = [
            {"row_index": 2, "account_number": "Z09581047", "account_name": "Individual", "symbol": "FCASH**", "description": "HELD IN FCASH", "quantity": "", "price": "", "market_value": "$10.00", "asset_class": "Cash"},
            {"row_index": 3, "account_number": "Z09581047", "account_name": "Individual", "symbol": "AMZN", "description": "AMAZON.COM INC", "quantity": "2", "price": "$30.00", "market_value": "$60.00", "asset_class": "Cash"},
            {"row_index": 5, "account_number": "34061", "account_name": "AMAZON 401(K) PLAN", "symbol": "", "description": "BROKERAGELINK", "quantity": "240", "price": "$1.00", "market_value": "$240.00", "asset_class": ""},
            {"row_index": 6, "account_number": "34061", "account_name": "AMAZON 401(K) PLAN", "symbol": "FUND", "description": "INDEX FUND", "quantity": "1", "price": "$100.00", "market_value": "$100.00", "asset_class": ""},
            {"row_index": 7, "account_number": "653405265", "account_name": "BrokerageLink", "symbol": "FDRXX**", "description": "HELD IN MONEY MARKET", "quantity": "", "price": "", "market_value": "$40.00", "asset_class": "Cash"},
            {"row_index": 8, "account_number": "653405265", "account_name": "BrokerageLink", "symbol": "BRKB", "description": "BERKSHIRE HATHAWAY", "quantity": "2", "price": "$100.00", "market_value": "$200.00", "asset_class": "Cash"},
            {"row_index": 10, "account_number": "242084500", "account_name": "Health Savings Account", "symbol": "FDRXX**", "description": "HELD IN MONEY MARKET", "quantity": "", "price": "", "market_value": "$30.00", "asset_class": "Cash"},
            {"row_index": 11, "account_number": "242084500", "account_name": "Health Savings Account", "symbol": "BRKB", "description": "BERKSHIRE HATHAWAY", "quantity": "1", "price": "$50.00", "market_value": "$50.00", "asset_class": "Cash"},
        ]
        for row in rows:
            db.add(StagingRow(import_batch_id=batch.id, account_id=individual.id, row_index=row["row_index"], row_kind="ignore" if "HELD IN" in row["description"] else "position", raw_json=json.dumps(row), normalized_json=json.dumps(row)))
        snapshot_date = date(2026, 7, 8)
        db.add_all([
            HoldingSnapshot(account_id=individual.id, snapshot_date=snapshot_date, symbol="AMZN", description="AMAZON.COM INC", quantity_basis_points=20000, price_cents=3000, market_value_cents=6000, asset_class="Cash"),
            HoldingSnapshot(account_id=retirement.id, snapshot_date=snapshot_date, symbol="FUND", description="INDEX FUND", quantity_basis_points=10000, price_cents=10000, market_value_cents=10000),
            HoldingSnapshot(account_id=hsa.id, snapshot_date=snapshot_date, symbol="BRKB", description="BERKSHIRE HATHAWAY", quantity_basis_points=20000, price_cents=10000, market_value_cents=20000, asset_class="Cash"),
            HoldingSnapshot(account_id=hsa.id, snapshot_date=snapshot_date, symbol="BRKB", description="BERKSHIRE HATHAWAY", quantity_basis_points=10000, price_cents=5000, market_value_cents=5000, asset_class="Cash"),
            NetWorthSnapshot(account_id=individual.id, snapshot_date=snapshot_date, balance_cents=6000, source="import"),
            NetWorthSnapshot(account_id=retirement.id, snapshot_date=snapshot_date, balance_cents=10000, source="import"),
            NetWorthSnapshot(account_id=hsa.id, snapshot_date=snapshot_date, balance_cents=25000, source="import"),
        ])
        db.commit()

        result = repair_fidelity_holding_history(db)
        db.commit()

        assert result["repaired"] is True
        assert result["operation_id"]
        assert db.get(Account, duplicate.id) is None
        assert hsa.last_four == "4500"
        assert retirement.account_type == "retirement"
        holdings = db.scalars(select(HoldingSnapshot).order_by(HoldingSnapshot.account_id, HoldingSnapshot.id)).all()
        assert [(row.symbol, row.market_value_cents) for row in holdings if row.account_id == individual.id] == [("AMZN", 6000), ("FCASH**", 1000)]
        assert [(row.symbol, row.market_value_cents) for row in holdings if row.account_id == retirement.id] == [("FUND", 10000), ("BRKB", 20000), ("FDRXX**", 4000)]
        assert [(row.symbol, row.market_value_cents) for row in holdings if row.account_id == hsa.id] == [("BRKB", 5000), ("FDRXX**", 3000)]
        totals = {row.account_id: row.balance_cents for row in db.scalars(select(NetWorthSnapshot)).all()}
        assert totals == {individual.id: 7000, retirement.id: 34000, hsa.id: 8000}
        assert db.scalar(select(AuditEvent.id).where(AuditEvent.event_type == FIDELITY_HISTORY_REPAIR_EVENT))
        assert repair_fidelity_holding_history(db) == {"repaired": False, "operation_id": None}
