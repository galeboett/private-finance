import { Landmark, RefreshCw } from "lucide-react";

export type ImportSignProfile = {
  id: number;
  account_id: number;
  preset_type: string | null;
  sign_convention: "canonical_as_detected" | "reverse_detected";
  decided_by: "user" | "auto_detected";
  sample_note: string | null;
  updated_at: string;
};

export type SignDecision = {
  applied_sign_convention: "preset" | "reverse";
  using_saved_profile: boolean;
  profile: ImportSignProfile | null;
  heuristic: {
    status: "consistent" | "contradicts_detected" | "mixed" | "insufficient_data";
    rule: string | null;
    sample_size: number;
    expected_ratio?: number;
    recommended_sign_convention: "preset" | "reverse" | null;
    examples: Array<{ transaction_date?: string; description?: string; amount?: string }>;
  };
  requires_confirmation: boolean;
};

export type InboxBatch = {
  id: number;
  filename: string;
  preset_type: string | null;
  sign_convention: "preset" | "reverse";
  account_id: number;
  account_name: string;
  account_last_four: string | null;
  match_confidence: number;
  match_reason: string | null;
  row_count: number;
  warnings: string[];
  preview: Array<Record<string, string | number | null>>;
  created_at: string;
  sign_decision: SignDecision | null;
};

export type ImportInboxState = { folder: string; pending: InboxBatch[] };
export type ImportInboxScan = ImportInboxState & {
  files_found: number;
  staged: Array<{ batch_id: number; filename: string; account_id: number; row_count: number }>;
  skipped: Array<{ filename: string; reason: string }>;
  needs_account: Array<{ filename: string; preset_type: string; reason: string; proposed_account: Record<string, string | null> }>;
  errors: Array<{ filename: string; message: string }>;
};

type Props = {
  inbox: ImportInboxState;
  lastScan: ImportInboxScan | null;
  busyAction: string | null;
  onScan: () => void;
  onConfirm: (batch: InboxBatch) => void;
  onDiscard: (batch: InboxBatch) => void;
};

export function ImportReview({ inbox, lastScan, busyAction, onScan, onConfirm, onDiscard }: Props) {
  return (
    <div className="importInboxPanel">
      <div className="importInboxHeader">
        <div>
          <strong>Import Inbox</strong>
          <span>Copy statement CSVs into this private local folder, then scan when you want the app to look for files.</span>
          <code>{inbox.folder || "The inbox folder will be created when the backend starts."}</code>
        </div>
        <button className="primaryButton" onClick={onScan} disabled={busyAction !== null}>
          <RefreshCw size={16} />
          {busyAction === "inbox-scan" ? "Scanning…" : "Scan inbox"}
        </button>
      </div>
      <small>Files stay in place, and fingerprints prevent accidental re-imports. For generic names, use one account subfolder and include its last four digits.</small>
      {lastScan && (lastScan.needs_account.length > 0 || lastScan.errors.length > 0) ? (
        <div className="inboxScanIssues">
          {lastScan.needs_account.map((item) => <div key={`account-${item.filename}`}><strong>{item.filename}</strong><span>Needs an account match: {item.reason} Use Smart import below to analyze it manually.</span></div>)}
          {lastScan.errors.map((item) => <div key={`error-${item.filename}`}><strong>{item.filename}</strong><span>{item.message}</span></div>)}
        </div>
      ) : null}
      {inbox.pending.length > 0 ? (
        <div className="pendingInboxList">
          {inbox.pending.map((batch) => (
            <article className="pendingInboxCard" key={batch.id}>
              <div className="pendingInboxTitle">
                <div><strong>{batch.filename}</strong><span>{batch.preset_type ?? "Detected CSV"} · {batch.row_count} rows</span></div>
                <span className="statusBadge suggested">{batch.match_confidence}% match</span>
              </div>
              <div className="matchedAccountCard">
                <Landmark size={16} />
                <div><strong>{batch.account_name}{batch.account_last_four && !batch.account_name.endsWith(batch.account_last_four) ? ` (${batch.account_last_four})` : ""}</strong><span>{batch.match_reason ?? "Matched from the file name and contents."}</span></div>
              </div>
              {batch.sign_decision?.using_saved_profile ? <small>Using your saved sign convention. Amounts are interpreted as {batch.sign_convention === "reverse" ? "reversed from" : "matching"} this source.</small> : null}
              {batch.preview.length > 0 ? (
                <div className="inboxPreviewRows">
                  {batch.preview.slice(0, 3).map((row, index) => <div key={`${batch.id}-${index}`}><span>{String(row.transaction_date ?? row.snapshot_date ?? `Row ${index + 1}`)}</span><strong>{String(row.raw_description ?? row.description ?? row.symbol ?? row.account_name ?? "Imported row")}</strong><span>{String(row.amount ?? row.market_value ?? "")}{row.interpreted_transaction_type ? ` · ${String(row.interpreted_transaction_type).replaceAll("_", " ")}` : ""}</span></div>)}
                </div>
              ) : null}
              {batch.warnings.length > 0 ? <small>{batch.warnings.join(" ")}</small> : null}
              <div className="buttonRow">
                <button className="primaryButton" onClick={() => onConfirm(batch)} disabled={busyAction !== null}>Confirm import</button>
                <button className="secondaryButton" onClick={() => onDiscard(batch)} disabled={busyAction !== null}>Discard batch</button>
              </div>
            </article>
          ))}
        </div>
      ) : <p className="emptyText">No files are waiting for confirmation.</p>}
    </div>
  );
}
