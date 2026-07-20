import { useMemo, useState } from "react";
import { FileText } from "lucide-react";

import type { InboxBatch, StatementBalancePreview } from "./ImportReview";
import { PdfRegionTeacher } from "./PdfRegionTeacher";

type Props = {
  batch: InboxBatch;
  csrf: string;
  preview: StatementBalancePreview;
  busy: boolean;
  onConfirm: (batch: InboxBatch, selection: { statement_date: string; balance_cents: number; candidate_index: number | null }) => Promise<void>;
  onDiscard: (batch: InboxBatch) => void;
};

export function StatementBalanceReview({ batch, preview, csrf, busy, onConfirm, onDiscard }: Props) {
  const initialBalance = preview.selected_balance_cents === null || preview.selected_balance_cents === undefined
    ? ""
    : (preview.selected_balance_cents / 100).toFixed(2);
  const [statementDate, setStatementDate] = useState(preview.statement_date ?? "");
  const [balance, setBalance] = useState(initialBalance);
  const [candidateIndex, setCandidateIndex] = useState<number | null>(preview.selected_index ?? null);
  const [teacherOpen, setTeacherOpen] = useState(false);
  const [teacherMessage, setTeacherMessage] = useState("");
  const balanceCents = useMemo(() => parseMoneyToCents(balance), [balance]);
  const canConfirm = Boolean(statementDate && balanceCents !== null);

  function chooseCandidate(index: number) {
    const candidate = preview.candidates[index];
    if (!candidate) return;
    setCandidateIndex(index);
    setBalance((candidate.balance_cents / 100).toFixed(2));
  }

  return (
    <article className="pendingInboxCard statementBalanceCard">
      <div className="pendingInboxTitle">
        <div>
          <strong><FileText size={16} />{batch.filename}</strong>
          <span><span className="fileTypeBadge">PDF</span> Balance preview · no transaction tables will be imported</span>
        </div>
        <span className={`statusBadge ${preview.confidence === "high" ? "confirmed" : "suggested"}`}>
          {preview.confidence === "high" ? "Ready to confirm" : "Needs your choice"}
        </span>
      </div>
      <div className="matchedAccountCard">
        <div>
          <strong>{batch.account_name}{batch.account_last_four && !batch.account_name.endsWith(batch.account_last_four) ? ` (${batch.account_last_four})` : ""}</strong>
          <span>{preview.institution ? `${preview.institution} · ` : ""}{batch.match_reason ?? "Matched to this account."}</span>
        </div>
      </div>
      {preview.candidates.length > 1 ? (
        <fieldset className="statementCandidates">
          <legend>Choose the ending balance shown on the statement</legend>
          {preview.candidates.map((candidate, index) => (
            <label key={`${candidate.label}-${candidate.balance_cents}-${index}`}>
              <input type="radio" checked={candidateIndex === index} onChange={() => chooseCandidate(index)} />
              <span><strong>{candidate.label}</strong>{candidate.context}</span>
              <strong>{formatCents(candidate.balance_cents)}</strong>
            </label>
          ))}
        </fieldset>
      ) : null}
      <div className="statementBalanceFields">
        <label>Statement date<input type="date" value={statementDate} onChange={(event) => setStatementDate(event.target.value)} /></label>
        <label>Ending balance<input type="text" inputMode="decimal" placeholder="0.00" value={balance} onChange={(event) => { setBalance(event.target.value); setCandidateIndex(null); }} /></label>
      </div>
      {preview.warnings.length > 0 ? <small>{preview.warnings.join(" ")}</small> : null}
      {preview.template_extracted ? <small className="templateTrustStatus">Saved template used via {preview.template_status === "anchored" ? "its text anchor" : "the fallback region"}. {preview.template_confirmations ?? 0} clean confirmation{preview.template_confirmations === 1 ? "" : "s"}.</small> : null}
      {teacherMessage ? <small className="successText">{teacherMessage}</small> : null}
      <div className="buttonRow">
        <button
          className="primaryButton"
          disabled={busy || !canConfirm}
          onClick={() => balanceCents !== null && void onConfirm(batch, { statement_date: statementDate, balance_cents: balanceCents, candidate_index: candidateIndex })}
        >
          Confirm anchor
        </button>
        <button className="secondaryButton" onClick={() => setTeacherOpen(true)} disabled={busy}>Teach the extractor</button>
        <button className="secondaryButton" onClick={() => onDiscard(batch)} disabled={busy}>Discard preview</button>
      </div>
      <small>The PDF itself is not added to the ledger. Confirmation saves only this date and balance as an undoable anchor.</small>
      {teacherOpen ? <PdfRegionTeacher batchId={batch.id} csrf={csrf} onSaved={setTeacherMessage} onClose={() => setTeacherOpen(false)} /> : null}
    </article>
  );
}

function parseMoneyToCents(value: string): number | null {
  const cleaned = value.replaceAll(",", "").replace("$", "").trim();
  if (!cleaned || !/^-?\d+(?:\.\d{0,2})?$/.test(cleaned)) return null;
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? Math.round(parsed * 100) : null;
}

function formatCents(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}
