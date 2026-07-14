import { FileUp, ListChecks, Plus, RefreshCw } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { api } from "../../api/client";
import { ReconciliationBadge, type ReconciliationStatus } from "./ReconciliationBadge";
import { PaymentVerification, type PaymentVerificationStatus, type PaymentWarning } from "../transfers/PaymentVerification";
import { ManualTransactionForm, type ManualTransactionAccount, type ManualTransactionCategory } from "../transactions/ManualTransactionForm";

export type AccountPageSummary = {
  id: number;
  display_name: string;
  account_type: string;
  status: string;
  institution_name: string | null;
  last_four: string | null;
  sidebar_balance_kind: "running_balance" | "investment_snapshot" | "recent_activity";
};

type Props = {
  account: AccountPageSummary;
  balanceCents: number;
  missingCategoryCount: number;
  reconciliation: ReconciliationStatus | null;
  paymentVerification: PaymentVerificationStatus | null;
  csrf: string;
  transactionAccounts: ManualTransactionAccount[];
  transactionCategories: ManualTransactionCategory[];
  formatMoney: (cents: number) => string;
  accountGroupLabel: (value: string) => string;
  readableAccountType: (value: string) => string;
  onImport: () => void;
  onOpenReview: () => void;
  onRefresh: () => void;
  onViewUncategorized: () => void;
  onCheckpointSaved: (operationId: string) => Promise<void>;
  onManualTransactionSaved: (operationId: string) => Promise<void>;
  onCheckpointError: (message: string) => void;
  onInvestigateReconciliation: (status: ReconciliationStatus) => void;
  onInvestigatePayment: (warning: PaymentWarning) => void;
  children: ReactNode;
};

export function AccountPage(props: Props) {
  const [statementDate, setStatementDate] = useState("");
  const [statementBalance, setStatementBalance] = useState("");
  const [saving, setSaving] = useState(false);
  const [showManualTransaction, setShowManualTransaction] = useState(false);

  async function submitCheckpoint(event: FormEvent) {
    event.preventDefault();
    const numericBalance = Number(statementBalance.replace(/[$,\s]/g, ""));
    if (!statementDate || !Number.isFinite(numericBalance)) {
      props.onCheckpointError("Enter a statement date and valid ending balance.");
      return;
    }
    setSaving(true);
    try {
      const result = await api<{ operation_id: string }>(`/api/accounts/${props.account.id}/statement-checkpoints`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-csrf-token": props.csrf },
        body: JSON.stringify({ statement_date: statementDate, statement_balance_cents: Math.round(numericBalance * 100) }),
      });
      await props.onCheckpointSaved(result.operation_id);
      setStatementBalance("");
    } catch (error) {
      props.onCheckpointError(error instanceof Error ? error.message : "Statement balance could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  const latest = props.reconciliation?.latest;
  return (
    <div className="stickyAccountChrome">
      {props.missingCategoryCount > 0 ? (
        <div className="reviewNoticeBar">
          <span>{props.missingCategoryCount} new transaction{props.missingCategoryCount === 1 ? "" : "s"} to approve or categorize.</span>
          <button type="button" onClick={props.onViewUncategorized}>View</button>
        </div>
      ) : null}
      <header className="accountLedgerHeader">
        <div>
          <h1>{props.account.display_name}{props.account.last_four ? ` (${props.account.last_four})` : ""}</h1>
          <div className="accountMetaRow">
            <span>{props.accountGroupLabel(props.account.account_type)}</span>
            <span>{props.readableAccountType(props.account.account_type)}</span>
            <span>{props.account.institution_name ?? "Local account"}</span>
            <span>{props.account.status}</span>
          </div>
          <ReconciliationBadge status={props.reconciliation} formatMoney={props.formatMoney} />
        </div>
        <div className="accountBalanceRow">
          <div><strong className={props.balanceCents < 0 ? "amount negative" : "amount positive"}>{props.formatMoney(props.balanceCents)}</strong><span>{props.account.sidebar_balance_kind === "recent_activity" ? "Last 30 days" : "Current balance"}</span></div>
          <div><strong>{props.missingCategoryCount}</strong><span>Need category</span></div>
        </div>
        <div className="accountActionBar">
          <button className="secondaryButton compactButton" onClick={() => setShowManualTransaction((current) => !current)}><Plus size={14} />Add transaction</button>
          <button className="primaryButton compactButton" onClick={props.onImport}><FileUp size={14} />File Import</button>
          <button className="secondaryButton compactButton" onClick={props.onOpenReview}><ListChecks size={14} />Open Review</button>
          <button className="ghostButton compactIconButton" title="Refresh data" onClick={props.onRefresh}><RefreshCw size={14} /></button>
        </div>
      </header>
      {showManualTransaction ? <ManualTransactionForm accounts={props.transactionAccounts} categories={props.transactionCategories} csrf={props.csrf} defaultAccountId={props.account.id} onSaved={props.onManualTransactionSaved} onError={props.onCheckpointError} onCancel={() => setShowManualTransaction(false)} /> : null}
      <div className="accountVerificationGrid">
        <form className="statementCheckpointForm" onSubmit={submitCheckpoint}>
          <div><strong>Statement balance</strong><span>Add the ending balance from a bank statement to verify the ledger.</span></div>
          <input type="date" aria-label="Statement date" value={statementDate} onChange={(event) => setStatementDate(event.target.value)} required />
          <input type="text" inputMode="decimal" aria-label="Statement balance" placeholder="Balance" value={statementBalance} onChange={(event) => setStatementBalance(event.target.value)} required />
          <button className="secondaryButton compactButton" disabled={saving}>{saving ? "Saving..." : "Save"}</button>
          {latest && !latest.reconciled ? <button type="button" className="ghostButton compactButton" onClick={() => props.onInvestigateReconciliation(props.reconciliation!)}>Investigate difference</button> : null}
        </form>
        <PaymentVerification status={props.paymentVerification} formatMoney={props.formatMoney} onInvestigate={props.onInvestigatePayment} />
      </div>
      {props.children}
    </div>
  );
}
