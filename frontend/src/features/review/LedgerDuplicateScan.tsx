import { RefreshCw, ScanSearch } from "lucide-react";
import { useEffect, useState } from "react";

import { useApiClient } from "../../api/hooks";
import { useSelection } from "../../lib/useSelection";
import { DuplicateBulkConfirm, type DuplicateBulkPreview, type DuplicateBulkStrategy } from "./DuplicateBulkConfirm";
import { DuplicateReview, type DuplicateAction, type DuplicatePair } from "./DuplicateReview";
import { DuplicateSelectionBulkConfirm, type DuplicateSelectionAction, type DuplicateSelectionPreview } from "./DuplicateSelectionBulkConfirm";
import { HistoricalRefundBulkConfirm, type HistoricalRefundBulkPreview } from "./HistoricalRefundBulkConfirm";

export type { DuplicatePair } from "./DuplicateReview";

type Tier = "exact" | "cross_source" | "probable" | "mirrored" | "import";
type QueueSummary = { total: number; counts: Record<Tier, number>; safe_reimports: number; historical_refunds: number };
type ScanSummary = { flagged: number; cleared_reviewed: number; counts: Record<"exact" | "cross_source" | "probable" | "mirrored", number>; limit: number; limited: boolean; operation_id?: string; queue: QueueSummary };
type Props = {
  pairs: DuplicatePair[];
  csrf: string;
  onChanged: (message: string, operationId?: string) => Promise<void>;
  onError: (message: string) => void;
  onRerunTransfers: () => Promise<void>;
};

