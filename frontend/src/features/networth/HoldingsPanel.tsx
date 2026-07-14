import { useState, type FormEvent } from "react";
import { api } from "../../api/client";

export type HoldingRow = {
  id: number;
  account_id: number;
  account: string;
  snapshot_date: string;
  symbol: string | null;
  description: string | null;
  csv_description: string | null;
  user_description: string | null;
  quantity: number | null;
  price_cents: number | null;
  display_price_cents: number | null;
  price_date: string;
  market_value_cents: number;
  display_market_value_cents: number;
  asset_class: string | null;
  lot_count: number;
  lot_quantity: number | null;
  cost_basis_cents: number | null;
  unrealized_gain_loss_cents: number | null;
  oldest_acquisition_date: string | null;
  lot_age_days: number | null;
};

type AccountOption = { id: number; display_name: string };
type Props = {
  rows: HoldingRow[];
  accounts: AccountOption[];
  csrf: string;
  selectedIds: number[];
  selectedVisibleIds: number[];
  visibleIds: number[];
  formatMoney: (cents: number) => string;
  formatDate: (value: string) => string;
  onToggleSelection: (holdingId: number, visibleIds: number[], shiftKey: boolean) => void;
  onRequestBulkDelete: (ids: number[]) => void;
  onClearSelection: () => void;
  onUpdateDescription: (symbol: string | null, userDescription: string) => Promise<void>;
  onRequestDelete: (row: HoldingRow) => void;
  onLotSaved: (operationId: string) => Promise<void>;
  onError: (message: string) => void;
};

