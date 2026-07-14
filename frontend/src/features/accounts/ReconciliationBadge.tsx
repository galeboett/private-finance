import { AlertTriangle, CheckCircle2, MinusCircle } from "lucide-react";

export type ReconciliationCheckpoint = {
  checkpoint_id: number;
  statement_date: string;
  statement_balance_cents: number;
  computed_balance_cents: number;
  delta_cents: number;
  reconciled: boolean;
  source: "import" | "manual";
  investigate_from: string;
  investigate_to: string;
};

export type ReconciliationStatus = {
  account_id: number;
  account_name: string;
  account_type: string;
  latest: ReconciliationCheckpoint | null;
  reconciled_through: string | null;
  checkpoint_count: number;
};

export function ReconciliationBadge({ status, formatMoney }: { status: ReconciliationStatus | null; formatMoney: (cents: number) => string }) {
  if (!status?.latest) {
    return <span className="reconciliationBadge neutral"><MinusCircle size={14} />No statement balance</span>;
  }
  if (status.latest.reconciled) {
    return <span className="reconciliationBadge reconciled"><CheckCircle2 size={14} />Reconciled through {status.latest.statement_date}</span>;
  }
  return <span className="reconciliationBadge warning"><AlertTriangle size={14} />Off by {formatMoney(Math.abs(status.latest.delta_cents))}</span>;
}
