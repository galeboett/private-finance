import { useState, type FormEvent } from "react";
import { api } from "../../api/client";
import { HoldingsTable, type HoldingRow } from "./HoldingsTable";
import { LotEditor } from "./LotEditor";

export type { HoldingRow } from "./HoldingsTable";

type AccountOption = { id: number; display_name: string };
type Props = {
  rows: HoldingRow[];
  accounts: AccountOption[];
  csrf: string;
  selectedIds: number[];
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
  const [editingHolding, setEditingHolding] = useState<HoldingRow | null>(null);
  const visibleIds = props.rows.map((row) => row.id);
  const selectedVisibleIds = visibleIds.filter((id) => props.selectedIds.includes(id));

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
      {props.rows.length > 0 ? <div className="selectionToolbar"><span>{selectedVisibleIds.length} selected</span><button className="dangerTextButton" onClick={() => props.onRequestBulkDelete(selectedVisibleIds)} disabled={selectedVisibleIds.length === 0}>Delete selected</button><button className="secondaryButton" onClick={props.onClearSelection}>Clear</button></div> : null}
      <HoldingsTable rows={props.rows} selectedIds={props.selectedIds} formatMoney={props.formatMoney} formatDate={props.formatDate} onToggleSelection={props.onToggleSelection} onUpdateDescription={props.onUpdateDescription} onRequestDelete={props.onRequestDelete} onManageLots={setEditingHolding} />
      {editingHolding ? <LotEditor holding={editingHolding} csrf={props.csrf} formatMoney={props.formatMoney} onClose={() => setEditingHolding(null)} onChanged={async (operationId) => props.onLotSaved(operationId)} onError={props.onError} /> : null}
    </div>
  );
}
