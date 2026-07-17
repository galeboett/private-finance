import { useEffect, useState } from "react";

import { useApiClient } from "../../api/hooks";
import { DeleteConfirmInline } from "../../components/DeleteConfirmInline";
import type { HoldingRow } from "./HoldingsTable";

type HoldingLot = {
  id: number;
  account_id: number;
  symbol: string;
  acquisition_date: string;
  quantity_basis_points: number;
  quantity: number;
  cost_basis_cents: number;
  note: string | null;
  source: string;
  import_batch_id: number | null;
};

type Props = {
  holding: HoldingRow;
  csrf: string;
  formatMoney: (cents: number) => string;
  onClose: () => void;
  onChanged: (operationId: string, message: string) => Promise<void>;
  onError: (message: string) => void;
};

export function LotEditor(props: Props) {
  const api = useApiClient();
  const [lots, setLots] = useState<HoldingLot[]>([]);
  const [loading, setLoading] = useState(true);

  async function loadLots() {
    setLoading(true);
    try {
      const rows = await api<HoldingLot[]>(`/api/investments/lots?account_id=${props.holding.account_id}`);
      setLots(rows.filter((lot) => lot.symbol.toUpperCase() === (props.holding.symbol ?? "").toUpperCase()));
    } catch (error) {
      props.onError(error instanceof Error ? error.message : "Tax lots could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadLots(); }, [props.holding.account_id, props.holding.symbol]);

  return (
    <section className="lotEditorPanel">
      <div className="holdingsPanelTitle"><div><strong>{props.holding.symbol || "Holding"} tax lots</strong><span>{props.holding.account} · imported lots may be replaced by a later positions import.</span></div><button className="ghostButton compactButton" onClick={props.onClose}>Close</button></div>
      {loading ? <p className="emptyText">Loading tax lots…</p> : lots.map((lot) => <LotRow key={lot.id} lot={lot} csrf={props.csrf} formatMoney={props.formatMoney} onChanged={async (operationId, message) => { await props.onChanged(operationId, message); await loadLots(); }} onError={props.onError} />)}
      {!loading && lots.length === 0 ? <p className="emptyText">No individual tax lots are recorded for this holding. Use Add tax lot to add basis details.</p> : null}
    </section>
  );
}

function LotRow({ lot, csrf, formatMoney, onChanged, onError }: { lot: HoldingLot; csrf: string; formatMoney: (cents: number) => string; onChanged: (operationId: string, message: string) => Promise<void>; onError: (message: string) => void }) {
  const api = useApiClient();
  const [date, setDate] = useState(lot.acquisition_date);
  const [quantity, setQuantity] = useState(String(lot.quantity));
  const [basis, setBasis] = useState((lot.cost_basis_cents / 100).toFixed(2));
  const [note, setNote] = useState(lot.note ?? "");
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmText, setConfirmText] = useState("");

  async function save() {
    const numericQuantity = Number(quantity.replace(/,/g, ""));
    const numericBasis = Number(basis.replace(/[$,\s]/g, ""));
    if (!date || !Number.isFinite(numericQuantity) || numericQuantity <= 0 || !Number.isFinite(numericBasis) || numericBasis < 0) {
      onError("Enter a date, positive quantity, and valid total basis.");
      return;
    }
    setSaving(true);
    try {
      const result = await api<{ operation_id: string }>(`/api/investments/lots/${lot.id}`, { method: "PATCH", headers: { "Content-Type": "application/json", "x-csrf-token": csrf }, body: JSON.stringify({ acquisition_date: date, quantity_basis_points: Math.round(numericQuantity * 10000), cost_basis_cents: Math.round(numericBasis * 100), note: note.trim() || null }) });
      await onChanged(result.operation_id, `${lot.symbol} tax lot updated.`);
    } catch (error) {
      onError(error instanceof Error ? error.message : "Tax lot could not be updated.");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    try {
      const result = await api<{ operation_id: string }>(`/api/investments/lots/${lot.id}`, { method: "DELETE", headers: { "x-csrf-token": csrf } });
      setConfirmDelete(false); setConfirmText("");
      await onChanged(result.operation_id, `${lot.symbol} tax lot deleted.`);
    } catch (error) {
      onError(error instanceof Error ? error.message : "Tax lot could not be deleted.");
    }
  }

  return <div className="lotEditorRow">
    <div className="lotEditorFields"><label>Acquired<input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label><label>Quantity<input inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label><label>Total basis<input inputMode="decimal" value={basis} onChange={(event) => setBasis(event.target.value)} /></label><label>Note<input value={note} onChange={(event) => setNote(event.target.value)} /></label></div>
    <div className="buttonRow"><span className="fileTypeBadge">{lot.source}</span><small>{formatMoney(lot.cost_basis_cents)} recorded basis</small><button className="secondaryButton compactButton" onClick={() => void save()} disabled={saving}>{saving ? "Saving…" : "Save changes"}</button><button className="dangerTextButton" onClick={() => setConfirmDelete(true)}>Delete</button></div>
    {confirmDelete ? <DeleteConfirmInline target={{ kind: "holding_lot", id: lot.id, label: `${lot.symbol} lot acquired ${lot.acquisition_date}` }} confirmText={confirmText} onConfirmTextChange={setConfirmText} onConfirm={remove} onCancel={() => { setConfirmDelete(false); setConfirmText(""); }} /> : null}
  </div>;
}
