import { FileUp, ListChecks, Plus, RefreshCw } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { api } from "../../api/client";
import { ReconciliationBadge, type ReconciliationStatus } from "./ReconciliationBadge";
import { PaymentVerification, type PaymentVerificationStatus, type PaymentWarning } from "../transfers/PaymentVerification";
import { ManualTransactionForm, type ManualTransactionAccount, type ManualTransactionCategory } from "../transactions/ManualTransactionForm";
import type { ExternalAccountOption } from "./ExternalPaymentAction";

export type AccountPageSummary = {
  id: number;
  display_name: string;
  account_type: string;
  status: string;
  institution_name: string | null;
  last_four: string | null;
  net_worth_inclusion: "auto" | "always" | "never";
  is_anchored: boolean;
  sidebar_balance_cents: number | null;
  sidebar_balance_kind: "running_balance" | "investment_snapshot" | "anchored_balance" | "recent_activity" | "unanchored" | "excluded";
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
  externalAccounts: ExternalAccountOption[];
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
  onPaymentDismissed: (operationId?: string) => Promise<void>;
  onAccountChanged: (operationId: string, message: string) => Promise<void>;
  children: ReactNode;
};

export function AccountPage(props: Props) {
  const [statementDate, setStatementDate] = useState("");
  const [statementBalance, setStatementBalance] = useState("");
  const [saving, setSaving] = useState(false);
  const [showManualTransaction, setShowManualTransaction] = useState(false);
  const [savingInclusion, setSavingInclusion] = useState(false);

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

  async function dismissPayment(warning: PaymentWarning) {
    try {
      const result = await api<{ operation_id?: string }>(`/api/transfers/payments/${warning.transaction_id}/dismiss`, { method: "POST", headers: { "x-csrf-token": props.csrf }, body: JSON.stringify({ reason: "not_a_payment" }) });
      await props.onPaymentDismissed(result.operation_id);
    } catch (error) {
      props.onCheckpointError(error instanceof Error ? error.message : "Payment warning could not be dismissed.");
    }
  }

  async function updateInclusion(value: "auto" | "always" | "never") {
    setSavingInclusion(true);
    try {
      const result = await api<{ operation_id: string }>(`/api/accounts/${props.account.id}`, { method: "PATCH", headers: { "Content-Type": "application/json", "x-csrf-token": props.csrf }, body: JSON.stringify({ net_worth_inclusion: value }) });
      await props.onAccountChanged(result.operation_id, "Net-worth inclusion updated.");
    } catch (error) {
      props.onCheckpointError(error instanceof Error ? error.message : "Net-worth inclusion could not be updated.");
    } finally {
      setSavingInclusion(false);
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
            {!props.account.is_anchored && props.account.account_type !== "external" ? <span className="statusBadge unanchored">Unanchored</span> : null}
            {props.account.account_type === "external" ? <span className="statusBadge external">Untracked</span> : null}
          </div>
          {props.account.account_type !== "external" ? <ReconciliationBadge status={props.reconciliation} formatMoney={props.formatMoney} /> : null}
        </div>
        <div className="accountBalanceRow">
          <div><strong className={props.account.sidebar_balance_cents === null ? "amount" : props.balanceCents < 0 ? "amount negative" : "amount positive"}>{props.account.sidebar_balance_cents === null ? "—" : props.formatMoney(props.balanceCents)}</strong><span>{props.account.sidebar_balance_kind === "unanchored" ? "Add statement balance" : props.account.sidebar_balance_kind === "excluded" ? "Excluded" : props.account.sidebar_balance_kind === "recent_activity" ? "Last 30 days" : "Current balance"}</span></div>
          <div><strong>{props.missingCategoryCount}</strong><span>Need category</span></div>
        </div>
        <div className="accountActionBar">
          {props.account.account_type !== "external" ? <button className="secondaryButton compactButton" onClick={() => setShowManualTransaction((current) => !current)}><Plus size={14} />Add transaction</button> : null}
          {props.account.account_type !== "external" ? <button className="primaryButton compactButton" onClick={props.onImport}><FileUp size={14} />File Import</button> : null}
          <button className="secondaryButton compactButton" onClick={props.onOpenReview}><ListChecks size={14} />Open Review</button>
          <button className="ghostButton compactIconButton" title="Refresh data" onClick={props.onRefresh}><RefreshCw size={14} /></button>
        </div>
      </header>
      {showManualTransaction ? <ManualTransactionForm accounts={props.transactionAccounts} categories={props.transactionCategories} csrf={props.csrf} defaultAccountId={props.account.id} onSaved={props.onManualTransactionSaved} onError={props.onCheckpointError} onCancel={() => setShowManualTransaction(false)} /> : null}
      {props.account.account_type !== "external" ? <div className="netWorthInclusionControl"><label>Net worth<select disabled={savingInclusion} value={props.account.net_worth_inclusion} onChange={(event) => void updateInclusion(event.target.value as "auto" | "always" | "never")}><option value="auto">Automatic — include once anchored</option><option value="always">Always include</option><option value="never">Never include</option></select></label><span>{props.account.net_worth_inclusion === "auto" ? "A statement balance or imported balance anchors this account." : props.account.net_worth_inclusion === "always" ? "Transaction history is used even without an anchor." : "This account is excluded from net worth."}</span></div> : null}
      <div className="accountVerificationGrid">
        {props.account.account_type !== "external" ? <form className="statementCheckpointForm" onSubmit={submitCheckpoint}>
          <div><strong>Statement balance</strong><span>Add the ending balance from a bank statement to verify the ledger.</span></div>
          <input type="date" aria-label="Statement date" value={statementDate} onChange={(event) => setStatementDate(event.target.value)} required />
          <input type="text" inputMode="decimal" aria-label="Statement balance" placeholder="Balance" value={statementBalance} onChange={(event) => setStatementBalance(event.target.value)} required />
          <button className="secondaryButton compactButton" disabled={saving}>{saving ? "Saving..." : "Save"}</button>
          {latest && !latest.reconciled ? <button type="button" className="ghostButton compactButton" onClick={() => props.onInvestigateReconciliation(props.reconciliation!)}>Investigate difference</button> : null}
        </form> : null}
        <PaymentVerification status={props.paymentVerification} formatMoney={props.formatMoney} onInvestigate={props.onInvestigatePayment} onDismiss={(warning) => void dismissPayment(warning)} externalAccounts={props.externalAccounts} csrf={props.csrf} onExternalSettled={async (operationId) => props.onAccountChanged(operationId, "Payment linked to an untracked account.")} onError={props.onCheckpointError} />
      </div>
      {props.children}
    </div>
  );
}
