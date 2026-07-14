import { Link2, Search, X } from "lucide-react";

import type { DuplicateTransaction } from "../review/TransactionCompareCard";
import type { RefundLink } from "./RefundSuggestions";

type Props = {
  open: boolean;
  links: RefundLink[];
  candidates: DuplicateTransaction[];
  loading: boolean;
  expenseAmountCents: number;
  search: string;
  formatMoney: (cents: number) => string;
  formatDate: (value: string) => string;
  onOpen: () => void;
  onClose: () => void;
  onSearch: (value: string) => void;
  onLink: (candidate: DuplicateTransaction) => void;
  onUnlink: (linkId: number) => void;
};

export function RefundLinkPicker({ open, links, candidates, loading, expenseAmountCents, search, formatMoney, formatDate, onOpen, onClose, onSearch, onLink, onUnlink }: Props) {
  if (!open) {
    return <button type="button" className="secondaryButton compactButton" onClick={onOpen}><Link2 size={14} />Link a refund…</button>;
  }
  return (
    <section className="refundLinkPicker" onClick={(event) => event.stopPropagation()}>
      <div className="refundPickerHeader"><div><strong>Refunds</strong><span>Likely merchant refunds within 90 days. Payments, transfers, and unrelated money-in rows are hidden.</span></div><button type="button" className="ghostButton compactIconButton" onClick={onClose} title="Close refund picker"><X size={15} /></button></div>
      {links.length > 0 ? (
        <div className="linkedRefundList">
          {links.map((link) => <div key={link.id}><span>↩ {formatDate(link.refund_transaction.date)} · {link.refund_transaction.description}</span><strong>{formatMoney(link.refund_transaction.amount_cents)}</strong><button type="button" className="dangerTextButton" onClick={() => onUnlink(link.id)}>Unlink</button></div>)}
          <p>Net expense remaining: <strong>{formatMoney(Math.max(0, Math.abs(expenseAmountCents) - links.reduce((sum, link) => sum + link.refund_transaction.amount_cents, 0)))}</strong></p>
        </div>
      ) : <small>No refunds linked yet.</small>}
      <label className="transactionSearchBox refundSearch"><Search size={14} /><input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Search possible refunds" /></label>
      <div className="refundCandidateList">
        {loading ? <p className="emptyText">Loading possible refunds…</p> : candidates.map((candidate) => (
          <button type="button" key={candidate.id} onClick={() => onLink(candidate)}>
            <span><strong>{candidate.description}</strong><small>{formatDate(candidate.date)} · {candidate.account}</small></span>
            <b>{formatMoney(candidate.amount_cents)}</b>
          </button>
        ))}
        {!loading && candidates.length === 0 ? <p className="emptyText">No plausible unlinked refunds found for this expense.</p> : null}
      </div>
    </section>
  );
}
