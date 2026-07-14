import { CheckCircle2, RefreshCw, Undo2 } from "lucide-react";

import { TransactionCompareCard, type DuplicateTransaction } from "../review/TransactionCompareCard";

export type RefundLink = {
  id: number;
  expense_transaction: DuplicateTransaction;
  refund_transaction: DuplicateTransaction;
  match_confidence: number;
  confirmed: boolean;
  expense_amount_cents: number;
  linked_refund_cents: number;
  would_exceed_expense: boolean;
};

type Props = {
  suggestions: RefundLink[];
  busy: string | null;
  onDetect: () => void;
  onConfirm: (link: RefundLink) => void;
  onReject: (linkId: number) => void;
};

export function RefundSuggestions({ suggestions, busy, onDetect, onConfirm, onReject }: Props) {
  return (
    <section className="toolPanel refundReviewPanel" id="refund-review">
      <div className="panelTitle"><Undo2 size={18} /><div><h3>Refund Review</h3><p>Connect returned money to the original expense so category totals net correctly.</p></div></div>
      <div className="transferIntro">
        <div><strong>{suggestions.length} likely matches</strong><span>Shows at most the 25 highest-confidence results. Payments, transfers, payroll, and unrelated money-in rows are excluded.</span></div>
        <button className="primaryButton" onClick={onDetect} disabled={busy === "refund-detect"}><RefreshCw size={16} />{busy === "refund-detect" ? "Finding…" : "Find refunds"}</button>
      </div>
      <div className="refundSuggestionList">
        {suggestions.map((link) => (
          <article className="refundSuggestionCard" key={link.id}>
            <div className="transferCardTop"><div><strong>Possible refund of</strong><span>{link.match_confidence}% confidence</span></div><span className="statusBadge suggested">Suggested</span></div>
            <div className="transactionCompareGrid refundCompareGrid">
              <TransactionCompareCard title="Original expense" transaction={link.expense_transaction} diffFields={["date", "amount"]} emphasis="original" />
              <TransactionCompareCard title="Money returned" transaction={link.refund_transaction} diffFields={["date", "amount"]} />
            </div>
            {link.would_exceed_expense ? <p className="refundWarning">This would make linked refunds exceed the original expense and will require an extra confirmation.</p> : null}
            <div className="reviewActions">
              <button className="dangerTextButton" onClick={() => onReject(link.id)} disabled={busy !== null}>Not a match</button>
              <button className="primaryButton" onClick={() => onConfirm(link)} disabled={busy !== null}><CheckCircle2 size={16} />Confirm refund</button>
            </div>
          </article>
        ))}
        {suggestions.length === 0 ? <p className="emptyText">No likely refund suggestions. Choose Find refunds after importing recent transactions.</p> : null}
      </div>
    </section>
  );
}
