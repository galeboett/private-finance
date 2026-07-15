import { AlertTriangle, ArrowRightLeft, CheckCircle2, X } from "lucide-react";

export type DuplicateBulkStrategy = "keep_existing" | "use_new_import";

type SourceCount = { source: string; count: number };
type AccountImpact = {
  account_id: number;
  account: string;
  institution: string | null;
  pairs: number;
  transactions_retained: number;
  balance_change_cents: number;
};

export type DuplicateBulkPreview = {
  strategy: DuplicateBulkStrategy;
  selection_token: string;
  pair_count: number;
  transactions_retained: number;
  rows_soft_deleted: number;
  accounts: AccountImpact[];
  account_count: number;
  balance_change_cents: number;
  date_from: string | null;
  date_to: string | null;
  selected_sources: SourceCount[];
  retired_sources: SourceCount[];
  annotations_preserved: { categorized: number; notes: number; labels: number; splits: number; allocations: number };
  uses_existing_record_identity: boolean;
};

type Props = {
  preview: DuplicateBulkPreview;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
};

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

function signedMoney(cents: number) {
  if (cents === 0) return money.format(0);
  return `${cents > 0 ? "+" : "-"}${money.format(Math.abs(cents) / 100)}`;
}

export function DuplicateBulkConfirm({ preview, busy, onClose, onConfirm }: Props) {
  const useNew = preview.strategy === "use_new_import";
  const actionLabel = useNew ? "Use newest import data" : "Keep existing ledger data";
  return <div className="modalBackdrop" onClick={busy ? undefined : onClose}>
    <section className="modalCard duplicateBulkModal" role="dialog" aria-modal="true" aria-labelledby="duplicate-bulk-title" onClick={(event) => event.stopPropagation()}>
      <div className="modalHeader">
        <div>
          <h2 id="duplicate-bulk-title">Confirm bulk duplicate resolution</h2>
          <p>This applies to every safely identified reimport in the queue, not only the current page or filter.</p>
        </div>
        <button className="ghostButton" onClick={onClose} disabled={busy} aria-label="Close confirmation"><X size={16} /></button>
      </div>

      <div className="duplicateBulkChoice">
        {useNew ? <ArrowRightLeft size={20} /> : <CheckCircle2 size={20} />}
        <div><strong>{actionLabel}</strong><span>{useNew
          ? "Copy the newest imported bank facts and import-source label onto the established ledger records, then retire the redundant imported rows."
          : "Leave established ledger records unchanged and retire all redundant imported rows."}</span></div>
      </div>

      <div className="duplicateBulkMetrics">
        <div><span>Safe pairs</span><strong>{preview.pair_count}</strong></div>
        <div><span>Accounts</span><strong>{preview.account_count}</strong></div>
        <div><span>Rows moved to Trash</span><strong>{preview.rows_soft_deleted}</strong></div>
        <div><span>Ledger adjustment</span><strong className={preview.balance_change_cents < 0 ? "negativeValue" : "positiveValue"}>{signedMoney(preview.balance_change_cents)}</strong></div>
      </div>

      <p className="duplicateBulkImpactNote">The ledger adjustment removes the extra copy already included in account totals. A positive number raises the displayed balance; a negative number lowers it.</p>

      <div className="duplicateBulkDetails">
        <section>
          <h3>Account impact</h3>
          <div className="duplicateBulkTable">
            {preview.accounts.map((account) => <div key={account.account_id}>
              <span><strong>{account.account}</strong>{account.institution ? <small>{account.institution}</small> : null}</span>
              <span>{account.pairs} pair{account.pairs === 1 ? "" : "s"}</span>
              <strong className={account.balance_change_cents < 0 ? "negativeValue" : "positiveValue"}>{signedMoney(account.balance_change_cents)}</strong>
            </div>)}
          </div>
        </section>
        <section>
          <h3>Transaction data selected from</h3>
          <div className="duplicateBulkSources">{preview.selected_sources.map((source) => <span key={source.source}><strong>{source.count}</strong>{source.source}</span>)}</div>
        </section>
        <section>
          <h3>Redundant rows being retired</h3>
          <div className="duplicateBulkSources">{preview.retired_sources.map((source) => <span key={source.source}><strong>{source.count}</strong>{source.source}</span>)}</div>
        </section>
      </div>

      <div className="duplicateBulkSafety">
        <AlertTriangle size={18} />
        <div><strong>What is protected</strong><span>Probable and opposite-sign pairs are excluded. Categories on {preview.annotations_preserved.categorized} retained transactions, plus notes, labels, splits, allocations, links, and internal record identity remain attached. The entire action is journaled and undoable from Activity.</span></div>
      </div>

      <div className="buttonRow duplicateBulkActions">
        <button className="secondaryButton" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="primaryButton" onClick={onConfirm} disabled={busy || preview.pair_count === 0}>{busy ? "Applying…" : `Confirm: ${actionLabel.toLowerCase()}`}</button>
      </div>
    </section>
  </div>;
}
