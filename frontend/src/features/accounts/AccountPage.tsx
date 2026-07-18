import { CopyCheck, CreditCard, FileUp, Plus, RefreshCw, Settings, Tags, Undo2, X } from "lucide-react";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useApiClient } from "../../api/hooks";
import type { ReconciliationStatus } from "./ReconciliationBadge";
import { PaymentVerification, type PaymentVerificationStatus, type PaymentWarning } from "../transfers/PaymentVerification";
import { ManualTransactionForm, type ManualTransactionAccount, type ManualTransactionCategory } from "../transactions/ManualTransactionForm";
import type { ExternalAccountOption } from "./ExternalPaymentAction";
import type { DuplicateAction, DuplicatePair } from "../review/DuplicateReview";
import { TransactionCompareCard } from "../review/TransactionCompareCard";

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
  suggestedRefundCount: number;
  duplicatePairs: DuplicatePair[];
  uncategorizedActive: boolean;
  reconciliation: ReconciliationStatus | null;
  paymentVerification: PaymentVerificationStatus | null;
  csrf: string;
  transactionAccounts: ManualTransactionAccount[];
  transactionCategories: ManualTransactionCategory[];
  externalAccounts: ExternalAccountOption[];
  formatMoney: (cents: number) => string;
  readableAccountType: (value: string) => string;
  onImport: () => void;
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
  suggestedRefunds?: ReactNode;
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
  const [activeOverlay, setActiveOverlay] = useState<"bill-pay" | "refunds" | "duplicates" | "settings" | null>(null);
  const [accountDuplicatePairs, setAccountDuplicatePairs] = useState<DuplicatePair[]>(props.duplicatePairs);
  const [loadingDuplicates, setLoadingDuplicates] = useState(false);
  const [resolvingDuplicateId, setResolvingDuplicateId] = useState<number | null>(null);

  useEffect(() => {
    setActiveOverlay(null);
    setShowManualTransaction(false);
    setAccountDuplicatePairs(props.duplicatePairs);
  }, [props.account.id]);

  useEffect(() => {
    setAccountDuplicatePairs(props.duplicatePairs);
  }, [props.duplicatePairs]);

  async function loadAccountDuplicates() {
    setLoadingDuplicates(true);
    try {
      const pairs = await api<DuplicatePair[]>(`/api/duplicates/pending?account_id=${props.account.id}&limit=100`);
      setAccountDuplicatePairs(pairs);
    } catch (error) {
      props.onCheckpointError(error instanceof Error ? error.message : "Suggested duplicates could not be loaded.");
    } finally {
      setLoadingDuplicates(false);
    }
  }

  function openDuplicates() {
    setActiveOverlay("duplicates");
    void loadAccountDuplicates();
  }

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
      setActiveOverlay(null);
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

  async function resolveDuplicate(transactionId: number, action: DuplicateAction) {
    setResolvingDuplicateId(transactionId);
    try {
      const result = await api<{ operation_id: string }>(`/api/duplicates/${transactionId}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-csrf-token": props.csrf },
        body: JSON.stringify({ action }),
      });
      const message = action === "remove_new"
        ? "Removed the new duplicate copy."
        : action === "keep_both"
          ? "Kept both transactions and remembered this decision."
          : action === "remove_sign_artifact"
            ? "Removed the positive mirrored-sign artifact."
            : "Updated the original with the newer bank details and preserved your annotations.";
      await props.onAccountChanged(result.operation_id, message);
      await loadAccountDuplicates();
    } catch (error) {
      props.onCheckpointError(error instanceof Error ? error.message : "The duplicate could not be resolved.");
    } finally {
      setResolvingDuplicateId(null);
    }
  }

  const latest = props.reconciliation?.latest;
  const paymentWarningCount = props.paymentVerification?.warnings.length ?? 0;
  return <>
    <div className="stickyAccountChrome accountOverviewChrome">
      <header className="accountLedgerHeader compactAccountHeader">
        <div className="accountIdentity">
          <span className="eyebrow">{props.account.institution_name ?? "Local account"} · {props.readableAccountType(props.account.account_type)}</span>
          <div className="accountTitleRow">
            <h1>{props.account.display_name}{props.account.last_four ? ` (${props.account.last_four})` : ""}</h1>
            {props.account.account_type === "external" ? <span className="statusBadge external">Untracked</span> : <span className={props.account.is_anchored ? "statusBadge anchored" : "statusBadge unanchored"}>{props.account.is_anchored ? "Anchored" : "Unanchored"}</span>}
          </div>
        </div>
        <div className="accountActionBar">
          {props.account.account_type !== "external" ? <button className="secondaryButton compactButton" onClick={() => setShowManualTransaction((current) => !current)}><Plus size={14} />Add transaction</button> : null}
          {props.account.account_type !== "external" ? <button className="primaryButton compactButton" onClick={props.onImport}><FileUp size={14} />Import</button> : null}
          <button className="ghostButton compactIconButton" title="Refresh data" onClick={props.onRefresh}><RefreshCw size={14} /></button>
        </div>
      </header>

      <section className="accountSummaryMetrics" aria-label="Account summary">
        <div><span>Current balance</span><strong>{props.account.sidebar_balance_cents === null ? "—" : props.formatMoney(props.balanceCents)}</strong><small>{props.account.is_anchored ? "Verified against a balance" : "Not yet anchored"}</small></div>
        <div><span>Last month's refunds</span><strong>{props.formatMoney(props.refundsCents)}</strong><small>Posted refunds for this account</small></div>
        <div><span>Average monthly spend</span><strong>{props.formatMoney(props.averageMonthlySpendCents)}</strong><small>Across months with activity</small></div>
      </section>

      <nav className="accountPageTabs accountActionTabs" aria-label="Account actions">
        <button type="button" className={props.uncategorizedActive ? "active" : ""} onClick={props.onViewUncategorized}><Tags size={15} />Uncategorized{props.missingCategoryCount > 0 ? <span>{props.missingCategoryCount}</span> : null}</button>
        <button type="button" className={activeOverlay === "bill-pay" ? "active" : ""} onClick={() => setActiveOverlay("bill-pay")}><CreditCard size={15} />Bill pay{paymentWarningCount > 0 ? <span>{paymentWarningCount}</span> : null}</button>
        <button type="button" className={activeOverlay === "refunds" ? "active" : ""} onClick={() => setActiveOverlay("refunds")}><Undo2 size={15} />Suggested refunds{props.suggestedRefundCount > 0 ? <span>{props.suggestedRefundCount}</span> : null}</button>
        <button type="button" className={activeOverlay === "duplicates" ? "active" : ""} onClick={openDuplicates}><CopyCheck size={15} />Duplicates{accountDuplicatePairs.length > 0 ? <span>{accountDuplicatePairs.length}</span> : null}</button>
        <button type="button" className={activeOverlay === "settings" ? "active" : ""} onClick={() => setActiveOverlay("settings")}><Settings size={15} />Settings</button>
      </nav>

      {showManualTransaction ? <ManualTransactionForm accounts={props.transactionAccounts} categories={props.transactionCategories} csrf={props.csrf} defaultAccountId={props.account.id} onSaved={props.onManualTransactionSaved} onError={props.onCheckpointError} onCancel={() => setShowManualTransaction(false)} /> : null}
    </div>

    {props.holdings ? <section className="accountAssetSection">{props.holdings}</section> : null}
    {props.onToggleTransactions ? <div className="assetTransactionToggle"><div><strong>Account transactions</strong><span>Investment accounts open with assets first. Expand activity when you need it.</span></div><button className="secondaryButton compactButton" onClick={props.onToggleTransactions}>{props.transactionsCollapsed ? "Show transactions" : "Hide transactions"}</button></div> : null}
    {!props.transactionsCollapsed ? props.children : null}

    {activeOverlay === "bill-pay" ? <div className="modalBackdrop accountSettingsBackdrop" onClick={() => setActiveOverlay(null)}>
      <section className="modalCard accountActionModal" role="dialog" aria-modal="true" aria-label={`${props.account.display_name} bill pay`} onClick={(event) => event.stopPropagation()}>
        <header className="modalHeader"><div><span className="eyebrow">Bill pay</span><h2>{props.account.display_name}</h2><p>Review confirmed card payments and resolve anything that still needs attention.</p></div><button type="button" className="ghostButton compactIconButton" onClick={() => setActiveOverlay(null)} aria-label="Close bill pay"><X size={16} /></button></header>
        {props.account.account_type !== "external" ? <form className="statementCheckpointForm accountSettingsCheckpoint billPayStatementForm" onSubmit={submitCheckpoint}>
          <div><strong>Statement balance</strong><span>Add an ending balance to anchor and verify this account.</span></div>
          <input type="date" aria-label="Statement date" value={statementDate} onChange={(event) => setStatementDate(event.target.value)} required />
          <input type="text" inputMode="decimal" aria-label="Statement balance" placeholder="Balance" value={statementBalance} onChange={(event) => setStatementBalance(event.target.value)} required />
          <button className="primaryButton compactButton" disabled={saving}>{saving ? "Saving..." : "Save balance"}</button>
          {latest && !latest.reconciled ? <button type="button" className="ghostButton compactButton" onClick={() => props.onInvestigateReconciliation(props.reconciliation!)}>Investigate difference</button> : null}
        </form> : null}
        {props.paymentVerification ? <PaymentVerification status={props.paymentVerification} formatMoney={props.formatMoney} onInvestigate={props.onInvestigatePayment} onDismiss={(warning) => void dismissPayment(warning)} externalAccounts={props.externalAccounts} csrf={props.csrf} onExternalSettled={async (operationId) => props.onAccountChanged(operationId, "Payment linked to an untracked account.")} onError={props.onCheckpointError} /> : <p className="emptyText accountOverlayEmpty">No bill-payment activity is tracked for this account.</p>}
      </section>
    </div> : null}

    {activeOverlay === "refunds" ? <div className="modalBackdrop accountSettingsBackdrop" onClick={() => setActiveOverlay(null)}>
      <section className="modalCard accountActionModal accountRefundModal" role="dialog" aria-modal="true" aria-label={`${props.account.display_name} suggested refunds`} onClick={(event) => event.stopPropagation()}>
        <header className="modalHeader"><div><span className="eyebrow">Suggested refunds</span><h2>{props.account.display_name}</h2><p>Review refund matches found for this account.</p></div><button type="button" className="ghostButton compactIconButton" onClick={() => setActiveOverlay(null)} aria-label="Close suggested refunds"><X size={16} /></button></header>
        <div className="accountRefundModalBody">{props.suggestedRefunds ?? <p className="emptyText accountOverlayEmpty">No suggested refund matches for this account.</p>}</div>
      </section>
    </div> : null}

    {activeOverlay === "duplicates" ? <div className="modalBackdrop accountSettingsBackdrop" onClick={() => setActiveOverlay(null)}>
      <section className="modalCard accountActionModal accountDuplicateModal" role="dialog" aria-modal="true" aria-label={`${props.account.display_name} suggested duplicates`} onClick={(event) => event.stopPropagation()}>
        <header className="modalHeader"><div><span className="eyebrow">Suggested duplicates</span><h2>{props.account.display_name}</h2><p>Compare possible duplicate transactions found for this account.</p></div><button type="button" className="ghostButton compactIconButton" onClick={() => setActiveOverlay(null)} aria-label="Close suggested duplicates"><X size={16} /></button></header>
        <div className="accountDuplicateList">
          {accountDuplicatePairs.map((pair) => <article className="duplicatePair" key={pair.candidate.id}>
            <div className="duplicatePairHeader">
              <div><strong>{pair.tier === "mirrored" ? "Opposite-sign pair" : pair.exact_match ? "Exact transaction facts" : `${pair.diff_fields.length} field${pair.diff_fields.length === 1 ? "" : "s"} differ`}</strong><span>{pair.tier === "mirrored" ? "Verify that no money was returned before removing the positive row." : pair.exact_match ? "Repeated same-day purchases are possible. Review both rows before deciding." : `Description similarity ${Math.round(pair.similarity * 100)}%.`}</span></div>
              <span className={pair.exact_match ? "statusBadge confirmed" : "statusBadge possible-duplicate"}>{pair.tier.replace("_", " ")}</span>
            </div>
            <div className="transactionCompareGrid">
              <TransactionCompareCard title="Existing ledger transaction" transaction={pair.original} diffFields={pair.diff_fields} emphasis="original" />
              <TransactionCompareCard title="New imported copy" transaction={pair.candidate} diffFields={pair.diff_fields} />
            </div>
            <div className="duplicateActions">
              {pair.tier === "mirrored" ? <button className="primaryButton" title="Move the positive refund-typed row to Trash." onClick={() => void resolveDuplicate(pair.candidate.id, "remove_sign_artifact")} disabled={resolvingDuplicateId !== null}>Remove positive copy</button> : <button className={pair.safe_reimport ? "primaryButton" : "secondaryButton"} onClick={() => void resolveDuplicate(pair.candidate.id, "remove_new")} disabled={resolvingDuplicateId !== null}>Remove new copy</button>}
              <button className="secondaryButton" onClick={() => void resolveDuplicate(pair.candidate.id, "keep_both")} disabled={resolvingDuplicateId !== null}>Keep both</button>
              {pair.tier !== "mirrored" ? <button className="secondaryButton" onClick={() => void resolveDuplicate(pair.candidate.id, "replace_old")} disabled={resolvingDuplicateId !== null}>Replace old bank details</button> : null}
            </div>
          </article>)}
          {loadingDuplicates ? <p className="emptyText accountOverlayEmpty">Loading suggested duplicates...</p> : null}
          {!loadingDuplicates && accountDuplicatePairs.length === 0 ? <p className="emptyText accountOverlayEmpty">No suggested duplicates were found for this account.</p> : null}
        </div>
      </section>
    </div> : null}

    {activeOverlay === "settings" ? <div className="modalBackdrop accountSettingsBackdrop" onClick={() => setActiveOverlay(null)}>
      <section className="modalCard accountSettingsModal" role="dialog" aria-modal="true" aria-label="Account settings" onClick={(event) => event.stopPropagation()}>
        <header className="modalHeader"><div><span className="eyebrow">Account settings</span><h2>{props.account.display_name}</h2><p>Manage how this account participates in net worth.</p></div><button type="button" className="ghostButton compactIconButton" onClick={() => setActiveOverlay(null)} aria-label="Close account settings"><X size={16} /></button></header>
        {props.account.account_type !== "external" ? <>
          <div className="netWorthInclusionControl"><label>Net worth<select disabled={savingInclusion} value={props.account.net_worth_inclusion} onChange={(event) => void updateInclusion(event.target.value as "auto" | "always" | "never")}><option value="auto">Automatic — include once anchored</option><option value="always">Always include</option><option value="never">Never include</option></select></label><span>{props.account.net_worth_inclusion === "auto" ? "A statement balance or imported balance anchors this account." : props.account.net_worth_inclusion === "always" ? "Transaction history is used even without an anchor." : "This account is excluded from net worth."}</span></div>
        </> : <p className="emptyText">Untracked accounts do not participate in net worth.</p>}
      </section>
    </div> : null}
  </>;
}
