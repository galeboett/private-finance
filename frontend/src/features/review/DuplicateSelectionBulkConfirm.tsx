import { AlertTriangle, CheckCheck, DatabaseZap, Trash2, X } from "lucide-react";

export type DuplicateSelectionAction = "keep_both" | "remove_new" | "prefer_authoritative_history";
export type DuplicateSelectionPreview = {
  action: DuplicateSelectionAction;
  selection_token: string;
  pair_count: number;
  tiers: Partial<Record<"exact" | "cross_source" | "probable", number>>;
  rows_soft_deleted: number;
  decisions_saved: number;
  balance_change_cents: number;
  category_changes: number;
  type_changes: number;
  authoritative_batch_id: number | null;
  authoritative_source: string | null;
  annotations_preserved: { notes: number; labels: number; splits: number; allocations: number };
  uses_existing_record_identity: boolean;
  date_from: string | null;
  date_to: string | null;
  accounts: { account_id: number; account: string; pairs: number }[];
  sources: { source: string; pairs: number }[];
  transaction_ids: number[];
};

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

function signedMoney(cents: number) {
  if (cents === 0) return money.format(0);
  return `${cents > 0 ? "+" : "-"}${money.format(Math.abs(cents) / 100)}`;
}

export function DuplicateSelectionBulkConfirm({ preview, busy, onClose, onConfirm, backdropClassName = "" }: { preview: DuplicateSelectionPreview; busy: boolean; onClose: () => void; onConfirm: () => void; backdropClassName?: string }) {
  const removing = preview.action === "remove_new";
  const preferringHistory = preview.action === "prefer_authoritative_history";
  const removingProbable = removing && (preview.tiers.probable ?? 0) > 0;
  return <div className={`modalBackdrop ${backdropClassName}`.trim()} onClick={busy ? undefined : onClose}>
    <section className="modalCard duplicateBulkModal" role="dialog" aria-modal="true" aria-labelledby="duplicate-selection-title" onClick={(event) => event.stopPropagation()}>
      <div className="modalHeader">
        <div><h2 id="duplicate-selection-title">Confirm selected duplicate action</h2><p>This applies only to the pairs you selected on the current page.</p></div>
        <button className="ghostButton" onClick={onClose} disabled={busy} aria-label="Close confirmation"><X size={16} /></button>
      </div>
      <div className="duplicateBulkChoice">
        {removing ? <Trash2 size={20} /> : preferringHistory ? <DatabaseZap size={20} /> : <CheckCheck size={20} />}
        <div><strong>{removing ? "Remove selected new copies" : preferringHistory ? "Prefer authoritative history" : "Keep both transactions"}</strong><span>{removing ? "Move the selected exact-match candidates to Trash while retaining the established ledger rows." : preferringHistory ? "Apply the history file's source facts, category, and type to the established records, then retire the redundant imported rows." : "Clear the duplicate flags and remember that every selected pair is legitimate."}</span></div>
      </div>
      <div className="duplicateBulkMetrics">
        <div><span>Selected pairs</span><strong>{preview.pair_count}</strong></div>
        <div><span>Exact / cross-source / probable</span><strong>{preview.tiers.exact ?? 0} / {preview.tiers.cross_source ?? 0} / {preview.tiers.probable ?? 0}</strong></div>
        <div><span>{preferringHistory ? "Category / type changes" : "Rows moved to Trash"}</span><strong>{preferringHistory ? `${preview.category_changes} / ${preview.type_changes}` : preview.rows_soft_deleted}</strong></div>
        <div><span>Ledger adjustment</span><strong className={preview.balance_change_cents < 0 ? "negativeValue" : "positiveValue"}>{signedMoney(preview.balance_change_cents)}</strong></div>
      </div>
      <div className="duplicateBulkDetails">
        <section><h3>Accounts</h3><div className="duplicateBulkSources">{preview.accounts.map((row) => <span key={row.account_id}><strong>{row.pairs}</strong>{row.account}</span>)}</div></section>
        <section><h3>{preferringHistory ? "Authoritative source" : "Selected candidate sources"}</h3><div className="duplicateBulkSources">{preview.sources.map((row) => <span key={row.source}><strong>{row.pairs}</strong>{row.source}</span>)}</div></section>
      </div>
      <div className="duplicateBulkSafety"><AlertTriangle size={18} /><div><strong>{removingProbable ? "Probable matches can be legitimate, similar purchases" : removing ? "Exact matches can still be legitimate repeated purchases" : preferringHistory ? "Established record identity and annotations are preserved" : "Keep both decisions are remembered by future scans"}</strong><span>{preferringHistory ? `Notes (${preview.annotations_preserved.notes}), labels (${preview.annotations_preserved.labels}), splits (${preview.annotations_preserved.splits}), allocations (${preview.annotations_preserved.allocations}), and existing links stay attached. ${preview.rows_soft_deleted} redundant row${preview.rows_soft_deleted === 1 ? "" : "s"} will move to Trash.` : removingProbable ? "This selection includes description-similarity matches. Confirm each selected pair before removing the new copies." : "Confirm that the selected scope matches your intent."} The action is recorded once and can be undone from Activity.</span></div></div>
      <div className="buttonRow duplicateBulkActions">
        <button className="secondaryButton" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="primaryButton" onClick={onConfirm} disabled={busy}>{busy ? "Applying…" : removing ? `Remove ${preview.pair_count} new copies` : preferringHistory ? `Prefer history for ${preview.pair_count} pairs` : `Keep ${preview.pair_count} pairs`}</button>
      </div>
    </section>
  </div>;
}
