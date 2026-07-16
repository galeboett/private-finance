import { AlertTriangle, CheckCircle2, RefreshCw, Undo2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { BulkActionBar } from "../../components/AppPrimitives";
import { useSelection } from "../../lib/useSelection";
import { TransactionCompareCard, type DuplicateTransaction } from "../review/TransactionCompareCard";
import { selectedRefundMatches } from "./refundReview";

export type RefundLink = {
  id: number;
  expense_transaction: DuplicateTransaction;
  refund_transaction: DuplicateTransaction;
  match_confidence: number;
  confirmed: boolean;
  expense_amount_cents: number;
  existing_linked_refund_cents: number;
  remaining_refundable_cents: number;
  linked_refund_cents: number;
  existing_linked_refunds: DuplicateTransaction[];
  would_exceed_expense: boolean;
};

export type RefundCandidate = {
  expense_transaction: DuplicateTransaction;
  match_confidence: number;
  match_reasons: string[];
  expense_amount_cents: number;
  existing_linked_refund_cents: number;
  remaining_refundable_cents: number;
  linked_refund_cents: number;
  existing_linked_refunds: DuplicateTransaction[];
  would_exceed_expense: boolean;
};

export type RefundSuggestionGroup = {
  refund_transaction: DuplicateTransaction;
  candidates: RefundCandidate[];
  candidate_count: number;
  limited_candidates: boolean;
};

export type RefundSelection = {
  refund_transaction_id: number;
  expense_transaction_id: number;
};

type Props = {
  suggestions: RefundSuggestionGroup[];
  busy: string | null;
  onDetect: () => void;
  onConfirm: (suggestion: RefundSuggestionGroup, candidate: RefundCandidate) => void;
  onReject: (suggestion: RefundSuggestionGroup, candidate: RefundCandidate) => void;
  onBulkConfirm: (selections: RefundSelection[]) => void;
  onBulkReject: (selections: RefundSelection[]) => void;
  onNoExpense: (refundIds: number[]) => void;
};

type CategorizationNudgeProps = {
  suggestion: RefundSuggestionGroup;
  busy: string | null;
  formatMoney: (cents: number) => string;
  onConfirm: (suggestion: RefundSuggestionGroup, candidate: RefundCandidate) => void;
  onReject: (suggestion: RefundSuggestionGroup, candidate: RefundCandidate) => void;
};

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

function formatCents(cents: number) {
  return money.format(cents / 100);
}

function ExistingRefundContext({ candidate, incomingRefundCents }: { candidate: RefundCandidate; incomingRefundCents: number }) {
  if (candidate.existing_linked_refunds.length === 0) return null;
  const excess = Math.max(0, candidate.linked_refund_cents - candidate.expense_amount_cents);
  return (
    <aside className={candidate.would_exceed_expense ? "refundExistingContext warning" : "refundExistingContext"}>
      <div>
        <strong>Already linked to this expense</strong>
        <span>{formatCents(candidate.existing_linked_refund_cents)} returned · {formatCents(candidate.remaining_refundable_cents)} remained before this option</span>
      </div>
      <ul>
        {candidate.existing_linked_refunds.map((refund) => <li key={refund.id}><span>{refund.date} · {refund.description}</span><strong>{formatCents(refund.amount_cents)}</strong></li>)}
      </ul>
      {candidate.would_exceed_expense ? <p>Adding {formatCents(incomingRefundCents)} would bring total linked refunds to {formatCents(candidate.linked_refund_cents)} against a {formatCents(candidate.expense_amount_cents)} expense—{formatCents(excess)} over.</p> : null}
    </aside>
  );
}

export function RefundCategorizationNudge({ suggestion, busy, formatMoney, onConfirm, onReject }: CategorizationNudgeProps) {
  const candidate = suggestion.candidates[0];
  if (!candidate) return null;
  return (
    <aside className="refundCategorizationNudge">
      <div><strong>Looks like a refund of {candidate.expense_transaction.description}</strong><span>Link it to net {formatMoney(suggestion.refund_transaction.amount_cents)} against the original expense category.</span></div>
      <div className="buttonRow">
        <button type="button" className="ghostButton compactButton" onClick={() => onReject(suggestion, candidate)} disabled={busy !== null}>Not this expense</button>
        <button type="button" className="primaryButton compactButton" onClick={() => onConfirm(suggestion, candidate)} disabled={busy !== null}><CheckCircle2 size={14} />Link refund</button>
      </div>
    </aside>
  );
}

export function RefundSuggestions({ suggestions, busy, onDetect, onConfirm, onReject, onBulkConfirm, onBulkReject, onNoExpense }: Props) {
  const { selectedIds, setSelectedIds, toggle, resetAnchor } = useSelection();
  const [candidateIndexByRefund, setCandidateIndexByRefund] = useState<Record<number, number>>({});
  const [confirmingMatches, setConfirmingMatches] = useState<RefundSelection[] | null>(null);
  const visibleIds = useMemo(() => suggestions.map((group) => group.refund_transaction.id), [suggestions]);

  useEffect(() => {
    const visible = new Set(visibleIds);
    setSelectedIds((current) => current.filter((id) => visible.has(id)));
    setCandidateIndexByRefund((current) => Object.fromEntries(Object.entries(current).filter(([id]) => visible.has(Number(id)))));
  }, [setSelectedIds, visibleIds]);

  function selectedCandidate(group: RefundSuggestionGroup) {
    const index = Math.min(candidateIndexByRefund[group.refund_transaction.id] ?? 0, Math.max(0, group.candidates.length - 1));
    return group.candidates[index];
  }

  const selectedGroups = suggestions.filter((group) => selectedIds.includes(group.refund_transaction.id));
  const selectedMatches = selectedRefundMatches(suggestions, selectedIds, candidateIndexByRefund);
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.includes(id));
  const selectedHasUncategorizedRefund = selectedGroups.some((group) => group.refund_transaction.category_id === null);
  const confirmationRows = (confirmingMatches ?? []).flatMap((selection) => {
    const group = suggestions.find((item) => item.refund_transaction.id === selection.refund_transaction_id);
    const candidate = group?.candidates.find((item) => item.expense_transaction.id === selection.expense_transaction_id);
    return group && candidate ? [{ group, candidate }] : [];
  });
  const confirmationTotal = confirmationRows.reduce((sum, row) => sum + row.group.refund_transaction.amount_cents, 0);
  const confirmationLowScores = confirmationRows.filter((row) => row.candidate.match_confidence < 80).length;
  const confirmationCategoryConflicts = confirmationRows.filter((row) => row.candidate.match_reasons.includes("Category differs")).length;
  const confirmationOverRefunds = confirmationRows.filter((row) => row.candidate.would_exceed_expense).length;

  function clearSelection() {
    setSelectedIds([]);
    resetAnchor();
  }

  return (
    <section className="toolPanel refundReviewPanel" id="refund-review">
      <div className="panelTitle"><Undo2 size={18} /><div><h3>Refund Review</h3><p>Review each returned-money transaction against its ranked possible expenses.</p></div></div>
      <div className="transferIntro">
        <div><strong>{suggestions.length} refunds with recommendations</strong><span>Each refund shows up to five candidates. The highest-ranked candidate is selected until you choose another numbered option.</span></div>
        <button className="primaryButton" onClick={onDetect} disabled={busy === "refund-detect"}><RefreshCw size={16} />{busy === "refund-detect" ? "Finding…" : "Find refunds"}</button>
      </div>

      {suggestions.length > 0 ? <div className="refundBulkSticky">
        <BulkActionBar count={selectedIds.length} detail="refunds; bulk actions use each refund's selected numbered candidate" onClear={clearSelection}>
          <button className="ghostButton compactButton" onClick={() => { setSelectedIds(allVisibleSelected ? [] : visibleIds); resetAnchor(); }} disabled={busy !== null}>{allVisibleSelected ? "Clear shown" : `Select all shown (${visibleIds.length})`}</button>
          <button className="primaryButton compactButton" onClick={() => setConfirmingMatches(selectedMatches)} disabled={selectedMatches.length === 0 || busy !== null}>Confirm selected matches</button>
          <button className="secondaryButton compactButton" onClick={() => onBulkReject(selectedMatches)} disabled={selectedMatches.length === 0 || busy !== null}>Not these expenses</button>
          <button className="ghostButton compactButton" title={selectedHasUncategorizedRefund ? "Categorize each refund before settling it without an expense." : "Keep these as categorized refunds without linking an expense."} onClick={() => onNoExpense(selectedIds)} disabled={selectedIds.length === 0 || selectedHasUncategorizedRefund || busy !== null}>No expense in ledger</button>
        </BulkActionBar>
      </div> : null}

      <div className="refundSuggestionList">
        {suggestions.map((group) => {
          const candidate = selectedCandidate(group);
          if (!candidate) return null;
          const selectedIndex = group.candidates.indexOf(candidate);
          const refundId = group.refund_transaction.id;
          return (
            <article className={selectedIds.includes(refundId) ? "refundSuggestionCard selected" : "refundSuggestionCard"} key={refundId}>
              <div className="transferCardTop refundGroupHeader">
                <label className="refundGroupSelect"><input type="checkbox" checked={selectedIds.includes(refundId)} onChange={(event) => toggle(refundId, visibleIds, (event.nativeEvent as MouseEvent).shiftKey)} title="Select refund. Hold Shift to select a range; use Ctrl or Cmd to toggle individual refunds." /><span>Select for bulk action</span></label>
                <div><strong>Returned money</strong><span>{candidate.match_confidence}% match score for option {selectedIndex + 1}</span></div>
                <span className="statusBadge suggested">Suggested</span>
              </div>
              <div className="refundCandidateNavigator" aria-label={`Possible expenses for ${group.refund_transaction.description}`}>
                <div><strong>Possible expenses</strong><span>{group.candidate_count} recommendation{group.candidate_count === 1 ? "" : "s"}{group.limited_candidates ? " · showing best five" : ""}</span></div>
                <div className="refundCandidateChips" role="tablist">
                  {group.candidates.map((option, index) => <button type="button" role="tab" aria-selected={index === selectedIndex} className={index === selectedIndex ? "active" : ""} onClick={() => setCandidateIndexByRefund((current) => ({ ...current, [refundId]: index }))} key={option.expense_transaction.id} title={`${option.match_confidence}% match: ${option.expense_transaction.description}`}>{index + 1}<small>{option.match_confidence}%</small></button>)}
                </div>
              </div>
              <div className="transactionCompareGrid refundCompareGrid">
                <TransactionCompareCard title="Money returned" transaction={group.refund_transaction} diffFields={["date", "amount", "category"]} emphasis="original" />
                <TransactionCompareCard title={`Possible expense ${selectedIndex + 1}`} transaction={candidate.expense_transaction} diffFields={["date", "amount", "category"]} />
              </div>
              <div className="refundMatchReasons">{candidate.match_reasons.map((reason) => <span key={reason}>{reason}</span>)}</div>
              <ExistingRefundContext candidate={candidate} incomingRefundCents={group.refund_transaction.amount_cents} />
              {candidate.would_exceed_expense ? <p className="refundWarning">This expense has insufficient unrefunded balance. Linking this option requires an extra confirmation.</p> : null}
              <div className="reviewActions refundReviewActions">
                <button className="dangerTextButton" onClick={() => onReject(group, candidate)} disabled={busy !== null}>Not this expense</button>
                <button className="ghostButton" title={group.refund_transaction.category_id === null ? "Choose a category first." : "Keep this as a reviewed refund without an expense link."} onClick={() => onNoExpense([refundId])} disabled={busy !== null || group.refund_transaction.category_id === null}>No expense in ledger</button>
                <button className="primaryButton" onClick={() => onConfirm(group, candidate)} disabled={busy !== null}><CheckCircle2 size={16} />Link option {selectedIndex + 1}</button>
              </div>
            </article>
          );
        })}
        {suggestions.length === 0 ? <p className="emptyText">No likely refund suggestions. Choose Find refunds after importing recent transactions.</p> : null}
      </div>
      {confirmingMatches ? <div className="modalBackdrop" onClick={() => setConfirmingMatches(null)}>
        <section className="modalCard refundBulkConfirmModal" role="dialog" aria-modal="true" aria-labelledby="refund-bulk-confirm-title" onClick={(event) => event.stopPropagation()}>
          <div className="modalHeader">
            <div><h2 id="refund-bulk-confirm-title">Confirm selected refund links</h2><p>Each refund will use the numbered expense option currently selected on its card.</p></div>
            <button className="ghostButton" onClick={() => setConfirmingMatches(null)} aria-label="Close confirmation"><X size={16} /></button>
          </div>
          <div className="duplicateBulkMetrics">
            <div><span>Refunds</span><strong>{confirmationRows.length}</strong></div>
            <div><span>Total returned</span><strong>{new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(confirmationTotal / 100)}</strong></div>
            <div><span>Scores below 80</span><strong>{confirmationLowScores}</strong></div>
            <div><span>Category conflicts</span><strong>{confirmationCategoryConflicts}</strong></div>
          </div>
          <div className="refundBulkConfirmRows">
            {confirmationRows.map(({ group, candidate }) => <div key={group.refund_transaction.id}><span><strong>{group.refund_transaction.description}</strong><small>{candidate.match_confidence}% match score</small></span><span aria-hidden="true">→</span><span><strong>{candidate.expense_transaction.description}</strong><small>{candidate.expense_transaction.account}</small></span></div>)}
          </div>
          {confirmationLowScores || confirmationCategoryConflicts || confirmationOverRefunds ? <div className="duplicateBulkSafety"><AlertTriangle size={18} /><div><strong>Review the exceptions before applying</strong><span>{confirmationLowScores} low-score selection{confirmationLowScores === 1 ? "" : "s"}, {confirmationCategoryConflicts} category conflict{confirmationCategoryConflicts === 1 ? "" : "s"}, and {confirmationOverRefunds} selection{confirmationOverRefunds === 1 ? "" : "s"} that would exceed the expense.</span></div></div> : null}
          <div className="buttonRow duplicateBulkActions">
            <button className="secondaryButton" onClick={() => setConfirmingMatches(null)}>Cancel</button>
            <button className="primaryButton" onClick={() => { onBulkConfirm(confirmingMatches); setConfirmingMatches(null); }}><CheckCircle2 size={16} />Confirm {confirmationRows.length} link{confirmationRows.length === 1 ? "" : "s"}</button>
          </div>
        </section>
      </div> : null}
    </section>
  );
}