export function HoldingsPanel(props: Props) {
  const [showLotForm, setShowLotForm] = useState(false);
  const [accountId, setAccountId] = useState<number | "">(props.accounts[0]?.id ?? "");
  const [symbol, setSymbol] = useState("");
  const [acquisitionDate, setAcquisitionDate] = useState("");
  const [quantity, setQuantity] = useState("");
  const [basis, setBasis] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const sharedPriceDate = props.rows.find((row) => row.price_date)?.price_date ?? "-";

  async function submitLot(event: FormEvent) {
    event.preventDefault();
    const numericQuantity = Number(quantity.replace(/,/g, ""));
    const numericBasis = Number(basis.replace(/[$,\s]/g, ""));
    if (!accountId || !symbol.trim() || !acquisitionDate || !Number.isFinite(numericQuantity) || numericQuantity <= 0 || !Number.isFinite(numericBasis) || numericBasis < 0) {
      props.onError("Enter an account, symbol, acquisition date, positive quantity, and valid total cost basis.");
      return;
    }
    setSaving(true);
    try {
      const result = await api<{ operation_id: string }>("/api/investments/lots", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-csrf-token": props.csrf },
        body: JSON.stringify({ account_id: accountId, symbol: symbol.trim(), acquisition_date: acquisitionDate, quantity_basis_points: Math.round(numericQuantity * 10000), cost_basis_cents: Math.round(numericBasis * 100), note: note.trim() || null }),
      });
      setSymbol(""); setAcquisitionDate(""); setQuantity(""); setBasis(""); setNote(""); setShowLotForm(false);
      await props.onLotSaved(result.operation_id);
    } catch (error) {
      props.onError(error instanceof Error ? error.message : "Tax lot could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="holdingsPanel">
      <div className="holdingsPanelTitle"><div><strong>Holding details</strong><span>Latest market values plus separately managed acquisition dates and cost basis.</span></div><button className="secondaryButton compactButton" onClick={() => setShowLotForm((current) => !current)}>{showLotForm ? "Cancel lot" : "Add tax lot"}</button></div>
      {showLotForm ? <form className="holdingLotForm" onSubmit={submitLot}>
        <label>Account<select value={accountId} onChange={(event) => setAccountId(Number(event.target.value) || "")} required><option value="">Choose account</option>{props.accounts.map((account) => <option value={account.id} key={account.id}>{account.display_name}</option>)}</select></label>
        <label>Symbol<input value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} placeholder="VTI" required /></label>
        <label>Acquired<input type="date" value={acquisitionDate} onChange={(event) => setAcquisitionDate(event.target.value)} required /></label>
        <label>Quantity<input inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} placeholder="10.0000" required /></label>
        <label>Total cost basis<input inputMode="decimal" value={basis} onChange={(event) => setBasis(event.target.value)} placeholder="800.00" required /></label>
        <label>Note<input value={note} onChange={(event) => setNote(event.target.value)} placeholder="Optional" /></label>
        <button className="primaryButton compactButton" disabled={saving}>{saving ? "Saving..." : "Save lot"}</button>
      </form> : null}
      {props.rows.length > 0 ? <div className="selectionToolbar"><span>{props.selectedVisibleIds.length} selected</span><button className="dangerTextButton" onClick={() => props.onRequestBulkDelete(props.selectedVisibleIds)} disabled={props.selectedVisibleIds.length === 0}>Delete selected</button><button className="secondaryButton" onClick={props.onClearSelection}>Clear</button></div> : null}
      <div className="holdingsTable">
        <div className="holdingsHeader"><span>Select</span><span>Account</span><span>Symbol</span><span>Description</span><span>Quantity</span><span className="stackedHeader">Price<small>{props.formatDate(sharedPriceDate)}</small></span><span>Value</span><span>Basis</span><span>Gain/loss</span><span>Lot age</span><span>Action</span></div>
        {props.rows.slice(0, 12).map((row) => <div className={props.selectedIds.includes(row.id) ? "holdingsRow selected" : "holdingsRow"} key={row.id}>
          <input type="checkbox" checked={props.selectedIds.includes(row.id)} onChange={(event) => props.onToggleSelection(row.id, props.visibleIds, (event.nativeEvent as MouseEvent).shiftKey)} title="Select holding. Hold Shift to select a range." />
          <span>{row.account}</span><strong>{row.symbol || "Holding"}</strong>
          <div className="holdingDescriptionEdit"><input defaultValue={row.user_description ?? row.csv_description ?? ""} onBlur={(event) => void updateIfChanged(row, event.currentTarget.value, props.onUpdateDescription)} placeholder="Add your description" />{row.csv_description ? <small>CSV: {row.csv_description}</small> : null}</div>
          <span>{row.quantity ?? "-"}</span><span>{row.display_price_cents == null ? "-" : props.formatMoney(row.display_price_cents)}</span><span>{props.formatMoney(row.display_market_value_cents)}</span>
          <span>{row.cost_basis_cents == null ? "-" : props.formatMoney(row.cost_basis_cents)}</span><strong className={row.unrealized_gain_loss_cents != null && row.unrealized_gain_loss_cents < 0 ? "amount negative" : "amount positive"}>{row.unrealized_gain_loss_cents == null ? "-" : props.formatMoney(row.unrealized_gain_loss_cents)}</strong>
          <span title={row.oldest_acquisition_date ? `Oldest lot acquired ${props.formatDate(row.oldest_acquisition_date)}` : undefined}>{formatLotAge(row.lot_age_days, row.lot_count)}</span>
          <button className="dangerTextButton" onClick={() => props.onRequestDelete(row)}>Delete</button>
        </div>)}
        {props.rows.length === 0 ? <p className="emptyText">No holdings rows to inspect yet.</p> : null}
      </div>
    </div>
  );
}

async function updateIfChanged(row: HoldingRow, nextDescription: string, onUpdate: (symbol: string | null, userDescription: string) => Promise<void>) {
  const previous = row.user_description ?? row.csv_description ?? "";
  if (nextDescription.trim() !== previous.trim()) await onUpdate(row.symbol, nextDescription);
}

export function formatLotAge(days: number | null, lotCount: number) {
  if (days == null || lotCount === 0) return "-";
  if (days < 365) return `${days}d / ${lotCount} lot${lotCount === 1 ? "" : "s"}`;
  return `${(days / 365.25).toFixed(1)}y / ${lotCount} lot${lotCount === 1 ? "" : "s"}`;
}
