import { Link2, X } from "lucide-react";

export type HistoricalRefundBulkPreview = {
  selection_token: string;
  pair_count: number;
  refund_total_cents: number;
  net_change_cents: number;
  date_from: string | null;
  date_to: string | null;
  accounts: { account_id: number; account: string; pairs: number }[];
  categories: { category: string; pairs: number }[];
  sources: { source: string; pairs: number }[];
  criteria: string[];
};

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

export function HistoricalRefundBulkConfirm({ preview, busy, onClose, onConfirm }: { preview: HistoricalRefundBulkPreview; busy: boolean; onClose: () => void; onConfirm: () => void }) {
  return <div className="modalBackdrop" onClick={busy ? undefined : onClose}>
    <section className="modalCard duplicateBulkModal" role="dialog" aria-modal="true" aria-labelledby="historical-refund-bulk-title" onClick={(event) => event.stopPropagation()}>
      <div className="modalHeader">
        <div><h2 id="historical-refund-bulk-title">Link intentional historical refunds</h2><p>Create explicit refund relationships without deleting rows or changing signed totals.</p></div>
        <button className="ghostButton" onClick={onClose} disabled={busy} aria-label="Close confirmation"><X size={16} /></button>
      </div>
      <div className="duplicateBulkChoice"><Link2 size={20} /><div><strong>{preview.pair_count} full-refund pair{preview.pair_count === 1 ? "" : "s"}</strong><span>The positive refund will be linked to its matching expense and removed from Duplicate Review.</span></div></div>
      <div className="duplicateBulkMetrics">
        <div><span>Refunds linked</span><strong>{preview.pair_count}</strong></div>
        <div><span>Refund value</span><strong>{money.format(preview.refund_total_cents / 100)}</strong></div>
        <div><span>Rows deleted</span><strong>0</strong></div>
        <div><span>Net ledger change</span><strong>{money.format(preview.net_change_cents / 100)}</strong></div>
      </div>
      <p className="duplicateBulkImpactNote">Dates, amounts, categories, and account balances remain unchanged. The action adds refund badges, Has refund filtering, and durable expense-to-refund provenance.</p>
      <div className="duplicateBulkDetails">
        <section><h3>Accounts</h3><div className="duplicateBulkSources">{preview.accounts.map((row) => <span key={row.account_id}><strong>{row.pairs}</strong>{row.account}</span>)}</div></section>
        <section><h3>Categories</h3><div className="duplicateBulkSources">{preview.categories.map((row) => <span key={row.category}><strong>{row.pairs}</strong>{row.category}</span>)}</div></section>
        <section><h3>Import sources</h3><div className="duplicateBulkSources">{preview.sources.map((row) => <span key={row.source}><strong>{row.pairs}</strong>{row.source}</span>)}</div></section>
      </div>
      <div className="duplicateBulkSafety"><Link2 size={18} /><div><strong>Strict eligibility</strong><span>{preview.criteria.join("; ")}. The entire action is journaled and undoable from Activity.</span></div></div>
      <div className="buttonRow duplicateBulkActions">
        <button className="secondaryButton" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="primaryButton" onClick={onConfirm} disabled={busy || preview.pair_count === 0}>{busy ? "Linking…" : `Link ${preview.pair_count} refunds`}</button>
      </div>
    </section>
  </div>;
}
