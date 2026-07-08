import {
  AlertCircle,
  ArrowDownToLine,
  BadgeDollarSign,
  BarChart3,
  CheckCircle2,
  FileUp,
  Landmark,
  LayoutDashboard,
  ListChecks,
  Pencil,
  PiggyBank,
  Plus,
  ReceiptText,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  WalletCards,
} from "lucide-react";
import { useEffect, useState } from "react";

type BootstrapCategory = { id: number; key: string; label: string };
type DashboardSummary = {
  review_counts: Record<string, number>;
  month_to_date_expense_cents: number;
  cash_flow_cents: number;
  net_worth_snapshot_cents: number;
};

type AccountSummary = {
  id: number;
  display_name: string;
  account_type: string;
  status: string;
  institution_name: string | null;
  currency: string;
  last_four: string | null;
};

type ReviewItem = {
  id: number;
  description: string;
  amount_cents: number;
  review_status: string;
};

type TransactionRow = {
  id: number;
  account_id: number;
  raw_description: string;
  amount_cents: number;
  transaction_type: string;
  review_status: string;
  transaction_date: string;
  category_id: number | null;
  user_note: string | null;
};

type TransferTransaction = Pick<TransactionRow, "id" | "account_id" | "raw_description" | "amount_cents" | "transaction_type" | "review_status" | "transaction_date">;

type TransferCandidate = {
  id: number;
  from_transaction: TransferTransaction;
  to_transaction: TransferTransaction;
  match_confidence: number;
  confirmed: boolean;
  suggested_type: string;
};

type ImportPreview = {
  preset_type: string;
  rows: Array<Record<string, string | number | null>>;
  warnings: string[];
};

type ToastState = {
  tone: "success" | "error" | "info";
  message: string;
};

type DeleteTarget =
  | { kind: "transaction"; id: number; label: string }
  | { kind: "transaction_bulk"; ids: number[]; label: string }
  | { kind: "holding"; id: number; label: string };

type SavedRuleAction = {
  id: number;
  matchText: string;
};

type RuleSummary = {
  id: number;
  category_id: number;
  priority: number;
  field_name: string;
  match_text: string;
  suggested_transaction_type: string;
};

type CategoryTotal = { category: string; amount_cents: number };
type MonthlyCashFlow = { month: string; income_cents: number; expense_cents: number; net_cents: number };
type NetWorthAccount = { account_id: number; account: string; account_type: string; latest_date: string; market_value_cents: number };
type AllocationRow = { asset_class: string; market_value_cents: number };
type HoldingRow = {
  id: number;
  account_id: number;
  account: string;
  snapshot_date: string;
  symbol: string | null;
  description: string | null;
  csv_description: string | null;
  user_description: string | null;
  quantity: number | null;
  price_cents: number | null;
  display_price_cents: number | null;
  price_date: string;
  market_value_cents: number;
  display_market_value_cents: number;
  asset_class: string | null;
};

const navItems = [
  { label: "Dashboard", icon: LayoutDashboard },
  { label: "Accounts", icon: WalletCards },
  { label: "Transactions", icon: ReceiptText },
  { label: "Cash Flow", icon: BarChart3 },
  { label: "Reports", icon: TrendingUp },
  { label: "Review", icon: ListChecks },
  { label: "Settings", icon: Settings },
];

const reportTabs = ["Reports", "Cash Flow", "Spending", "Income", "Net Worth"];

const transactionTypes = [
  { value: "expense", label: "Expense" },
  { value: "income", label: "Income" },
  { value: "transfer", label: "Transfer" },
  { value: "credit_card_payment", label: "Card payment" },
  { value: "refund", label: "Refund" },
  { value: "investment_flow", label: "Investment flow" },
  { value: "adjustment", label: "Adjustment" },
];

const formatMoney = (cents: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);

const readableAccountType = (value: string) => value.replace("_", " ");

const reviewStatusLabel = (value: string) =>
  ({
    needs_review: "Needs review",
    suggested: "Suggested",
    possible_duplicate: "Possible duplicate",
    confirmed: "Confirmed",
  })[value] ?? readableAccountType(value);

const reviewStatusClass = (value: string) => `statusBadge ${value.replace(/_/g, "-")}`;

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new Error(await readableApiError(response));
  }
  return parseApiJson<T>(response);
}

async function readableApiError(response: Response): Promise<string> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return `The API returned ${response.status} ${response.statusText || "with a non-JSON response"}. Make sure the backend is running at http://127.0.0.1:8000.`;
  }
  try {
    const data = await response.json();
    const detail = data?.detail;
    if (Array.isArray(detail) && detail.length > 0) {
      return detail[0]?.msg ?? "The request could not be completed.";
    }
    if (typeof detail === "string") {
      return detail;
    }
  } catch {
    return "The request could not be completed.";
  }
  return "The request could not be completed.";
}

async function parseApiJson<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    throw new Error("The app received the frontend HTML instead of API data. Open http://127.0.0.1:8000, or start the backend before using the Vite dev URL.");
  }
  return response.json() as Promise<T>;
}

