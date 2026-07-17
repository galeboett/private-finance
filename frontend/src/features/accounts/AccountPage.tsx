import { FileUp, LayoutDashboard, ListChecks, Plus, ReceiptText, RefreshCw, Settings, X } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { useApiClient } from "../../api/hooks";
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
  refundsCents: number;
  averageMonthlySpendCents: number;
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
  holdings?: ReactNode;
  transactionsCollapsed?: boolean;
  onToggleTransactions?: () => void;
  children?: ReactNode;
};

export function AccountPage(props: Props) {
  const api = useApiClient();
  const [statementDate, setStatementDate] = useState("");
  const [statementBalance, setStatementBalance] = useState("");
  const [saving, setSaving] = useState(false);
  const [showManualTransaction, setShowManualTransaction] = useState(false);
  const [savingInclusion, setSavingInclusion] = useState(false);
  const [showReview, setShowReview] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

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
      setShowSettings(false);
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
  const reviewCount = (latest && !latest.reconciled ? 1 : 0) + (props.paymentVerification?.warnings.length ?? 0);
  const balanceLabel = props.account.sidebar_balance_kind === "unanchored"
    ? "Add statement balance"
    : props.account.sidebar_balance_kind === "excluded"
      ? "Excluded from net worth"
      : props.account.sidebar_balance_kind === "recent_activity"
        ? "Last 30 days"
        : "Current balance";

  return <>
    <div className="stickyAccountChrome accountOverviewChrome">
      <header className="accountLedgerHeader compactAccountHeader">
        <div className="accountIdentity">
          <span className="eyebrow">{props.account.institution_name ?? "Local account"} · {props.readableAccountType(props.account.account_type)}</span>
          <h1>{props.account.display_name}{props.account.last_four ? ` (${props.account.last_four})` : ""}</h1>
          <div className="accountMetaRow">
            <span>{props.accountGroupLabel(props.account.account_type)}</span>
            <span>{props.account.status}</span>
            {props.account.account_type === "external" ? <span className="statusBadge external">Untracked</span> : null}
          </div>
        </div>
        <div className="accountHeroBalance">
          <span>{balanceLabel}</span>
          <div>
            <strong className={props.account.sidebar_balance_cents === null ? "amount" : props.balanceCents < 0 ? "amount negative" : "amount positive"}>{props.account.sidebar_balance_cents === null ? "—" : props.formatMoney(props.balanceCents)}</strong>
            {props.account.account_type !== "external" ? <span className={props.account.is_anchored ? "statusBadge anchored" : "statusBadge unanchored"}>{props.account.is_anchored ? "Anchored" : "Unanchored"}</span> : null}
          </div>
          {props.account.account_type !== "external" ? <ReconciliationBadge status={props.reconciliation} formatMoney={props.formatMoney} /> : null}
        </div>
        <div className="accountActionBar">
          {props.account.account_type !== "external" ? <button className="secondaryButton compactButton" onClick={() => setShowManualTransaction((current) => !current)}><Plus size={14} />Add transaction</button> : null}
          {props.account.account_type !== "external" ? <button className="primaryButton compactButton" onClick={props.onImport}><FileUp size={14} />Import</button> : null}
          <button className="ghostButton compactIconButton" title="Refresh data" onClick={props.onRefresh}><RefreshCw size={14} /></button>
        </div>
      </header>

      <nav className="accountPageTabs" aria-label="Account sections">
        <button type="button" className="active"><LayoutDashboard size={15} />Overview</button>
        <button type="button" onClick={() => document.getElementById("account-transactions")?.scrollIntoView({ behavior: "smooth", block: "start" })}><ReceiptText size={15} />Transactions</button>
        <button type="button" className={showReview ? "active" : ""} onClick={() => setShowReview((current) => !current)}><ListChecks size={15} />Needs review{reviewCount > 0 ? <span>{reviewCount}</span> : null}</button>
        <button type="button" onClick={() => setShowSettings(true)}><Settings size={15} />Settings</button>
      </nav>

      <section className="accountSummaryMetrics" aria-label="Account summary">
        <div><span>Current balance</span><strong>{props.account.sidebar_balance_cents === null ? "—" : props.formatMoney(props.balanceCents)}</strong><small>{props.account.is_anchored ? "Verified against a balance" : "Not yet anchored"}</small></div>
        <div><span>Refunds · last 30 days</span><strong>{props.formatMoney(props.refundsCents)}</strong><small>Posted refunds for this account</small></div>
        <div><span>Average monthly spend</span><strong>{props.formatMoney(props.averageMonthlySpendCents)}</strong><small>Across months with activity</small></div>
      </section>

      {props.missingCategoryCount > 0 ? <div className="accountCategoryNotice"><div><strong>{props.missingCategoryCount} transaction{props.missingCategoryCount === 1 ? "" : "s"} need a category</strong><span>Category work stays with transactions rather than the review queue.</span></div><button type="button" className="secondaryButton compactButton" onClick={props.onViewUncategorized}>View transactions</button></div> : null}

      {showReview ? <section className="accountNeedsReviewPanel">
        <header><div><span className="eyebrow">Needs review</span><h2>Account notifications</h2></div><button type="button" className="ghostButton compactButton" onClick={props.onOpenReview}>Open full review</button></header>
        {latest && !latest.reconciled && props.reconciliation ? <div className="accountReviewItem"><ReconciliationBadge status={props.reconciliation} formatMoney={props.formatMoney} /><button type="button" className="secondaryButton compactButton" onClick={() => props.onInvestigateReconciliation(props.reconciliation!)}>Investigate difference</button></div> : null}
        <PaymentVerification status={props.paymentVerification} formatMoney={props.formatMoney} onInvestigate={props.onInvestigatePayment} onDismiss={(warning) => void dismissPayment(warning)} externalAccounts={props.externalAccounts} csrf={props.csrf} onExternalSettled={async (operationId) => props.onAccountChanged(operationId, "Payment linked to an untracked account.")} onError={props.onCheckpointError} />
        {reviewCount === 0 ? <p className="emptyText">No account-level notifications need attention.</p> : null}
      </section> : null}

      {showManualTransaction ? <ManualTransactionForm accounts={props.transactionAccounts} categories={props.transactionCategories} csrf={props.csrf} defaultAccountId={props.account.id} onSaved={props.onManualTransactionSaved} onError={props.onCheckpointError} onCancel={() => setShowManualTransaction(false)} /> : null}
    </div>

    {props.holdings ? <section className="accountAssetSection">{props.holdings}</section> : null}
    {props.onToggleTransactions ? <div className="assetTransactionToggle"><div><strong>Account transactions</strong><span>Investment accounts open with assets first. Expand activity when you need it.</span></div><button className="secondaryButton compactButton" onClick={props.onToggleTransactions}>{props.transactionsCollapsed ? "Show transactions" : "Hide transactions"}</button></div> : null}
    {!props.transactionsCollapsed ? props.children : null}

    {showSettings ? <div className="modalBackdrop accountSettingsBackdrop" onClick={() => setShowSettings(false)}>
      <section className="modalCard accountSettingsModal" role="dialog" aria-modal="true" aria-label="Account settings" onClick={(event) => event.stopPropagation()}>
        <header className="modalHeader"><div><span className="eyebrow">Account settings</span><h2>{props.account.display_name}</h2><p>Manage net-worth treatment and add a statement balance.</p></div><button type="button" className="ghostButton compactIconButton" onClick={() => setShowSettings(false)} aria-label="Close account settings"><X size={16} /></button></header>
        {props.account.account_type !== "external" ? <>
          <div className="netWorthInclusionControl"><label>Net worth<select disabled={savingInclusion} value={props.account.net_worth_inclusion} onChange={(event) => void updateInclusion(event.target.value as "auto" | "always" | "never")}><option value="auto">Automatic — include once anchored</option><option value="always">Always include</option><option value="never">Never include</option></select></label><span>{props.account.net_worth_inclusion === "auto" ? "A statement balance or imported balance anchors this account." : props.account.net_worth_inclusion === "always" ? "Transaction history is used even without an anchor." : "This account is excluded from net worth."}</span></div>
          <form className="statementCheckpointForm accountSettingsCheckpoint" onSubmit={submitCheckpoint}>
            <div><strong>Statement balance</strong><span>Add an ending balance to anchor and verify this account.</span></div>
            <input type="date" aria-label="Statement date" value={statementDate} onChange={(event) => setStatementDate(event.target.value)} required />
            <input type="text" inputMode="decimal" aria-label="Statement balance" placeholder="Balance" value={statementBalance} onChange={(event) => setStatementBalance(event.target.value)} required />
            <button className="primaryButton compactButton" disabled={saving}>{saving ? "Saving..." : "Save balance"}</button>
            {latest && !latest.reconciled ? <button type="button" className="ghostButton compactButton" onClick={() => props.onInvestigateReconciliation(props.reconciliation!)}>Investigate difference</button> : null}
          </form>
        </> : <p className="emptyText">Untracked accounts do not participate in net worth.</p>}
      </section>
    </div> : null}
  </>;
}
