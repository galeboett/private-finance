import { useEffect, useState } from "react";

import { useApiClient } from "../../api/hooks";
import { DeleteConfirmInline } from "../../components/DeleteConfirmInline";

type ManualSnapshot = { id: number; account_id: number; account: string; snapshot_date: string; balance_cents: number; source: "manual" };
type AccountOption = { id: number; display_name: string; last_four: string | null };

export function ManualSnapshotEditor({ accounts, csrf, onCreate, onChanged, onError }: { accounts: AccountOption[]; csrf: string; onCreate: (accountId: number, snapshotDate: string, balance: string) => Promise<boolean>; onChanged: (operationId: string, message: string) => Promise<void>; onError: (message: string) => void }) {
  const api = useApiClient();
  const [rows, setRows] = useState<ManualSnapshot[]>([]);
  const [accountId, setAccountId] = useState<number | "">(accounts[0]?.id ?? "");
  const [date, setDate] = useState(new Date().toLocaleDateString("en-CA"));
  const [balance, setBalance] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  async function load() {
    try { setRows(await api<ManualSnapshot[]>("/api/snapshots/networth/manual")); }
    catch (error) { onError(error instanceof Error ? error.message : "Manual balances could not be loaded."); }
  }
  useEffect(() => { void load(); }, [refreshKey]);
  return <section className="manualSnapshotEditor">
    <div><strong>Manual balances</strong><span>Add or correct direct balance entries. Statement-backed and imported balances are protected.</span></div>
    <div className="manualSnapshotCreateRow"><select value={accountId} onChange={(event) => setAccountId(Number(event.target.value) || "")}><option value="">Choose account</option>{accounts.map((account) => <option value={account.id} key={account.id}>{account.display_name}{account.last_four ? ` (${account.last_four})` : ""}</option>)}</select><input type="date" value={date} onChange={(event) => setDate(event.target.value)} /><input inputMode="decimal" placeholder="Balance" value={balance} onChange={(event) => setBalance(event.target.value)} /><button className="secondaryButton compactButton" onClick={() => { if (accountId) void onCreate(accountId, date, balance).then((saved) => { if (saved) { setBalance(""); setRefreshKey((current) => current + 1); } }); }}>Save balance</button></div>
    {rows.map((row) => <SnapshotRow key={row.id} row={row} csrf={csrf} onChanged={async (operationId, message) => { await onChanged(operationId, message); await load(); }} onError={onError} />)}
  </section>;
}

function SnapshotRow({ row, csrf, onChanged, onError }: { row: ManualSnapshot; csrf: string; onChanged: (operationId: string, message: string) => Promise<void>; onError: (message: string) => void }) {
  const api = useApiClient();
  const [date, setDate] = useState(row.snapshot_date);
  const [balance, setBalance] = useState((row.balance_cents / 100).toFixed(2));
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmText, setConfirmText] = useState("");

  async function save() {
    const numeric = Number(balance.replace(/[$,\s]/g, ""));
    if (!date || !Number.isFinite(numeric)) { onError("Enter a date and valid balance."); return; }
    try {
      const result = await api<{ operation_id: string }>(`/api/snapshots/networth/${row.id}`, { method: "PATCH", headers: { "Content-Type": "application/json", "x-csrf-token": csrf }, body: JSON.stringify({ snapshot_date: date, balance_cents: Math.round(numeric * 100) }) });
      await onChanged(result.operation_id, `${row.account} manual balance updated.`);
    } catch (error) { onError(error instanceof Error ? error.message : "Manual balance could not be updated."); }
  }

  async function remove() {
    try {
      const result = await api<{ operation_id: string }>(`/api/snapshots/networth/${row.id}`, { method: "DELETE", headers: { "x-csrf-token": csrf } });
      setConfirmDelete(false); setConfirmText("");
      await onChanged(result.operation_id, `${row.account} manual balance deleted.`);
    } catch (error) { onError(error instanceof Error ? error.message : "Manual balance could not be deleted."); }
  }

  return <div className="manualSnapshotEditRow"><strong>{row.account}</strong><input type="date" value={date} onChange={(event) => setDate(event.target.value)} /><input inputMode="decimal" value={balance} onChange={(event) => setBalance(event.target.value)} /><button className="secondaryButton compactButton" onClick={() => void save()}>Save</button><button className="dangerTextButton" onClick={() => setConfirmDelete(true)}>Delete</button>{confirmDelete ? <DeleteConfirmInline target={{ kind: "net_worth_snapshot", id: row.id, label: `${row.account} balance on ${row.snapshot_date}` }} confirmText={confirmText} onConfirmTextChange={setConfirmText} onConfirm={remove} onCancel={() => { setConfirmDelete(false); setConfirmText(""); }} /> : null}</div>;
}