export function App() {
  const [configured, setConfigured] = useState(false);
  const [csrf, setCsrf] = useState("");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [toast, setToast] = useState<ToastState | null>(null);
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null);
  const [categories, setCategories] = useState<BootstrapCategory[]>([]);
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [review, setReview] = useState<ReviewItem[]>([]);
  const [transactions, setTransactions] = useState<TransactionRow[]>([]);
  const [rules, setRules] = useState<RuleSummary[]>([]);
  const [categoryTotals, setCategoryTotals] = useState<CategoryTotal[]>([]);
  const [cashFlowRows, setCashFlowRows] = useState<MonthlyCashFlow[]>([]);
  const [netWorthAccounts, setNetWorthAccounts] = useState<NetWorthAccount[]>([]);
  const [allocationRows, setAllocationRows] = useState<AllocationRow[]>([]);
  const [holdingRows, setHoldingRows] = useState<HoldingRow[]>([]);
  const [transferCandidates, setTransferCandidates] = useState<TransferCandidate[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<number | "">("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null);
  const [activeTab, setActiveTab] = useState("Cash Flow");
  const [editingAccountId, setEditingAccountId] = useState<number | null>(null);
  const [newCategoryLabel, setNewCategoryLabel] = useState("");
  const [editingCategoryId, setEditingCategoryId] = useState<number | null>(null);
  const [editingCategoryLabel, setEditingCategoryLabel] = useState("");
  const [lastSavedRule, setLastSavedRule] = useState<SavedRuleAction | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [selectedTransactionIds, setSelectedTransactionIds] = useState<number[]>([]);
  const [lastSelectedTransactionId, setLastSelectedTransactionId] = useState<number | null>(null);
  const [accountForm, setAccountForm] = useState({
    institution_name: "",
    display_name: "",
    account_type: "checking",
    last_four: "",
  });

  useEffect(() => {
    void loadBootstrap();
  }, []);

  async function loadBootstrap() {
    const data = await api<{ configured: boolean; categories: BootstrapCategory[] }>("/api/bootstrap");
    setConfigured(data.configured);
    setCategories(data.categories);
    if (data.configured) {
      try {
        const me = await api<{ csrf_token: string }>("/api/me");
        setCsrf(me.csrf_token);
        await loadData();
      } catch {
        setCsrf("");
      }
    }
  }

  async function loadData() {
    const [dashboardData, accountsData, reviewData, transactionData, rulesData, categoryData, cashFlowData, netWorthData, allocationData, holdingsData, transferData] = await Promise.all([
      api<DashboardSummary>("/api/dashboard/summary"),
      api<AccountSummary[]>("/api/accounts"),
      api<ReviewItem[]>("/api/review"),
      api<TransactionRow[]>("/api/transactions"),
      api<RuleSummary[]>("/api/rules"),
      api<CategoryTotal[]>("/api/category-totals"),
      api<MonthlyCashFlow[]>("/api/cash-flow"),
      api<NetWorthAccount[]>("/api/net-worth/accounts"),
      api<AllocationRow[]>("/api/investments/allocation"),
      api<HoldingRow[]>("/api/investments/holdings"),
      api<TransferCandidate[]>("/api/transfers/unconfirmed"),
    ]);
    setDashboard(dashboardData);
    setAccounts(accountsData);
    setReview(reviewData);
    setTransactions(transactionData);
    setRules(rulesData);
    setCategoryTotals(categoryData);
    setCashFlowRows(cashFlowData);
    setNetWorthAccounts(netWorthData);
    setAllocationRows(allocationData);
    setHoldingRows(holdingsData);
    setTransferCandidates(transferData);
  }

  function showToast(nextToast: ToastState) {
    setToast(nextToast);
  }

  function clearAccountForm() {
    setEditingAccountId(null);
    setAccountForm({ institution_name: "", display_name: "", account_type: "checking", last_four: "" });
  }

  function beginEditAccount(account: AccountSummary) {
    setEditingAccountId(account.id);
    setSelectedAccountId(account.id);
    setAccountForm({
      institution_name: account.institution_name ?? "",
      display_name: account.display_name,
      account_type: account.account_type,
      last_four: account.last_four ?? "",
    });
  }

  async function handleSetup() {
    setErrorMessage("");
    if (password.length < 12) {
      setErrorMessage("Use at least 12 characters for your local password.");
      return;
    }
    try {
      await api("/api/setup", { method: "POST", body: JSON.stringify({ password }) });
      setConfigured(true);
      setPassword("");
      showToast({ tone: "success", message: "Workspace initialized. Sign in with your new password." });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Setup failed.");
    }
  }

  async function handleLogin() {
    setErrorMessage("");
    try {
      const result = await api<{ csrf_token: string }>("/api/login", { method: "POST", body: JSON.stringify({ password }) });
      setCsrf(result.csrf_token);
      setPassword("");
      await loadData();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Login failed.");
    }
  }

  async function saveAccount() {
    setToast(null);
    if (!accountForm.display_name.trim()) {
      showToast({ tone: "error", message: "Add an account name before saving." });
      return;
    }
    try {
      const isEditing = editingAccountId !== null;
      const result = await api<{ id?: number }>(isEditing ? `/api/accounts/${editingAccountId}` : "/api/accounts", {
        method: isEditing ? "PATCH" : "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify(accountForm),
      });
      if (result.id) {
        setSelectedAccountId(result.id);
      }
      clearAccountForm();
      await loadData();
      showToast({
        tone: "success",
        message: isEditing ? "Account updated." : "Account added. It is selected for your next import.",
      });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Account could not be saved." });
    }
  }

  async function createCategory() {
    const label = newCategoryLabel.trim();
    if (!label) {
      showToast({ tone: "error", message: "Add a category name before saving." });
      return;
    }
    try {
      const category = await api<BootstrapCategory>("/api/categories", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ label }),
      });
      setCategories((current) => [...current, category].sort((left, right) => left.label.localeCompare(right.label)));
      setNewCategoryLabel("");
      showToast({ tone: "success", message: "Category added. You can use it during review now." });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Category could not be added." });
    }
  }

  async function updateCategory() {
    const label = editingCategoryLabel.trim();
    if (!editingCategoryId || !label) {
      showToast({ tone: "error", message: "Choose a category and enter a name before saving." });
      return;
    }
    try {
      await api(`/api/categories/${editingCategoryId}`, {
        method: "PATCH",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ label }),
      });
      setCategories((current) =>
        current.map((category) => (category.id === editingCategoryId ? { ...category, label } : category)).sort((left, right) => left.label.localeCompare(right.label)),
      );
      setEditingCategoryId(null);
      setEditingCategoryLabel("");
      showToast({ tone: "success", message: "Category renamed." });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Category could not be updated." });
    }
  }

  async function previewSelectedImport() {
    setToast(null);
    setImportPreview(null);
    if (!selectedAccountId) {
      showToast({ tone: "error", message: "Choose or add the account this CSV belongs to first." });
      return;
    }
    if (!selectedFile) {
      showToast({ tone: "error", message: "Choose a CSV file before previewing." });
      return;
    }
    const form = new FormData();
    form.append("file", selectedFile);
    try {
      const response = await fetch(`/api/imports/preview?account_id=${selectedAccountId}`, {
        method: "POST",
        credentials: "include",
        body: form,
      });
      if (!response.ok) {
        throw new Error(await readableApiError(response));
      }
      const preview = (await response.json()) as ImportPreview;
      setImportPreview(preview);
      showToast({ tone: "success", message: `Preview ready: ${preview.rows.length} sample rows detected.` });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Preview failed." });
    }
  }

  async function commitSelectedImport() {
    setToast(null);
    if (!selectedAccountId || !selectedFile || !importPreview) {
      showToast({ tone: "error", message: "Preview the file before committing it." });
      return;
    }
    const form = new FormData();
    form.append("file", selectedFile);
    try {
      const response = await fetch(`/api/imports/commit?account_id=${selectedAccountId}`, {
        method: "POST",
        credentials: "include",
        headers: { "x-csrf-token": csrf },
        body: form,
      });
      if (!response.ok) {
        throw new Error(await readableApiError(response));
      }
      const result = (await response.json()) as { inserted: number; skipped: number };
      setImportPreview(null);
      setSelectedFile(null);
      await loadData();
      showToast({ tone: "success", message: `Imported ${result.inserted} rows. Skipped ${result.skipped} duplicates.` });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Import failed." });
    }
  }

  async function updateTransaction(transactionId: number, patch: Partial<Pick<TransactionRow, "category_id" | "transaction_type" | "review_status" | "user_note">>) {
    setToast(null);
    try {
      await api(`/api/transactions/${transactionId}`, {
        method: "PATCH",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify(patch),
      });
      setTransactions((current) =>
        current.map((transaction) => (transaction.id === transactionId ? { ...transaction, ...patch } : transaction)),
      );
      setReview((current) => (patch.review_status === "confirmed" ? current.filter((item) => item.id !== transactionId) : current));
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Transaction could not be updated." });
    }
  }

  async function detectTransfers() {
    setToast(null);
    try {
      const result = await api<{ created: number }>("/api/transfers/detect", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
      });
      await loadData();
      showToast({
        tone: "success",
        message: result.created > 0 ? `Found ${result.created} possible transfer/payment matches.` : "No new transfer/payment matches found.",
      });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Transfer scan failed." });
    }
  }

  async function confirmTransferCandidate(candidateId: number) {
    setToast(null);
    try {
      await api(`/api/transfers/${candidateId}/confirm`, {
        method: "POST",
        headers: { "x-csrf-token": csrf },
      });
      await loadData();
      showToast({ tone: "success", message: "Transfer/payment confirmed and excluded from spending totals." });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Transfer candidate could not be confirmed." });
    }
  }

  async function rejectTransferCandidate(candidateId: number) {
    setToast(null);
    try {
      await api(`/api/transfers/${candidateId}/reject`, {
        method: "POST",
        headers: { "x-csrf-token": csrf },
      });
      await loadData();
      showToast({ tone: "success", message: "Transfer/payment suggestion rejected." });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Transfer candidate could not be rejected." });
    }
  }

  async function confirmTransaction(transaction: TransactionRow) {
    if (transaction.transaction_type === "expense" && !transaction.category_id) {
      showToast({ tone: "error", message: "Choose a category before confirming an expense." });
      return;
    }
    await updateTransaction(transaction.id, { review_status: "confirmed" });
    showToast({ tone: "success", message: "Transaction confirmed." });
  }

  async function saveRuleFromTransaction(transaction: TransactionRow) {
    setToast(null);
    if (!transaction.category_id) {
      showToast({ tone: "error", message: "Choose a category before saving a rule." });
      return;
    }
    const matchText = suggestedRuleText(transaction.raw_description);
    try {
      const rule = await api<{ id: number }>("/api/rules", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({
          category_id: transaction.category_id,
          field_name: "raw_description",
          match_text: matchText,
          suggested_transaction_type: transaction.transaction_type,
          priority: 100,
        }),
      });
      setLastSavedRule({ id: rule.id, matchText });
      await loadData();
      showToast({ tone: "success", message: `Rule saved for "${matchText}". Apply it below to categorize and confirm matches.` });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Rule could not be saved." });
    }
  }

  async function applySavedRule(scope: "unreviewed" | "all") {
    if (!lastSavedRule) {
      return;
    }
    await applyRule(lastSavedRule.id, scope);
  }

  async function applyRule(ruleId: number, scope: "unreviewed" | "all") {
    try {
      const result = await api<{ matched: number; updated: number }>(`/api/rules/${ruleId}/apply`, {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ scope }),
      });
      await loadData();
      const scopeLabel = scope === "unreviewed" ? "unreviewed transactions" : "previous transactions";
      showToast({ tone: "success", message: `Rule confirmed ${result.updated} of ${result.matched} matching ${scopeLabel}.` });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Rule could not be applied." });
    }
  }

  async function updateHoldingDescription(symbol: string | null, userDescription: string) {
    if (!symbol) {
      showToast({ tone: "error", message: "This holding does not have a symbol to save a reusable description." });
      return;
    }
    try {
      await api("/api/investments/holding-metadata", {
        method: "PATCH",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ symbol, user_description: userDescription }),
      });
      await loadData();
      showToast({ tone: "success", message: `Description saved for ${symbol}. Future uploads will use it in Holding details.` });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Holding description could not be saved." });
    }
  }

  function requestDelete(target: DeleteTarget) {
    setDeleteTarget(target);
    setDeleteConfirmText("");
  }

  function toggleTransactionSelection(transactionId: number, visibleIds: number[], shiftKey: boolean) {
    setSelectedTransactionIds((current) => {
      const next = new Set(current);
      if (shiftKey && lastSelectedTransactionId !== null) {
        const start = visibleIds.indexOf(lastSelectedTransactionId);
        const end = visibleIds.indexOf(transactionId);
        if (start >= 0 && end >= 0) {
          const [from, to] = start < end ? [start, end] : [end, start];
          visibleIds.slice(from, to + 1).forEach((id) => next.add(id));
          return Array.from(next);
        }
      }
      if (next.has(transactionId)) {
        next.delete(transactionId);
      } else {
        next.add(transactionId);
      }
      return Array.from(next);
    });
    setLastSelectedTransactionId(transactionId);
  }

  function requestBulkTransactionDelete(ids: number[]) {
    if (ids.length === 0) {
      showToast({ tone: "error", message: "Select at least one transaction before bulk delete." });
      return;
    }
    requestDelete({ kind: "transaction_bulk", ids, label: `${ids.length} selected transaction rows` });
  }

  async function confirmDelete() {
    if (!deleteTarget) {
      return;
    }
    if (deleteConfirmText !== "DELETE") {
      showToast({ tone: "error", message: "Type DELETE to confirm removing this row." });
      return;
    }
    try {
      if (deleteTarget.kind === "transaction_bulk") {
        for (const id of deleteTarget.ids) {
          await api(`/api/transactions/${id}`, {
            method: "DELETE",
            headers: { "x-csrf-token": csrf },
            body: JSON.stringify({ confirm_text: deleteConfirmText }),
          });
        }
      } else {
        const path = deleteTarget.kind === "transaction" ? `/api/transactions/${deleteTarget.id}` : `/api/investments/holdings/${deleteTarget.id}`;
        await api(path, {
          method: "DELETE",
          headers: { "x-csrf-token": csrf },
          body: JSON.stringify({ confirm_text: deleteConfirmText }),
        });
      }
      setDeleteTarget(null);
      setDeleteConfirmText("");
      setSelectedTransactionIds([]);
      setLastSelectedTransactionId(null);
      await loadData();
      showToast({ tone: "success", message: deleteTarget.kind === "transaction_bulk" ? "Selected rows deleted." : "Row deleted." });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Rows could not be deleted." });
    }
  }

  if (!configured) {
    return (
      <div className="authShell">
        <section className="authPanel">
          <ShieldCheck size={28} />
          <h1>private-finance</h1>
          <p>Create the local password for this workspace.</p>
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Create password, 12+ characters" />
          {errorMessage ? <p className="formError">{errorMessage}</p> : null}
          <button className="primaryButton" onClick={() => void handleSetup()}>
            <CheckCircle2 size={16} />
            Initialize
          </button>
        </section>
      </div>
    );
  }

  if (!csrf) {
    return (
      <div className="authShell">
        <section className="authPanel">
          <ShieldCheck size={28} />
          <h1>Welcome back</h1>
          <p>Sign in locally to review imports, cash flow, and net worth.</p>
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Password" />
          {errorMessage ? <p className="formError">{errorMessage}</p> : null}
          <button className="primaryButton" onClick={() => void handleLogin()}>
            <ShieldCheck size={16} />
            Sign in
          </button>
        </section>
      </div>
    );
  }

  const totalIncomeCents = transactions.filter((transaction) => transaction.transaction_type === "income").reduce((sum, transaction) => sum + transaction.amount_cents, 0);
  const totalExpenseCents = Math.abs(
    transactions.filter((transaction) => transaction.transaction_type === "expense").reduce((sum, transaction) => sum + transaction.amount_cents, 0),
  );
  const netIncomeCents = totalIncomeCents - totalExpenseCents;
  const savingsRate = totalIncomeCents > 0 ? Math.max(0, Math.round((netIncomeCents / totalIncomeCents) * 1000) / 10) : 0;
  const selectedAccount = accounts.find((account) => account.id === selectedAccountId);
  const previewRows = importPreview?.rows.slice(0, 6) ?? [];
  const reviewTransactions = transactions.filter((transaction) => ["needs_review", "suggested", "possible_duplicate"].includes(transaction.review_status));
  const visibleReviewTransactions = reviewTransactions.slice(0, 5);
  const recentTransactions = transactions.slice(0, 8);
  const visibleReviewIds = visibleReviewTransactions.map((transaction) => transaction.id);
  const recentTransactionIds = recentTransactions.map((transaction) => transaction.id);
  const selectedVisibleReviewIds = visibleReviewIds.filter((id) => selectedTransactionIds.includes(id));
  const selectedRecentTransactionIds = recentTransactionIds.filter((id) => selectedTransactionIds.includes(id));
  const reportIncomeCents = cashFlowRows.reduce((sum, row) => sum + row.income_cents, 0);
  const reportExpenseCents = cashFlowRows.reduce((sum, row) => sum + row.expense_cents, 0);
  const reportNetCents = cashFlowRows.reduce((sum, row) => sum + row.net_cents, 0);
  const netWorthCents = netWorthAccounts.reduce((sum, row) => sum + row.market_value_cents, 0);

  return (
    <div className="appFrame">
      <aside className="sidebar">
        <div className="brandMark">
          <BadgeDollarSign size={22} />
        </div>
        <nav>
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button className={item.label === "Reports" ? "navItem active" : "navItem"} key={item.label} title={item.label}>
                <Icon size={16} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </aside>

      <main className="workspace">
        <header className="topBar">
          <div className="reportTabs" role="tablist" aria-label="Report views">
            {reportTabs.map((tab) => (
              <button className={tab === activeTab ? "reportTab active" : "reportTab"} key={tab} onClick={() => setActiveTab(tab)}>
                {tab}
              </button>
            ))}
          </div>
          <div className="toolbar">
            <button className="ghostButton" title="Search">
              <Search size={16} />
            </button>
            <button className="filterButton">This month</button>
            <button className="filterButton">Filters</button>
          </div>
        </header>

        {toast ? (
          <div className={`toast ${toast.tone}`}>
            {toast.tone === "success" ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
            <span>{toast.message}</span>
          </div>
        ) : null}

        {deleteTarget ? (
          <section className="deleteConfirmPanel">
            <div>
              <strong>{deleteTarget.kind === "transaction_bulk" ? "Delete selected transaction rows?" : `Delete this ${deleteTarget.kind} row?`}</strong>
              <span>{deleteTarget.label}</span>
              <small>This removes the row from reports. Audit history remains append-only.</small>
            </div>
            <input value={deleteConfirmText} onChange={(event) => setDeleteConfirmText(event.target.value)} placeholder="Type DELETE to confirm" />
            <div className="buttonRow">
              <button className="dangerButton" onClick={() => void confirmDelete()} disabled={deleteConfirmText !== "DELETE"}>
                Delete row
              </button>
              <button
                className="secondaryButton"
                onClick={() => {
                  setDeleteTarget(null);
                  setDeleteConfirmText("");
                }}
              >
                Cancel
              </button>
            </div>
          </section>
        ) : null}

        <section className="metricsGrid" aria-label="Financial summary">
          <MetricTile label="Total income" value={formatMoney(totalIncomeCents)} tone="green" />
          <MetricTile label="Total expenses" value={formatMoney(totalExpenseCents)} tone="red" />
          <MetricTile label="Total net income" value={formatMoney(netIncomeCents)} tone="neutral" />
          <MetricTile label="Savings rate" value={`${savingsRate}%`} tone="neutral" />
        </section>

        <section className="contentGrid">
          <section className="reportSurface">
            <div className="sectionHeader">
              <div>
                <span className="eyebrow">{activeTab}</span>
                <h2>{reportTitle(activeTab)}</h2>
              </div>
              <div className="inlineActions">
                <button className="ghostButton" title="Refresh data" onClick={() => void loadData()}>
                  <RefreshCw size={16} />
                </button>
              </div>
            </div>
            <ReportSurface
              activeTab={activeTab}
              income={reportIncomeCents}
              expenses={reportExpenseCents}
              net={reportNetCents}
              categoryTotals={categoryTotals}
              cashFlowRows={cashFlowRows}
              netWorthAccounts={netWorthAccounts}
              allocationRows={allocationRows}
              holdingRows={holdingRows}
              onUpdateHoldingDescription={updateHoldingDescription}
              onRequestDelete={requestDelete}
            />
          </section>

          <aside className="rightRail">
            <section className="phonePanel">
              <div className="phoneTop">
                <span>Accounts</span>
                <strong>{formatMoney(netWorthCents || dashboard?.net_worth_snapshot_cents || 0)}</strong>
              </div>
              <div className="sparkline" />
              <div className="accountStack">
                {accounts.slice(0, 3).map((account) => (
                  <div className="miniAccount" key={account.id}>
                    <Landmark size={16} />
                    <span>{account.display_name}</span>
                    <small>{readableAccountType(account.account_type)}</small>
                  </div>
                ))}
                {accounts.length === 0 ? <p className="emptyText">Add accounts to build your net-worth picture.</p> : null}
              </div>
            </section>
          </aside>
        </section>

        <section className="workGrid">
          <section className="toolPanel">
            <PanelTitle icon={WalletCards} title="Accounts" subtitle="Create or edit the containers your imports belong to." />
            <div className="compactForm">
              <input value={accountForm.display_name} onChange={(event) => setAccountForm({ ...accountForm, display_name: event.target.value })} placeholder="Account name" />
              <input value={accountForm.institution_name} onChange={(event) => setAccountForm({ ...accountForm, institution_name: event.target.value })} placeholder="Institution" />
              <select value={accountForm.account_type} onChange={(event) => setAccountForm({ ...accountForm, account_type: event.target.value })}>
                <option value="checking">Checking</option>
                <option value="savings">Savings</option>
                <option value="credit_card">Credit card</option>
                <option value="brokerage">Brokerage</option>
              </select>
              <input value={accountForm.last_four} onChange={(event) => setAccountForm({ ...accountForm, last_four: event.target.value })} placeholder="Last four" />
              <div className="buttonRow">
                <button className="primaryButton" onClick={() => void saveAccount()}>
                  {editingAccountId ? <Pencil size={16} /> : <Plus size={16} />}
                  {editingAccountId ? "Save account" : "Add account"}
                </button>
                {editingAccountId ? (
                  <button className="secondaryButton" onClick={clearAccountForm}>
                    Cancel
                  </button>
                ) : null}
              </div>
            </div>
            <div className="denseList">
              {accounts.map((account) => (
                <button className={selectedAccountId === account.id ? "accountRow selected" : "accountRow"} key={account.id} onClick={() => beginEditAccount(account)}>
                  <Landmark size={16} />
                  <span>
                    {account.display_name}
                    {account.institution_name ? <small>{account.institution_name}</small> : null}
                  </span>
                  <small>{readableAccountType(account.account_type)}</small>
                  <Pencil size={14} />
                </button>
              ))}
            </div>
          </section>

          <section className="toolPanel">
            <PanelTitle icon={FileUp} title="Imports" subtitle="Preview first, then commit clean rows into the ledger." />
            <div className="compactForm">
              <select value={selectedAccountId} onChange={(event) => setSelectedAccountId(event.target.value ? Number(event.target.value) : "")}>
                <option value="">Choose account</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.display_name}
                  </option>
                ))}
              </select>
              <input type="file" accept=".csv" onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)} />
              <div className="buttonRow">
                <button className="secondaryButton" onClick={() => void previewSelectedImport()}>
                  <Search size={16} />
                  Preview
                </button>
                <button className="primaryButton" onClick={() => void commitSelectedImport()} disabled={!importPreview}>
                  <ArrowDownToLine size={16} />
                  Commit
                </button>
              </div>
            </div>
            <div className="previewPanel">
              {importPreview ? (
                <>
                  <div className="previewMeta">
                    <strong>{importPreview.preset_type}</strong>
                    <span>{selectedAccount?.display_name}</span>
                  </div>
                  <div className="previewRows">
                    {previewRows.map((row, index) => (
                      <div className="previewRow" key={`${row.row_index ?? index}`}>
                        <span>{String(row.raw_description ?? row.description ?? row.symbol ?? "Row")}</span>
                        <strong>{String(row.amount ?? row.market_value ?? "")}</strong>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <p className="emptyText">Select an account and CSV to see the normalized rows before they touch the ledger.</p>
              )}
            </div>
          </section>

          <section className="toolPanel">
            <PanelTitle icon={WalletCards} title="Transfer Review" subtitle="Find bank transfers and credit card payments so reports do not count them as spending." />
            <div className="transferIntro">
              <div>
                <strong>{transferCandidates.length} open matches</strong>
                <span>Matches use equal-and-opposite amounts across accounts within five days.</span>
              </div>
              <button className="primaryButton" onClick={() => void detectTransfers()}>
                <RefreshCw size={16} />
                Find transfers/payments
              </button>
            </div>
            <div className="transferList">
              {transferCandidates.map((candidate) => {
                const fromAccount = accounts.find((account) => account.id === candidate.from_transaction.account_id);
                const toAccount = accounts.find((account) => account.id === candidate.to_transaction.account_id);
                return (
                  <article className="transferCard" key={candidate.id}>
                    <div className="transferCardTop">
                      <div>
                        <strong>{readableAccountType(candidate.suggested_type)}</strong>
                        <span>{candidate.match_confidence}% confidence</span>
                      </div>
                      <span className="statusBadge suggested">Suggested</span>
                    </div>
                    <div className="transferPair">
                      <div>
                        <small>Money out</small>
                        <strong>{fromAccount?.display_name ?? `Account ${candidate.from_transaction.account_id}`}</strong>
                        <span>{candidate.from_transaction.transaction_date} / {candidate.from_transaction.raw_description}</span>
                        <b>{formatMoney(candidate.from_transaction.amount_cents)}</b>
                      </div>
                      <div>
                        <small>Money in</small>
                        <strong>{toAccount?.display_name ?? `Account ${candidate.to_transaction.account_id}`}</strong>
                        <span>{candidate.to_transaction.transaction_date} / {candidate.to_transaction.raw_description}</span>
                        <b>{formatMoney(candidate.to_transaction.amount_cents)}</b>
                      </div>
                    </div>
                    <div className="reviewActions">
                      <button className="dangerTextButton" onClick={() => void rejectTransferCandidate(candidate.id)}>
                        Reject
                      </button>
                      <button className="primaryButton" onClick={() => void confirmTransferCandidate(candidate.id)}>
                        <CheckCircle2 size={16} />
                        Confirm match
                      </button>
                    </div>
                  </article>
                );
              })}
              {transferCandidates.length === 0 ? <p className="emptyText">No transfer suggestions yet. Import the matching bank/card files, then run the finder.</p> : null}
            </div>
          </section>

          <section className="toolPanel">
            <PanelTitle icon={ListChecks} title="Review Inbox" subtitle={`${reviewTransactions.length} items need a human decision.`} />
            {visibleReviewTransactions.length > 0 ? (
              <div className="selectionToolbar">
                <span>{selectedVisibleReviewIds.length} selected</span>
                <button className="dangerTextButton" onClick={() => requestBulkTransactionDelete(selectedVisibleReviewIds)} disabled={selectedVisibleReviewIds.length === 0}>
                  Delete selected
                </button>
                <button className="secondaryButton" onClick={() => setSelectedTransactionIds((current) => current.filter((id) => !visibleReviewIds.includes(id)))}>
                  Clear
                </button>
              </div>
            ) : null}
            {lastSavedRule ? (
              <div className="ruleApplyPanel">
                <div>
                  <strong>Rule saved for "{lastSavedRule.matchText}"</strong>
                  <span>Apply it now to categorize and confirm matching transactions.</span>
                </div>
                <div className="buttonRow">
                  <button className="secondaryButton" onClick={() => void applySavedRule("unreviewed")}>
                    Apply to unreviewed
                  </button>
                  <button className="secondaryButton" onClick={() => void applySavedRule("all")}>
                    Apply to previous
                  </button>
                </div>
              </div>
            ) : null}
            <div className="reviewEditor">
              {visibleReviewTransactions.map((transaction) => (
                <article className={selectedTransactionIds.includes(transaction.id) ? "reviewCard selected" : "reviewCard"} key={transaction.id}>
                  <div className="reviewCardTop">
                    <input
                      type="checkbox"
                      checked={selectedTransactionIds.includes(transaction.id)}
                      onChange={(event) => toggleTransactionSelection(transaction.id, visibleReviewIds, (event.nativeEvent as MouseEvent).shiftKey)}
                      title="Select transaction. Hold Shift to select a range."
                    />
                    <div>
                      <strong>{transaction.raw_description}</strong>
                      <span className="reviewMetaRow"><small>{transaction.transaction_date}</small><span className={reviewStatusClass(transaction.review_status)}>{reviewStatusLabel(transaction.review_status)}</span></span>
                    </div>
                    <span className={transaction.amount_cents < 0 ? "amount negative" : "amount positive"}>{formatMoney(transaction.amount_cents)}</span>
                  </div>
                  <div className="reviewControls">
                    <select
                      value={transaction.transaction_type}
                      onChange={(event) => void updateTransaction(transaction.id, { transaction_type: event.target.value })}
                    >
                      {transactionTypes.map((type) => (
                        <option key={type.value} value={type.value}>
                          {type.label}
                        </option>
                      ))}
                    </select>
                    <select
                      value={transaction.category_id ?? ""}
                      onChange={(event) => void updateTransaction(transaction.id, { category_id: event.target.value ? Number(event.target.value) : null })}
                    >
                      <option value="">No category</option>
                      {categories.map((category) => (
                        <option key={category.id} value={category.id}>
                          {category.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <textarea
                    value={transaction.user_note ?? ""}
                    onChange={(event) => void updateTransaction(transaction.id, { user_note: event.target.value })}
                    placeholder="Add your own context, like what you actually bought."
                    rows={2}
                  />
                  <div className="ruleHint">
                    <strong>Rule to save:</strong> future descriptions containing "{suggestedRuleText(transaction.raw_description)}" will use {readableAccountType(transaction.transaction_type)}
                    {transaction.category_id ? ` / ${categories.find((category) => category.id === transaction.category_id)?.label ?? "selected category"}` : " / no category"}. Applying it now also confirms matching rows.
                  </div>
                  <div className="reviewActions">
                    <button className="secondaryButton" onClick={() => void saveRuleFromTransaction(transaction)}>
                      <Sparkles size={16} />
                      Save rule
                    </button>
                    <button className="dangerTextButton" onClick={() => requestDelete({ kind: "transaction", id: transaction.id, label: transaction.raw_description })}>
                      Delete
                    </button>
                    <button className="primaryButton" onClick={() => void confirmTransaction(transaction)}>
                      <CheckCircle2 size={16} />
                      Confirm
                    </button>
                  </div>
                </article>
              ))}
              {reviewTransactions.length === 0 ? <p className="emptyText">No items waiting for review. New imports will appear here before reports rely on them.</p> : null}
            </div>
            {rules.length > 0 ? (
              <div className="savedRulesPanel">
                <strong>Saved rules</strong>
                {rules.slice(0, 5).map((rule) => {
                  const category = categories.find((item) => item.id === rule.category_id);
                  return (
                    <div className="savedRuleRow" key={rule.id}>
                      <div>
                        <span>{rule.match_text}</span>
                        <small>{category?.label ?? "Unknown category"} / {readableAccountType(rule.suggested_transaction_type)}</small>
                      </div>
                      <button className="secondaryButton" onClick={() => void applyRule(rule.id, "unreviewed")}>
                        Apply to unreviewed
                      </button>
                      <button className="secondaryButton" onClick={() => void applyRule(rule.id, "all")}>
                        Apply to previous
                      </button>
                    </div>
                  );
                })}
              </div>
            ) : null}
          </section>

          <section className="toolPanel">
            <PanelTitle icon={PiggyBank} title="Categories" subtitle="Spending buckets for expense reporting. Add or rename them as your life changes." />
            <div className="compactForm">
              <div className="buttonRow">
                <input value={newCategoryLabel} onChange={(event) => setNewCategoryLabel(event.target.value)} placeholder="New category name" />
                <button className="primaryButton" onClick={() => void createCategory()}>
                  <Plus size={16} />
                  Add
                </button>
              </div>
              {editingCategoryId ? (
                <div className="inlineEdit">
                  <input value={editingCategoryLabel} onChange={(event) => setEditingCategoryLabel(event.target.value)} placeholder="Rename category" />
                  <button className="secondaryButton" onClick={() => void updateCategory()}>
                    Save rename
                  </button>
                  <button
                    className="ghostButton"
                    onClick={() => {
                      setEditingCategoryId(null);
                      setEditingCategoryLabel("");
                    }}
                  >
                    Cancel
                  </button>
                </div>
              ) : null}
            </div>
            <div className="categoryGrid">
              {categories.map((category) => (
                <button
                  className={editingCategoryId === category.id ? "categoryPill editing" : "categoryPill"}
                  key={category.id}
                  onClick={() => {
                    setEditingCategoryId(category.id);
                    setEditingCategoryLabel(category.label);
                  }}
                >
                  {category.label}
                </button>
              ))}
            </div>
          </section>
        </section>

        <section className="ledgerPanel">
          <PanelTitle icon={ReceiptText} title="Recent Transactions" subtitle="The ledger after imports, edits, and review decisions." />
          {recentTransactions.length > 0 ? (
            <div className="selectionToolbar">
              <span>{selectedRecentTransactionIds.length} selected</span>
              <button className="dangerTextButton" onClick={() => requestBulkTransactionDelete(selectedRecentTransactionIds)} disabled={selectedRecentTransactionIds.length === 0}>
                Delete selected
              </button>
              <button className="secondaryButton" onClick={() => setSelectedTransactionIds((current) => current.filter((id) => !recentTransactionIds.includes(id)))}>
                Clear
              </button>
            </div>
          ) : null}
          <div className="ledgerTable">
            <div className="ledgerHeader">
              <span>Select</span>
              <span>Date</span>
              <span>Description</span>
              <span>Type</span>
              <span>Category</span>
              <span>Status</span>
              <span>Amount</span>
              <span>Action</span>
            </div>
            {recentTransactions.map((transaction) => {
              const category = categories.find((item) => item.id === transaction.category_id);
              return (
                <div className={selectedTransactionIds.includes(transaction.id) ? "ledgerRow selected" : "ledgerRow"} key={transaction.id}>
                  <input
                    type="checkbox"
                    checked={selectedTransactionIds.includes(transaction.id)}
                    onChange={(event) => toggleTransactionSelection(transaction.id, recentTransactionIds, (event.nativeEvent as MouseEvent).shiftKey)}
                    title="Select transaction. Hold Shift to select a range."
                  />
                  <span>{transaction.transaction_date}</span>
                  <strong className="ledgerDescription">
                    {transaction.raw_description}
                    {transaction.user_note ? <small>{transaction.user_note}</small> : null}
                  </strong>
                  <span>{readableAccountType(transaction.transaction_type)}</span>
                  <span>{category?.label ?? "Uncategorized"}</span>
                  <span className={reviewStatusClass(transaction.review_status)}>{reviewStatusLabel(transaction.review_status)}</span>
                  <span className={transaction.amount_cents < 0 ? "amount negative" : "amount positive"}>{formatMoney(transaction.amount_cents)}</span>
                  <button className="dangerTextButton" onClick={() => requestDelete({ kind: "transaction", id: transaction.id, label: transaction.raw_description })}>
                    Delete
                  </button>
                </div>
              );
            })}
            {recentTransactions.length === 0 ? <p className="emptyText">No transactions yet. Import a CSV to start the ledger.</p> : null}
          </div>
        </section>
      </main>
    </div>
  );
}

function reportTitle(activeTab: string) {
  if (activeTab === "Spending") return "Where your money is going";
  if (activeTab === "Income") return "Income vs expenses";
  if (activeTab === "Net Worth") return "Investment-backed net worth";
  if (activeTab === "Cash Flow") return "Cash flow by month";
  return "Financial report center";
}

function ReportSurface({
  activeTab,
  income,
  expenses,
  net,
  categoryTotals,
  cashFlowRows,
  netWorthAccounts,
  allocationRows,
  holdingRows,
  onUpdateHoldingDescription,
  onRequestDelete,
}: {
  activeTab: string;
  income: number;
  expenses: number;
  net: number;
  categoryTotals: CategoryTotal[];
  cashFlowRows: MonthlyCashFlow[];
  netWorthAccounts: NetWorthAccount[];
  allocationRows: AllocationRow[];
  holdingRows: HoldingRow[];
  onUpdateHoldingDescription: (symbol: string | null, userDescription: string) => Promise<void>;
  onRequestDelete: (target: DeleteTarget) => void;
}) {
  if (activeTab === "Spending") {
    return <SpendingReport rows={categoryTotals} />;
  }
  if (activeTab === "Income") {
    return <IncomeReport income={income} expenses={expenses} net={net} />;
  }
  if (activeTab === "Net Worth") {
    return <NetWorthReport accounts={netWorthAccounts} allocationRows={allocationRows} holdingRows={holdingRows} onUpdateHoldingDescription={onUpdateHoldingDescription} onRequestDelete={onRequestDelete} />;
  }
  if (activeTab === "Cash Flow") {
    return <MonthlyCashFlowReport rows={cashFlowRows} income={income} expenses={expenses} net={net} />;
  }
  return (
    <div className="reportStack">
      <CashFlowGraphic income={income} expenses={expenses} net={net} />
      <div className="reportMiniGrid">
        <ReportStat label="Tracked income" value={formatMoney(income)} />
        <ReportStat label="Tracked expenses" value={formatMoney(expenses)} />
        <ReportStat label="Tracked net" value={formatMoney(net)} />
      </div>
    </div>
  );
}

function SpendingReport({ rows }: { rows: CategoryTotal[] }) {
  const max = Math.max(...rows.map((row) => row.amount_cents), 1);
  return (
    <div className="reportStack">
      <div className="barList">
        {rows.map((row) => (
          <div className="barRow" key={row.category}>
            <div>
              <strong>{row.category}</strong>
              <span>{formatMoney(row.amount_cents)}</span>
            </div>
            <div className="barTrack">
              <div style={{ width: `${Math.max(4, Math.round((row.amount_cents / max) * 100))}%` }} />
            </div>
          </div>
        ))}
        {rows.length === 0 ? <p className="emptyText">No categorized expenses yet. Categorize and confirm transactions to populate this report.</p> : null}
      </div>
    </div>
  );
}

function MonthlyCashFlowReport({ rows, income, expenses, net }: { rows: MonthlyCashFlow[]; income: number; expenses: number; net: number }) {
  return (
    <div className="reportStack">
      <CashFlowGraphic income={income} expenses={expenses} net={net} />
      <div className="reportTable">
        <div className="reportTableHeader">
          <span>Month</span>
          <span>Income</span>
          <span>Expenses</span>
          <span>Net</span>
        </div>
        {rows.slice(-6).map((row) => (
          <div className="reportTableRow" key={row.month}>
            <strong>{row.month}</strong>
            <span>{formatMoney(row.income_cents)}</span>
            <span>{formatMoney(row.expense_cents)}</span>
            <span className={row.net_cents < 0 ? "amount negative" : "amount positive"}>{formatMoney(row.net_cents)}</span>
          </div>
        ))}
        {rows.length === 0 ? <p className="emptyText">No income or expense transactions yet.</p> : null}
      </div>
    </div>
  );
}

function IncomeReport({ income, expenses, net }: { income: number; expenses: number; net: number }) {
  const max = Math.max(income, expenses, Math.abs(net), 1);
  return (
    <div className="reportStack">
      <div className="compareGrid">
        <CompareCard label="Income" value={income} max={max} tone="green" />
        <CompareCard label="Expenses" value={expenses} max={max} tone="red" />
        <CompareCard label="Net" value={net} max={max} tone={net < 0 ? "red" : "green"} />
      </div>
      <p className="emptyText">Income uses transactions marked as income. Expenses use transactions marked as expense, with refunds reducing total expenses.</p>
    </div>
  );
}

function NetWorthReport({
  accounts,
  allocationRows,
  holdingRows,
  onUpdateHoldingDescription,
  onRequestDelete,
}: {
  accounts: NetWorthAccount[];
  allocationRows: AllocationRow[];
  holdingRows: HoldingRow[];
  onUpdateHoldingDescription: (symbol: string | null, userDescription: string) => Promise<void>;
  onRequestDelete: (target: DeleteTarget) => void;
}) {
  const total = accounts.reduce((sum, row) => sum + row.market_value_cents, 0);
  const max = Math.max(...accounts.map((row) => row.market_value_cents), 1);
  return (
    <div className="reportStack">
      <div className="reportMiniGrid">
        <ReportStat label="Latest investment value" value={formatMoney(total)} />
        <ReportStat label="Accounts with snapshots" value={String(accounts.length)} />
        <ReportStat label="Allocation groups" value={String(allocationRows.length)} />
      </div>
      <div className="barList">
        {accounts.map((row) => (
          <div className="barRow" key={row.account_id}>
            <div>
              <strong>{row.account}</strong>
              <span>{formatMoney(row.market_value_cents)} / {row.latest_date}</span>
            </div>
            <div className="barTrack blue">
              <div style={{ width: `${Math.max(4, Math.round((row.market_value_cents / max) * 100))}%` }} />
            </div>
          </div>
        ))}
        {accounts.length === 0 ? <p className="emptyText">No investment snapshots yet. Commit a brokerage positions CSV to populate net worth.</p> : null}
      </div>
      <div className="holdingsPanel">
        <div>
          <strong>Holding details</strong>
          <span>Latest imported rows used for investment net worth. Descriptions you edit are stored locally by symbol.</span>
        </div>
        <div className="holdingsTable">
          <div className="holdingsHeader">
            <span>Account</span>
            <span>Symbol</span>
            <span>Description</span>
            <span>Quantity</span>
            <span>Price</span>
            <span>Price date</span>
            <span>Value</span>
            <span>Action</span>
          </div>
          {holdingRows.slice(0, 12).map((row) => (
            <div className="holdingsRow" key={row.id}>
              <span>{row.account}</span>
              <strong>{row.symbol || "Holding"}</strong>
              <div className="holdingDescriptionEdit">
                <input
                  defaultValue={row.user_description ?? row.csv_description ?? ""}
                  onBlur={(event) => void updateIfChanged(row, event.currentTarget.value, onUpdateHoldingDescription)}
                  placeholder="Add your description"
                />
                {row.csv_description ? <small>CSV: {row.csv_description}</small> : null}
              </div>
              <span>{row.quantity ?? "-"}</span>
              <span>{row.display_price_cents == null ? "-" : formatMoney(row.display_price_cents)}</span>
              <span>{row.price_date}</span>
              <span>{formatMoney(row.display_market_value_cents)}</span>
              <button className="dangerTextButton" onClick={() => onRequestDelete({ kind: "holding", id: row.id, label: `${row.symbol || row.description || "Holding"} in ${row.account}` })}>
                Delete
              </button>
            </div>
          ))}
          {holdingRows.length === 0 ? <p className="emptyText">No holdings rows to inspect yet.</p> : null}
        </div>
      </div>
    </div>
  );
}

function CompareCard({ label, value, max, tone }: { label: string; value: number; max: number; tone: "green" | "red" }) {
  return (
    <div className={`compareCard ${tone}`}>
      <span>{label}</span>
      <strong>{formatMoney(value)}</strong>
      <div>
        <i style={{ width: `${Math.max(4, Math.round((Math.abs(value) / max) * 100))}%` }} />
      </div>
    </div>
  );
}

async function updateIfChanged(row: HoldingRow, nextDescription: string, onUpdate: (symbol: string | null, userDescription: string) => Promise<void>) {
  const previous = row.user_description ?? row.csv_description ?? "";
  if (nextDescription.trim() === previous.trim()) {
    return;
  }
  await onUpdate(row.symbol, nextDescription.trim());
}

function ReportStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="reportStat">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MetricTile({ label, value, tone }: { label: string; value: string; tone: "green" | "red" | "neutral" }) {
  return (
    <div className={`metricTile ${tone}`}>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function suggestedRuleText(description: string) {
  const cleaned = description.replace(/[^a-zA-Z0-9\s*&]/g, " ").replace(/\s+/g, " ").trim();
  return cleaned.split(" ").slice(0, 3).join(" ").toUpperCase() || description.slice(0, 40).toUpperCase();
}

function PanelTitle({ icon: Icon, title, subtitle }: { icon: typeof WalletCards; title: string; subtitle: string }) {
  return (
    <div className="panelTitle">
      <Icon size={18} />
      <div>
        <h3>{title}</h3>
        <p>{subtitle}</p>
      </div>
    </div>
  );
}

function CashFlowGraphic({ income, expenses, net }: { income: number; expenses: number; net: number }) {
  const max = Math.max(income, expenses, Math.abs(net), 1);
  const incomeWidth = Math.max(18, Math.round((income / max) * 100));
  const expenseWidth = Math.max(18, Math.round((expenses / max) * 100));
  const netWidth = Math.max(18, Math.round((Math.abs(net) / max) * 100));

  return (
    <div className="flowCanvas" aria-label="Cash flow summary">
      <div className="flowColumn">
        <span>Paychecks</span>
        <strong>{formatMoney(income)}</strong>
        <div className="flowBar income" style={{ height: `${incomeWidth}%` }} />
      </div>
      <div className="flowStream">
        <div className="streamBand blue" />
        <div className="streamBand green" />
        <div className="streamBand coral" />
      </div>
      <div className="flowColumn">
        <span>Income</span>
        <strong>{formatMoney(income)}</strong>
        <div className="flowBar net" style={{ height: `${incomeWidth}%` }} />
      </div>
      <div className="flowStream split">
        <div className="streamBand yellow" />
        <div className="streamBand rose" />
        <div className="streamBand slate" />
      </div>
      <div className="flowOutcomes">
        <div className="outcomeRow">
          <div>
            <strong>Savings</strong>
            <span>{formatMoney(Math.max(net, 0))}</span>
          </div>
          <div className="outcomeTrack">
            <div style={{ width: `${netWidth}%` }} />
          </div>
        </div>
        <div className="outcomeRow">
          <div>
            <strong>Expenses</strong>
            <span>{formatMoney(expenses)}</span>
          </div>
          <div className="outcomeTrack expense">
            <div style={{ width: `${expenseWidth}%` }} />
          </div>
        </div>
      </div>
    </div>
  );
}
