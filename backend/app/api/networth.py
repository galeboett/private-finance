from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..db import get_db
from ..models import Account, HoldingLot, HoldingSnapshot, Institution, NetWorthSnapshot, SecurityMetadata, SecurityPrice, SessionToken, StatementCheckpoint
from ..schemas import BulkDeleteRequest, DeleteConfirmRequest, HoldingLotCreate, HoldingLotUpdate, HoldingMetadataUpdate, NetWorthSnapshotUpdate, NetWorthSnapshotUpsert
from ..security import require_csrf
from ..services.accounts import UNASSIGNED_ACCOUNT_MARKER
from ..services.mutation_log import MutationChange, full_values, journal_mutation
from ..services.reporting import cash_flow_summary, category_totals, dashboard_summary, latest_investment_allocation, latest_net_worth_by_account
from ..services.snapshots import net_worth_contributors, net_worth_series, net_worth_stats, refresh_holding_net_worth_snapshot, upsert_net_worth_snapshot
from .dependencies import actor_for_session, current_session, require_delete_confirmation


router = APIRouter()


@router.get("/api/dashboard/summary")
def get_dashboard_summary(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return dashboard_summary(db)


@router.get("/api/cash-flow")
def get_cash_flow(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return cash_flow_summary(db)


@router.get("/api/category-totals")
def get_category_totals(start_date: date | None = None, end_date: date | None = None, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return category_totals(db, start_date=start_date, end_date=end_date)


@router.get("/api/net-worth/timeseries")
def get_net_worth_timeseries(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    rows = db.execute(select(HoldingSnapshot.snapshot_date, HoldingSnapshot.market_value_cents).order_by(HoldingSnapshot.snapshot_date.asc(), HoldingSnapshot.id.asc())).all()
    grouped: dict[str, int] = {}
    for snapshot_date, market_value_cents in rows:
        key = snapshot_date.isoformat()
        grouped[key] = grouped.get(key, 0) + market_value_cents
    return [{"date": key, "market_value_cents": value} for key, value in grouped.items()]


@router.get("/api/net-worth/accounts")
def get_net_worth_accounts(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return latest_net_worth_by_account(db)


@router.get("/api/snapshots/networth")
def get_net_worth_series(from_date: date | None = Query(default=None, alias="from"), to_date: date | None = Query(default=None, alias="to"), bucket: Literal["day", "week", "month"] = "day", session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    try:
        return net_worth_series(db, from_date=from_date, to_date=to_date, bucket=bucket)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/api/snapshots/networth/stats")
def get_net_worth_stats(from_date: date = Query(alias="from"), to_date: date = Query(alias="to"), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    try:
        return net_worth_stats(db, from_date=from_date, to_date=to_date)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/api/snapshots/networth/contributors")
def get_net_worth_contributors(from_date: date = Query(alias="from"), to_date: date = Query(alias="to"), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    try:
        return net_worth_contributors(db, from_date=from_date, to_date=to_date)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/snapshots/networth/manual")
def save_manual_net_worth_snapshot(payload: NetWorthSnapshotUpsert, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    account = db.get(Account, payload.account_id)
    if not account or account.status != "active" or account.last_four == UNASSIGNED_ACCOUNT_MARKER:
        raise HTTPException(status_code=400, detail="Choose an active account")
    if account.account_type == "external":
        raise HTTPException(status_code=400, detail="Untracked accounts are excluded from net worth")
    snapshot = db.scalar(select(NetWorthSnapshot).where(NetWorthSnapshot.account_id == payload.account_id, NetWorthSnapshot.snapshot_date == payload.snapshot_date))
    before = full_values(snapshot) if snapshot else None
    snapshot = upsert_net_worth_snapshot(db, account_id=payload.account_id, snapshot_date=payload.snapshot_date, balance_cents=payload.balance_cents, source="manual")
    db.flush()
    operation_id = journal_mutation(db, kind="update" if before else "create", entity_type="net_worth_snapshot", actor=actor_for_session(session), description=f"Recorded {account.display_name} balance for {payload.snapshot_date.isoformat()}", changes=[MutationChange(snapshot.id, before, full_values(snapshot))])
    db.commit()
    return {"ok": True, "snapshot_id": snapshot.id, "operation_id": operation_id}


@router.get("/api/snapshots/networth/manual")
def list_manual_net_worth_snapshots(account_id: int | None = None, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    query = select(NetWorthSnapshot).where(NetWorthSnapshot.source == "manual").order_by(NetWorthSnapshot.snapshot_date.desc(), NetWorthSnapshot.id.desc())
    if account_id is not None:
        query = query.where(NetWorthSnapshot.account_id == account_id)
    accounts = {account.id: account for account in db.scalars(select(Account)).all()}
    checkpoint_keys = {(checkpoint.account_id, checkpoint.statement_date) for checkpoint in db.scalars(select(StatementCheckpoint)).all()}
    return [{"id": snapshot.id, "account_id": snapshot.account_id, "account": accounts[snapshot.account_id].display_name if snapshot.account_id in accounts else "Unknown account", "snapshot_date": snapshot.snapshot_date.isoformat(), "balance_cents": snapshot.balance_cents, "source": snapshot.source} for snapshot in db.scalars(query).all() if (snapshot.account_id, snapshot.snapshot_date) not in checkpoint_keys]


def _editable_manual_snapshot(db: Session, snapshot_id: int) -> NetWorthSnapshot:
    snapshot = db.get(NetWorthSnapshot, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Net-worth snapshot not found")
    if snapshot.source != "manual":
        raise HTTPException(status_code=400, detail="Imported snapshots cannot be edited")
    checkpoint = db.scalar(select(StatementCheckpoint).where(StatementCheckpoint.account_id == snapshot.account_id, StatementCheckpoint.statement_date == snapshot.snapshot_date))
    if checkpoint:
        raise HTTPException(status_code=400, detail="Statement-backed balances must be changed through reconciliation")
    return snapshot


@router.patch("/api/snapshots/networth/{snapshot_id}")
def update_manual_net_worth_snapshot(snapshot_id: int, payload: NetWorthSnapshotUpdate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    snapshot = _editable_manual_snapshot(db, snapshot_id)
    conflict = db.scalar(select(NetWorthSnapshot).where(NetWorthSnapshot.account_id == snapshot.account_id, NetWorthSnapshot.snapshot_date == payload.snapshot_date, NetWorthSnapshot.id != snapshot.id))
    if conflict:
        raise HTTPException(status_code=409, detail="That account already has a balance on this date")
    before = full_values(snapshot)
    snapshot.snapshot_date = payload.snapshot_date
    snapshot.balance_cents = payload.balance_cents
    db.flush()
    operation_id = journal_mutation(db, kind="update", entity_type="net_worth_snapshot", actor=actor_for_session(session), description=f"Updated manual balance for {payload.snapshot_date.isoformat()}", changes=[MutationChange(snapshot.id, before, full_values(snapshot))])
    record_audit_event(db, "net_worth_snapshot_update", actor_for_session(session), "net_worth_snapshot", str(snapshot.id), {"operation_id": operation_id})
    db.commit()
    return {"ok": True, "operation_id": operation_id}


@router.delete("/api/snapshots/networth/{snapshot_id}")
def delete_manual_net_worth_snapshot(snapshot_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    snapshot = _editable_manual_snapshot(db, snapshot_id)
    before = full_values(snapshot)
    operation_id = journal_mutation(db, kind="delete", entity_type="net_worth_snapshot", actor=actor_for_session(session), description=f"Deleted manual balance for {snapshot.snapshot_date.isoformat()}", changes=[MutationChange(snapshot.id, before, None)])
    record_audit_event(db, "net_worth_snapshot_delete", actor_for_session(session), "net_worth_snapshot", str(snapshot.id), {"operation_id": operation_id})
    db.delete(snapshot)
    db.commit()
    return {"ok": True, "operation_id": operation_id}


@router.get("/api/investments/lots")
def get_holding_lots(account_id: int | None = None, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    query = select(HoldingLot).order_by(HoldingLot.acquisition_date.asc(), HoldingLot.id.asc())
    if account_id is not None:
        query = query.where(HoldingLot.account_id == account_id)
    accounts = {account.id: account for account in db.scalars(select(Account)).all()}
    return [{"id": lot.id, "account_id": lot.account_id, "symbol": lot.symbol, "acquisition_date": lot.acquisition_date.isoformat(), "quantity_basis_points": lot.quantity_basis_points, "quantity": lot.quantity_basis_points / 10000, "cost_basis_cents": lot.cost_basis_cents, "note": lot.note, "source": lot.source, "import_batch_id": lot.import_batch_id, "account": accounts[lot.account_id].display_name if lot.account_id in accounts else "Unknown account"} for lot in db.scalars(query).all()]


@router.post("/api/investments/lots")
def create_holding_lot(payload: HoldingLotCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    account = db.get(Account, payload.account_id)
    if not account or account.status != "active" or account.account_type not in {"brokerage", "retirement"}:
        raise HTTPException(status_code=400, detail="Choose an active brokerage or retirement account")
    symbol = payload.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol is required")
    lot = HoldingLot(account_id=account.id, symbol=symbol, acquisition_date=payload.acquisition_date, quantity_basis_points=payload.quantity_basis_points, cost_basis_cents=payload.cost_basis_cents, note=payload.note.strip() if payload.note and payload.note.strip() else None)
    db.add(lot)
    db.flush()
    operation_id = journal_mutation(db, kind="create", entity_type="holding_lot", actor=actor_for_session(session), description=f"Added {symbol} tax lot", changes=[MutationChange(lot.id, None, full_values(lot))])
    record_audit_event(db, "holding_lot_create", actor_for_session(session), "holding_lot", str(lot.id), {"account_id": account.id, "symbol": symbol, "operation_id": operation_id})
    db.commit()
    return {"ok": True, "lot_id": lot.id, "operation_id": operation_id}


@router.patch("/api/investments/lots/{lot_id}")
def update_holding_lot(lot_id: int, payload: HoldingLotUpdate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    lot = db.get(HoldingLot, lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Holding lot not found")
    before = full_values(lot)
    lot.acquisition_date = payload.acquisition_date
    lot.quantity_basis_points = payload.quantity_basis_points
    lot.cost_basis_cents = payload.cost_basis_cents
    lot.note = payload.note.strip() if payload.note and payload.note.strip() else None
    db.flush()
    operation_id = journal_mutation(db, kind="update", entity_type="holding_lot", actor=actor_for_session(session), description=f"Updated {lot.symbol} tax lot", changes=[MutationChange(lot.id, before, full_values(lot))])
    record_audit_event(db, "holding_lot_update", actor_for_session(session), "holding_lot", str(lot.id), {"account_id": lot.account_id, "symbol": lot.symbol, "operation_id": operation_id})
    db.commit()
    return {"ok": True, "operation_id": operation_id}


@router.delete("/api/investments/lots/{lot_id}")
def delete_holding_lot(lot_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    lot = db.get(HoldingLot, lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Holding lot not found")
    operation_id = journal_mutation(db, kind="delete", entity_type="holding_lot", actor=actor_for_session(session), description=f"Deleted {lot.symbol} tax lot", changes=[MutationChange(lot.id, full_values(lot), None)])
    record_audit_event(db, "holding_lot_delete", actor_for_session(session), "holding_lot", str(lot.id), {"account_id": lot.account_id, "symbol": lot.symbol, "operation_id": operation_id})
    db.delete(lot)
    db.commit()
    return {"ok": True, "operation_id": operation_id}


@router.get("/api/investments/holdings")
def get_investment_holdings(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    accounts = {account.id: account for account in db.scalars(select(Account)).all()}
    institutions = {institution.id: institution.name for institution in db.scalars(select(Institution)).all()}
    metadata = {item.symbol.upper(): item for item in db.scalars(select(SecurityMetadata)).all()}
    prices = db.scalars(select(SecurityPrice).order_by(SecurityPrice.price_date.asc(), SecurityPrice.id.asc())).all()
    latest_prices: dict[str, SecurityPrice] = {}
    for price in prices:
        latest_prices[price.symbol.upper()] = price
    rows = db.scalars(select(HoldingSnapshot).order_by(HoldingSnapshot.snapshot_date.asc(), HoldingSnapshot.id.asc())).all()
    latest_dates: dict[int, object] = {}
    for row in rows:
        latest_dates[row.account_id] = max(latest_dates.get(row.account_id, row.snapshot_date), row.snapshot_date)
    latest_rows = [row for row in rows if latest_dates.get(row.account_id) == row.snapshot_date]
    lots_by_security: dict[tuple[int, str], list[HoldingLot]] = {}
    for lot in db.scalars(select(HoldingLot).order_by(HoldingLot.acquisition_date.asc(), HoldingLot.id.asc())).all():
        lots_by_security.setdefault((lot.account_id, lot.symbol.upper()), []).append(lot)
    payload = []
    for row in latest_rows:
        symbol_key = (row.symbol or "").upper()
        meta = metadata.get(symbol_key)
        latest_price = latest_prices.get(symbol_key)
        displayed_price_cents = latest_price.price_cents if latest_price else row.price_cents
        displayed_price_date = latest_price.price_date.isoformat() if latest_price else row.snapshot_date.isoformat()
        displayed_value_cents = row.market_value_cents
        if latest_price and row.quantity_basis_points is not None:
            displayed_value_cents = round((row.quantity_basis_points * latest_price.price_cents) / 10000)
        security_lots = lots_by_security.get((row.account_id, symbol_key), []) if symbol_key else []
        cost_basis_cents = sum(lot.cost_basis_cents for lot in security_lots) if security_lots else row.cost_basis_cents
        oldest_acquisition_date = security_lots[0].acquisition_date if security_lots else None
        payload.append({"id": row.id, "account_id": row.account_id, "account": accounts[row.account_id].display_name if row.account_id in accounts else "Unknown account", "institution": institutions.get(accounts[row.account_id].institution_id) if row.account_id in accounts else None, "snapshot_date": row.snapshot_date.isoformat(), "symbol": row.symbol, "description": meta.user_description if meta and meta.user_description else row.description, "csv_description": row.description, "user_description": meta.user_description if meta else None, "quantity": row.quantity_basis_points / 10000 if row.quantity_basis_points is not None else None, "price_cents": row.price_cents, "display_price_cents": displayed_price_cents, "price_date": displayed_price_date, "market_value_cents": row.market_value_cents, "display_market_value_cents": displayed_value_cents, "asset_class": row.asset_class, "lot_count": len(security_lots), "lot_quantity": sum(lot.quantity_basis_points for lot in security_lots) / 10000 if security_lots else None, "cost_basis_cents": cost_basis_cents, "unrealized_gain_loss_cents": displayed_value_cents - cost_basis_cents if cost_basis_cents is not None else None, "oldest_acquisition_date": oldest_acquisition_date.isoformat() if oldest_acquisition_date else None, "lot_age_days": (date.today() - oldest_acquisition_date).days if oldest_acquisition_date else None})
    return payload


@router.patch("/api/investments/holding-metadata")
def update_holding_metadata(payload: HoldingMetadataUpdate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    symbol = payload.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol is required")
    metadata = db.scalar(select(SecurityMetadata).where(SecurityMetadata.symbol == symbol))
    before = full_values(metadata) if metadata else None
    if not metadata:
        metadata = SecurityMetadata(symbol=symbol)
        db.add(metadata)
        db.flush()
    metadata.user_description = payload.user_description.strip() if payload.user_description else None
    operation_id = journal_mutation(db, kind="update" if before else "create", entity_type="security_metadata", actor=actor_for_session(session), description=f"Updated holding description for {symbol}", changes=[MutationChange(metadata.id, before, full_values(metadata))])
    record_audit_event(db, "holding_metadata_update", "local-user", "security_metadata", symbol, {"symbol": symbol})
    db.commit()
    return {"ok": True, "operation_id": operation_id}


def _delete_holding_row(db: Session, holding: HoldingSnapshot) -> None:
    record_audit_event(db, "holding_delete", "local-user", "holding_snapshot", str(holding.id), {"symbol": holding.symbol, "market_value_cents": holding.market_value_cents, "snapshot_date": holding.snapshot_date.isoformat()})
    db.delete(holding)


@router.delete("/api/investments/holdings/bulk-delete")
def bulk_delete_holdings(payload: BulkDeleteRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    require_delete_confirmation(payload.confirm_text)
    if not payload.ids:
        raise HTTPException(status_code=400, detail="Choose at least one holding to delete")
    holdings = db.scalars(select(HoldingSnapshot).where(HoldingSnapshot.id.in_(payload.ids))).all()
    found_ids = {holding.id for holding in holdings}
    missing_ids = [holding_id for holding_id in payload.ids if holding_id not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"Holding row not found: {missing_ids[0]}")
    changes = [MutationChange(holding.id, full_values(holding), None) for holding in holdings]
    scopes = {(holding.account_id, holding.snapshot_date) for holding in holdings}
    for holding in holdings:
        _delete_holding_row(db, holding)
    operation_id = journal_mutation(db, kind="delete", entity_type="holding_snapshot", actor=actor_for_session(session), description=f"Deleted {len(holdings)} holding rows", changes=changes)
    for account_id, snapshot_date in scopes:
        refresh_holding_net_worth_snapshot(db, account_id=account_id, snapshot_date=snapshot_date)
    db.commit()
    return {"ok": True, "deleted": len(holdings), "operation_id": operation_id}


@router.delete("/api/investments/holdings/{holding_id}")
def delete_holding(holding_id: int, payload: DeleteConfirmRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    require_delete_confirmation(payload.confirm_text)
    holding = db.get(HoldingSnapshot, holding_id)
    if not holding:
        raise HTTPException(status_code=404, detail="Holding row not found")
    account_id, snapshot_date = holding.account_id, holding.snapshot_date
    operation_id = journal_mutation(db, kind="delete", entity_type="holding_snapshot", actor=actor_for_session(session), description=f'Deleted holding "{holding.symbol or holding.description or holding.id}"', changes=[MutationChange(holding.id, full_values(holding), None)])
    _delete_holding_row(db, holding)
    refresh_holding_net_worth_snapshot(db, account_id=account_id, snapshot_date=snapshot_date)
    db.commit()
    return {"ok": True, "operation_id": operation_id}


@router.get("/api/investments/allocation")
def get_investment_allocation(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return latest_investment_allocation(db)


@router.get("/api/investments/value-timeseries")
def get_investment_value_timeseries(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return get_net_worth_timeseries(session, db)
