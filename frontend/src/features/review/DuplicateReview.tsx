import { CopyCheck } from "lucide-react";
import { useState } from "react";

import type { DuplicateBulkStrategy } from "./DuplicateBulkConfirm";
import type { DuplicateSelectionAction } from "./DuplicateSelectionBulkConfirm";
import { TransactionCompareCard, type DuplicateTransaction } from "./TransactionCompareCard";

export type DuplicateAction = "remove_new" | "keep_both" | "replace_old" | "remove_sign_artifact";
export type DuplicatePair = {
  candidate: DuplicateTransaction;
  original: DuplicateTransaction;
  diff_fields: string[];
  exact_match: boolean;
  safe_reimport: boolean;
  tier: "exact" | "cross_source" | "probable" | "mirrored" | "import";
  similarity: number;
};

type Props = {
  pairs: DuplicatePair[];
  busyAction: string | null;
  onResolve: (transactionId: number, action: DuplicateAction) => void;
  onBulkPreview: (strategy: DuplicateBulkStrategy) => void;
  totalCount: number;
  safeReimportCount: number;
  historicalRefundCount: number;
  selectedCandidateIds: number[];
  onToggleSelected: (candidateId: number, visibleIds: number[], shiftKey: boolean) => void;
  onSelectPage: (candidateIds: number[]) => void;
  onClearSelected: () => void;
  onSelectionPreview: (action: DuplicateSelectionAction, authoritativeBatchId?: number) => void;
  onHistoricalRefundPreview: () => void;
};

