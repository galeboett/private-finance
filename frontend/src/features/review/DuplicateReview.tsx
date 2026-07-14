import { CopyCheck } from "lucide-react";

import { TransactionCompareCard, type DuplicateTransaction } from "./TransactionCompareCard";

export type DuplicateAction = "remove_new" | "keep_both" | "replace_old";
export type DuplicatePair = {
  candidate: DuplicateTransaction;
  original: DuplicateTransaction;
  diff_fields: string[];
  exact_match: boolean;
};

type Props = {
  pairs: DuplicatePair[];
  busyAction: string | null;
  onResolve: (transactionId: number, action: DuplicateAction) => void;
  onResolveExact: () => void;
};

export function DuplicateReview({ pairs, busyAction, onResolve, onResolveExact }: Props) {
  const exactCount = pairs.filter((pair) => pair.exact_match).length;
  return (
    <section className="toolPanel duplicateReviewPanel" id="duplicate-review">
      <div className="panelTitle">
        <CopyCheck size={20} />
        <div><h3>Duplicate Review</h3><p>Compare a new import with the transaction already in your ledger.</p></div>
      </div>
      <div className="duplicateReviewSummary">
        <div><strong>{pairs.length} open pair{pairs.length === 1 ? "" : "s"}</strong><span>Differing fields are highlighted.</span></div>
        <button className="primaryButton" onClick={onResolveExact} disabled={exactCount === 0 || busyAction !== null}>Resolve all exact matches ({exactCount})</button>
      </div>
      <div className="duplicatePairList">
        {pairs.map((pair) => (
          <article className="duplicatePair" key={pair.candidate.id}>
            <div className="duplicatePairHeader">
              <div><strong>{pair.exact_match ? "Exact match" : `${pair.diff_fields.length} field${pair.diff_fields.length === 1 ? "" : "s"} differ`}</strong><span>{pair.exact_match ? "Removing the new copy is recommended." : "Choose which bank-sourced record should remain."}</span></div>
              <span className={pair.exact_match ? "statusBadge confirmed" : "statusBadge possible-duplicate"}>{pair.exact_match ? "Exact" : "Review"}</span>
            </div>
            <div className="transactionCompareGrid">
              <TransactionCompareCard title="Existing ledger transaction" transaction={pair.original} diffFields={pair.diff_fields} emphasis="original" />
              <TransactionCompareCard title="New imported copy" transaction={pair.candidate} diffFields={pair.diff_fields} />
            </div>
            <div className="duplicateActions">
              <button className={pair.exact_match ? "primaryButton" : "secondaryButton"} onClick={() => onResolve(pair.candidate.id, "remove_new")} disabled={busyAction !== null}>Remove new copy</button>
              <button className="secondaryButton" onClick={() => onResolve(pair.candidate.id, "keep_both")} disabled={busyAction !== null}>Keep both</button>
              <button className="secondaryButton" onClick={() => onResolve(pair.candidate.id, "replace_old")} disabled={busyAction !== null} title="Use the new date, amount, description, and reference while preserving your category, notes, labels, and splits.">Replace old bank details</button>
            </div>
          </article>
        ))}
        {pairs.length === 0 ? <p className="emptyText">No possible duplicates are waiting for review.</p> : null}
      </div>
    </section>
  );
}