export function LedgerDuplicateScan({ pairs, csrf, onChanged, onError, onRerunTransfers }: Props) {
  const api = useApiClient();
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [summary, setSummary] = useState<ScanSummary | null>(null);
  const [queueSummary, setQueueSummary] = useState<QueueSummary | null>(null);
  const [pagePairs, setPagePairs] = useState<DuplicatePair[]>(pairs);
  const [tierFilter, setTierFilter] = useState<Tier | "all">("all");
  const [offset, setOffset] = useState(0);
  const [suggestTransferRerun, setSuggestTransferRerun] = useState(false);
  const [bulkPreview, setBulkPreview] = useState<DuplicateBulkPreview | null>(null);
  const [historicalRefundPreview, setHistoricalRefundPreview] = useState<HistoricalRefundBulkPreview | null>(null);
  const [selectionPreview, setSelectionPreview] = useState<DuplicateSelectionPreview | null>(null);
  const { selectedIds: selectedCandidateIds, setSelectedIds: setSelectedCandidateIds, toggle: toggleCandidateSelection, resetAnchor: resetCandidateSelectionAnchor } = useSelection();

  useEffect(() => {
    if (tierFilter === "all" && offset === 0) setPagePairs(pairs);
  }, [pairs, tierFilter, offset]);

  useEffect(() => {
    api<QueueSummary>("/api/duplicates/summary").then(setQueueSummary).catch(() => undefined);
  }, []);

  async function loadPage(nextOffset = offset, nextTier = tierFilter) {
    const query = new URLSearchParams({ limit: "25", offset: String(nextOffset) });
    if (nextTier !== "all") query.set("tier", nextTier);
    const [nextPairs, nextSummary] = await Promise.all([
      api<DuplicatePair[]>(`/api/duplicates/pending?${query.toString()}`),
      api<QueueSummary>("/api/duplicates/summary"),
    ]);
    setPagePairs(nextPairs);
    setQueueSummary(nextSummary);
    setOffset(nextOffset);
    setSelectedCandidateIds([]);
    resetCandidateSelectionAnchor();
  }

  async function scan() {
    setBusyAction("scan");
    try {
      const result = await api<ScanSummary>("/api/duplicates/scan", { method: "POST", headers: { "x-csrf-token": csrf } });
      setSummary(result);
      setQueueSummary(result.queue);
      const foundMessage = result.flagged ? `Found ${result.flagged} new ledger duplicate pair${result.flagged === 1 ? "" : "s"}.` : "No new ledger duplicates found.";
      const reviewedMessage = result.cleared_reviewed ? ` Cleared ${result.cleared_reviewed} pair${result.cleared_reviewed === 1 ? "" : "s"} already covered by your Keep both decisions.` : "";
      await onChanged(`${foundMessage}${reviewedMessage}`, result.operation_id);
      await loadPage(0, tierFilter);
    } catch (error) {
      onError(error instanceof Error ? error.message : "The ledger duplicate scan failed.");
    } finally {
      setBusyAction(null);
    }
  }

  async function resolve(transactionId: number, action: DuplicateAction) {
    setBusyAction(`resolve-${transactionId}`);
    try {
      const result = await api<{ operation_id: string; affected_card_account: boolean }>(`/api/duplicates/${transactionId}/resolve`, { method: "POST", headers: { "x-csrf-token": csrf }, body: JSON.stringify({ action }) });
      const message = action === "remove_new" ? "Removed the new duplicate copy." : action === "keep_both" ? "Kept both transactions and remembered this decision." : action === "remove_sign_artifact" ? "Removed the positive mirrored-sign artifact." : "Updated the original with the newer bank details and preserved your annotations.";
      if (result.affected_card_account) setSuggestTransferRerun(true);
      await onChanged(message, result.operation_id);
      await loadPage(Math.max(0, offset - (pagePairs.length === 1 && offset > 0 ? 25 : 0)), tierFilter);
    } catch (error) {
      onError(error instanceof Error ? error.message : "The duplicate could not be resolved.");
    } finally {
      setBusyAction(null);
    }
  }

  async function openBulkPreview(strategy: DuplicateBulkStrategy) {
    setBusyAction("preview-safe");
    try {
      const preview = await api<DuplicateBulkPreview>(`/api/duplicates/bulk-preview?strategy=${strategy}`);
      setBulkPreview(preview);
    } catch (error) {
      onError(error instanceof Error ? error.message : "The bulk duplicate preview could not be loaded.");
    } finally {
      setBusyAction(null);
    }
  }

  async function confirmBulk() {
    if (!bulkPreview) return;
    setBusyAction("resolve-safe");
    try {
      const result = await api<{ resolved: number; updated: number; operation_id: string | null; affected_card_account: boolean }>("/api/duplicates/resolve-safe", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ strategy: bulkPreview.strategy, preview_token: bulkPreview.selection_token }),
      });
      if (result.affected_card_account) setSuggestTransferRerun(true);
      const message = bulkPreview.strategy === "keep_existing"
        ? `Kept the existing ledger data and removed ${result.resolved} safe reimport${result.resolved === 1 ? "" : "s"}.`
        : `Used newer import data for ${result.updated} transaction${result.updated === 1 ? "" : "s"} and removed ${result.resolved} redundant row${result.resolved === 1 ? "" : "s"}.`;
      setBulkPreview(null);
      await onChanged(message, result.operation_id ?? undefined);
      await loadPage(0, tierFilter);
    } catch (error) {
      setBulkPreview(null);
      onError(error instanceof Error ? error.message : "Safe duplicate reimports could not be resolved.");
      await loadPage(0, tierFilter).catch(() => undefined);
    } finally {
      setBusyAction(null);
    }
  }

  async function openHistoricalRefundPreview() {
    setBusyAction("preview-historical-refunds");
    try {
      setHistoricalRefundPreview(await api<HistoricalRefundBulkPreview>("/api/duplicates/historical-refunds-preview"));
    } catch (error) {
      onError(error instanceof Error ? error.message : "The historical refund preview could not be loaded.");
    } finally {
      setBusyAction(null);
    }
  }

  async function confirmHistoricalRefunds() {
    if (!historicalRefundPreview) return;
    setBusyAction("link-historical-refunds");
    try {
      const result = await api<{ linked: number; operation_id: string | null }>("/api/duplicates/link-historical-refunds", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ preview_token: historicalRefundPreview.selection_token }),
      });
      setHistoricalRefundPreview(null);
      await onChanged(`Linked ${result.linked} intentional historical refund pair${result.linked === 1 ? "" : "s"}.`, result.operation_id ?? undefined);
      await loadPage(0, tierFilter);
    } catch (error) {
      setHistoricalRefundPreview(null);
      onError(error instanceof Error ? error.message : "The historical refunds could not be linked.");
      await loadPage(0, tierFilter).catch(() => undefined);
    } finally {
      setBusyAction(null);
    }
  }

  async function openSelectionPreview(action: DuplicateSelectionAction, authoritativeBatchId?: number) {
    if (!selectedCandidateIds.length) return;
    setBusyAction("preview-selection");
    try {
      const preview = await api<DuplicateSelectionPreview>("/api/duplicates/selection-preview", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ transaction_ids: selectedCandidateIds, action, authoritative_batch_id: authoritativeBatchId }),
      });
      setSelectionPreview(preview);
    } catch (error) {
      onError(error instanceof Error ? error.message : "The selected duplicate preview could not be loaded.");
    } finally {
      setBusyAction(null);
    }
  }

  async function confirmSelection() {
    if (!selectionPreview) return;
    setBusyAction("resolve-selection");
    try {
      const result = await api<{ resolved: number; operation_id: string; affected_card_account: boolean }>("/api/duplicates/resolve-selection", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ transaction_ids: selectionPreview.transaction_ids, action: selectionPreview.action, authoritative_batch_id: selectionPreview.authoritative_batch_id, preview_token: selectionPreview.selection_token }),
      });
      if (result.affected_card_account) setSuggestTransferRerun(true);
      const message = selectionPreview.action === "keep_both"
        ? `Kept both transactions in ${result.resolved} selected pair${result.resolved === 1 ? "" : "s"}.`
        : selectionPreview.action === "prefer_authoritative_history"
          ? `Applied authoritative history data to ${result.resolved} selected pair${result.resolved === 1 ? "" : "s"} and preserved the established records.`
          : `Removed the new copy from ${result.resolved} selected exact pair${result.resolved === 1 ? "" : "s"}.`;
      setSelectionPreview(null);
      setSelectedCandidateIds([]);
      resetCandidateSelectionAnchor();
      await onChanged(message, result.operation_id);
      await loadPage(0, tierFilter);
    } catch (error) {
      setSelectionPreview(null);
      onError(error instanceof Error ? error.message : "The selected duplicate action could not be completed.");
      await loadPage(0, tierFilter).catch(() => undefined);
    } finally {
      setBusyAction(null);
    }
  }

  const counts: QueueSummary["counts"] = queueSummary?.counts ?? (summary ? { ...summary.counts, import: 0 } : { exact: 0, cross_source: 0, probable: 0, mirrored: 0, import: 0 });
  const filteredTotal = tierFilter === "all" ? queueSummary?.total ?? pagePairs.length : counts[tierFilter];
  return <>
    <section className="toolPanel ledgerDuplicateScan">
      <div><ScanSearch size={19} /><div><strong>Scan the full ledger</strong><span>Find older and cross-source duplicates that import-time review could not see.</span></div></div>
      <div className="duplicateTierCounts"><span>{counts.cross_source} cross-source</span><span>{counts.exact} exact</span><span>{counts.probable} probable</span><span>{counts.mirrored} mirrored-sign</span></div>
      <div className="duplicateQueueControls">
        <label>Show<select value={tierFilter} onChange={(event) => { const next = event.target.value as Tier | "all"; setTierFilter(next); void loadPage(0, next); }}><option value="all">All types</option><option value="cross_source">Cross-source</option><option value="exact">Exact</option><option value="probable">Probable</option><option value="mirrored">Opposite-sign</option><option value="import">Import-time</option></select></label>
        <span>{filteredTotal ? offset + 1 : 0}–{Math.min(offset + pagePairs.length, filteredTotal)} of {filteredTotal}</span>
        <button className="ghostButton compactButton" disabled={offset === 0 || busyAction !== null} onClick={() => void loadPage(Math.max(0, offset - 25))}>Previous</button>
        <button className="ghostButton compactButton" disabled={offset + 25 >= filteredTotal || busyAction !== null} onClick={() => void loadPage(offset + 25)}>Next</button>
      </div>
      <button className="primaryButton" onClick={() => void scan()} disabled={busyAction !== null}><ScanSearch size={15} />{busyAction === "scan" ? "Scanning…" : "Scan ledger for duplicates"}</button>
      {summary?.limited ? <small>Showing the first {summary.limit} non-overlapping pairs. Resolve some, then scan again.</small> : null}
      {suggestTransferRerun ? <div className="duplicateTransferPrompt"><span>Card duplicates changed. Re-run transfer matching so the surviving payment can link correctly.</span><button className="secondaryButton compactButton" onClick={() => { setSuggestTransferRerun(false); void onRerunTransfers(); }}><RefreshCw size={13} />Re-run transfer matching</button></div> : null}
    </section>
    <DuplicateReview pairs={pagePairs} totalCount={filteredTotal} safeReimportCount={queueSummary?.safe_reimports ?? 0} historicalRefundCount={queueSummary?.historical_refunds ?? 0} selectedCandidateIds={selectedCandidateIds} busyAction={busyAction} onResolve={(transactionId, action) => void resolve(transactionId, action)} onBulkPreview={(strategy) => void openBulkPreview(strategy)} onHistoricalRefundPreview={() => void openHistoricalRefundPreview()} onToggleSelected={toggleCandidateSelection} onSelectPage={(ids) => { setSelectedCandidateIds(ids); resetCandidateSelectionAnchor(); }} onClearSelected={() => { setSelectedCandidateIds([]); resetCandidateSelectionAnchor(); }} onSelectionPreview={(action, batchId) => void openSelectionPreview(action, batchId)} />
    {bulkPreview ? <DuplicateBulkConfirm preview={bulkPreview} busy={busyAction === "resolve-safe"} onClose={() => setBulkPreview(null)} onConfirm={() => void confirmBulk()} /> : null}
    {historicalRefundPreview ? <HistoricalRefundBulkConfirm preview={historicalRefundPreview} busy={busyAction === "link-historical-refunds"} onClose={() => setHistoricalRefundPreview(null)} onConfirm={() => void confirmHistoricalRefunds()} /> : null}
    {selectionPreview ? <DuplicateSelectionBulkConfirm preview={selectionPreview} busy={busyAction === "resolve-selection"} onClose={() => setSelectionPreview(null)} onConfirm={() => void confirmSelection()} /> : null}
  </>;
}