export function DuplicateReview({ pairs, busyAction, onResolve, onBulkPreview, totalCount, safeReimportCount, historicalRefundCount, selectedCandidateIds, onToggleSelected, onSelectPage, onClearSelected, onSelectionPreview, onHistoricalRefundPreview }: Props) {
  const [authoritativeBatchId, setAuthoritativeBatchId] = useState<number | null>(null);
  const selectablePairs = pairs.filter((pair) => pair.tier === "exact" || pair.tier === "probable");
  const selectableIds = selectablePairs.map((pair) => pair.candidate.id);
  const selectedPairs = selectablePairs.filter((pair) => selectedCandidateIds.includes(pair.candidate.id));
  const authoritativeBatches = Array.from(new Map(
    selectablePairs
      .filter((pair) => pair.candidate.import_batch_id !== null)
      .map((pair) => [pair.candidate.import_batch_id!, pair.candidate.import_source])
  ).entries());
  const selectedCanPreferHistory = selectedPairs.length === selectedCandidateIds.length && selectedPairs.length > 0 && selectedPairs.every((pair) =>
    pair.original.import_source === "Manual entry" && pair.candidate.import_batch_id === authoritativeBatchId
  );
  const allPageSelected = selectableIds.length > 0 && selectableIds.every((id) => selectedCandidateIds.includes(id));
  return (
    <section className="toolPanel duplicateReviewPanel" id="duplicate-review">
      <div className="panelTitle">
        <CopyCheck size={20} />
        <div><h3>Duplicate Review</h3><p>Compare a new import with the transaction already in your ledger.</p></div>
      </div>
      <div className="duplicateReviewSummary">
        <div><strong>{totalCount} open pair{totalCount === 1 ? "" : "s"}</strong><span>Showing {pairs.length} on this page. Differing fields are highlighted.</span></div>
        <div className="duplicateBulkButtons">
          <button className="primaryButton" onClick={onHistoricalRefundPreview} disabled={historicalRefundCount === 0 || busyAction !== null}>Link historical refunds ({historicalRefundCount})</button>
          <button className="primaryButton" onClick={() => onBulkPreview("keep_existing")} disabled={safeReimportCount === 0 || busyAction !== null}>Keep existing ({safeReimportCount})</button>
          <button className="secondaryButton" onClick={() => onBulkPreview("use_new_import")} disabled={safeReimportCount === 0 || busyAction !== null}>Use new imports ({safeReimportCount})</button>
        </div>
      </div>
      {selectableIds.length > 0 ? <div className="duplicateSelectionBar">
        <button className="ghostButton compactButton" onClick={() => allPageSelected ? onClearSelected() : onSelectPage(selectableIds)} disabled={busyAction !== null}>{allPageSelected ? "Clear selection" : `Select exact/probable on page (${selectableIds.length})`}</button>
        <span>{selectedCandidateIds.length} selected</span>
        <button className="secondaryButton compactButton" onClick={() => onSelectionPreview("keep_both")} disabled={selectedCandidateIds.length === 0 || busyAction !== null}>Keep both selected</button>
        <label className="duplicateAuthoritativePicker">
          <span>Source of record</span>
          <select value={authoritativeBatchId ?? ""} onChange={(event) => setAuthoritativeBatchId(event.target.value ? Number(event.target.value) : null)} disabled={busyAction !== null}>
            <option value="">Choose import batch</option>
            {authoritativeBatches.map(([batchId, filename]) => <option key={batchId} value={batchId}>{filename} (batch {batchId})</option>)}
          </select>
        </label>
        <button className="primaryButton compactButton" title={selectedCanPreferHistory ? "Use the chosen batch as the source of record while preserving established transaction annotations and links." : "Available when every selected pair has Manual entry on the established side and belongs to the chosen imported batch."} onClick={() => onSelectionPreview("prefer_authoritative_history", authoritativeBatchId!)} disabled={!selectedCanPreferHistory || busyAction !== null}>Prefer chosen source</button>
        <button className="primaryButton compactButton" title="Move the selected new copies to Trash, including probable matches." onClick={() => onSelectionPreview("remove_new")} disabled={selectedCandidateIds.length === 0 || busyAction !== null}>Remove selected new copies</button>
      </div> : null}
      <div className="duplicatePairList">
        {(["cross_source", "exact", "probable", "mirrored", "import"] as const).map((tier) => {
          const tierPairs = pairs.filter((pair) => pair.tier === tier);
          if (!tierPairs.length) return null;
          const tierLabel = tier === "cross_source" ? "Cross-source overlaps" : tier === "mirrored" ? "Mirrored-sign artifacts" : tier === "probable" ? "Probable matches" : tier === "exact" ? "Exact matches" : "Import-time matches";
          return <section className="duplicateTierGroup" key={tier}><h4>{tierLabel} <span>{tierPairs.length}</span></h4>{tierPairs.map((pair) => (
          <article className="duplicatePair" key={pair.candidate.id}>
            <div className="duplicatePairHeader">
              <div>{pair.tier === "exact" || pair.tier === "probable" ? <label className="duplicatePairSelect"><input type="checkbox" checked={selectedCandidateIds.includes(pair.candidate.id)} onChange={(event) => onToggleSelected(pair.candidate.id, selectableIds, (event.nativeEvent as MouseEvent).shiftKey)} disabled={busyAction !== null} title="Select duplicate pair. Hold Shift to select a range." /><span>Select for bulk action</span></label> : null}<strong>{pair.tier === "mirrored" ? "Opposite-sign pair" : pair.exact_match ? "Exact transaction facts" : `${pair.diff_fields.length} field${pair.diff_fields.length === 1 ? "" : "s"} differ`}</strong><span>{pair.tier === "mirrored" ? "This may be an import sign error, but it can also be a real refund or reversal. Verify that no money was returned before removing the positive row." : pair.tier === "cross_source" ? "The same transaction appears in categorized history and a bank import." : pair.safe_reimport ? "The source reference also matches, so this is eligible for safe bulk removal." : pair.exact_match ? "The facts match, but repeated same-day purchases are possible. Review before removing." : `Description similarity ${Math.round(pair.similarity * 100)}%. Review before removing either row.`}</span></div>
              <span className={pair.exact_match ? "statusBadge confirmed" : "statusBadge possible-duplicate"}>{pair.tier.replace("_", " ")}</span>
            </div>
            <div className="transactionCompareGrid">
              <TransactionCompareCard title="Existing ledger transaction" transaction={pair.original} diffFields={pair.diff_fields} emphasis="original" />
              <TransactionCompareCard title="New imported copy" transaction={pair.candidate} diffFields={pair.diff_fields} />
            </div>
            <div className="duplicateActions">
              {pair.tier === "mirrored" ? <button className="primaryButton" title="Soft-delete the positive refund-typed row and keep the negative expense row. Undo is available in Activity." onClick={() => onResolve(pair.candidate.id, "remove_sign_artifact")} disabled={busyAction !== null}>Remove positive copy</button> : <button className={pair.safe_reimport ? "primaryButton" : "secondaryButton"} onClick={() => onResolve(pair.candidate.id, "remove_new")} disabled={busyAction !== null}>Remove new copy</button>}
              <button className="secondaryButton" onClick={() => onResolve(pair.candidate.id, "keep_both")} disabled={busyAction !== null}>Keep both</button>
              {pair.tier !== "mirrored" ? <button className="secondaryButton" onClick={() => onResolve(pair.candidate.id, "replace_old")} disabled={busyAction !== null} title="Use the new date, amount, description, and reference while preserving your category, notes, labels, and splits.">Replace old bank details</button> : null}
            </div>
          </article>
          ))}</section>;
        })}
        {pairs.length === 0 ? <p className="emptyText">No possible duplicates are waiting for review.</p> : null}
      </div>
    </section>
  );
}
