import {
  AlertCircle,
  ArrowDownToLine,
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
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

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
  institution_name: string | null;
  account_name: string;
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

type ImportAnalysis = {
  preset_type: string;
  suggested_account_id: number | null;
  match_confidence: number;
  reason: string;
  proposed_account: {
    institution_name: string | null;
    display_name: string;
    account_type: string;
    currency: string;
    last_four: string | null;
  };
  warnings: string[];
};

type CategorizedHistoryRow = {
  row_index: string;
  account: string;
  posted_date: string;
  payee: string;
  amount: string;
  category: string;
  errors?: string[];
};

type CategorizedHistoryImportResponse =
  | { needs_review: true; filename: string; rows: CategorizedHistoryRow[] }
  | { needs_review?: false; inserted: number; skipped: number; accounts_created: number; categories_created: number; warnings: string[] };

type ToastState = {
  tone: "success" | "error" | "info";
  message: string;
};

type DeleteTarget =
  | { kind: "transaction"; id: number; label: string }
  | { kind: "transaction_bulk"; ids: number[]; label: string }
  | { kind: "account"; id: number; label: string }
  | { kind: "account_bulk"; ids: number[]; label: string }
  | { kind: "holding"; id: number; label: string }
  | { kind: "holding_bulk"; ids: number[]; label: string };

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
type TransactionSortKey = "date" | "amount";
type SortDirection = "asc" | "desc";
type ReportPeriod = "this_month" | "this_year" | "last_12_months" | "all";
type FilterOption = { value: string; label: string };
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

type AppView = "overview" | "all-accounts" | "account" | "review" | "reports" | "settings";

const primaryNavItems: Array<{ id: AppView; label: string; icon: typeof LayoutDashboard }> = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "reports", label: "Reports", icon: TrendingUp },
  { id: "all-accounts", label: "All Accounts", icon: Landmark },
  { id: "review", label: "Review", icon: ListChecks },
  { id: "settings", label: "Settings", icon: Settings },
];

const reportTabs = ["Reports", "Cash Flow", "Spending", "Income", "Net Worth"];

const monthOptions: FilterOption[] = [
  { value: "01", label: "January" },
  { value: "02", label: "February" },
  { value: "03", label: "March" },
  { value: "04", label: "April" },
  { value: "05", label: "May" },
  { value: "06", label: "June" },
  { value: "07", label: "July" },
  { value: "08", label: "August" },
  { value: "09", label: "September" },
  { value: "10", label: "October" },
  { value: "11", label: "November" },
  { value: "12", label: "December" },
];

const uncategorizedFilterValue = "__uncategorized__";
const TRANSACTION_PAGE_SIZE = 100;

const reportPeriodOptions: Array<{ value: ReportPeriod; label: string }> = [
  { value: "this_month", label: "This month" },
  { value: "this_year", label: "This year" },
  { value: "last_12_months", label: "Last 12 months" },
  { value: "all", label: "All time" },
];

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

const formatShortDate = (value: string | null | undefined) => {
  if (!value) return "-";
  const [datePart] = value.split("T");
  const [year, month, day] = datePart.split("-");
  if (!year || !month || !day) return value;
  return `${month}/${day}/${year.slice(-2)}`;
};

const readableAccountType = (value: string) =>
  ({
    checking: "Checking",
    savings: "Savings",
    credit_card: "Credit card",
    cash: "Cash",
    other: "Other",
    loan: "Loan",
    brokerage: "Brokerage",
    retirement: "Retirement",
  })[value] ?? value.replace(/_/g, " ");

const bankAccountTypes = new Set(["checking", "savings", "cash", "other", "loan"]);
const creditCardAccountTypes = new Set(["credit_card"]);
const brokerageAccountTypes = new Set(["brokerage", "retirement"]);

function isBrokerageAccountType(accountType: string): boolean {
  return brokerageAccountTypes.has(accountType);
}

function accountGroupLabel(accountType: string): string {
  if (creditCardAccountTypes.has(accountType)) return "Credit Cards";
  if (brokerageAccountTypes.has(accountType)) return "Brokerages";
  return "Bank Accounts";
}

const accountTypeOptions = [
  { value: "checking", label: "Checking (Bank Accounts)" },
  { value: "savings", label: "Savings (Bank Accounts)" },
  { value: "cash", label: "Cash (Bank Accounts)" },
  { value: "loan", label: "Loan (Bank Accounts)" },
  { value: "other", label: "Other (Bank Accounts)" },
  { value: "credit_card", label: "Credit card (Credit Cards)" },
  { value: "brokerage", label: "Brokerage (Brokerages)" },
  { value: "retirement", label: "Retirement (Brokerages)" },
];

const reviewStatusLabel = (value: string) =>
  ({
    needs_review: "Needs review",
    suggested: "Suggested",
    possible_duplicate: "Possible duplicate",
    confirmed: "Confirmed",
  })[value] ?? readableAccountType(value);

const reviewStatusClass = (value: string) => `statusBadge ${value.replace(/_/g, "-")}`;

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new Error(await readableApiError(response, path));
  }
  return parseApiJson<T>(response, path);
}

function apiUrl(path: string): string {
  if (window.location.port === "5173" && path.startsWith("/api/")) {
    return `http://${window.location.hostname}:8000${path}`;
  }
  return path;
}

async function readableApiError(response: Response, path: string): Promise<string> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return `${path} returned ${response.status} ${response.statusText || "with a non-JSON response"}. Make sure the backend is running at http://127.0.0.1:8000.`;
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

async function parseApiJson<T>(response: Response, path: string): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    throw new Error(`${path} returned frontend HTML instead of API data. The backend may need to be restarted at http://127.0.0.1:8000.`);
  }
  return response.json() as Promise<T>;
}

function visibleIdsFilter(visibleIds: number[], selectedIds: number[]) {
  return visibleIds.filter((id) => selectedIds.includes(id));
}

function toggleValue<T>(current: T[], value: T) {
  return current.includes(value) ? current.filter((item) => item !== value) : [...current, value];
}

function monthKeyFromDate(value: string): string {
  return value.slice(0, 7);
}

function isTransactionInReportPeriod(transactionDate: string, period: ReportPeriod, now = new Date()): boolean {
  if (period === "all") {
    return true;
  }
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const thisMonth = `${year}-${month}`;
  const thisYear = String(year);
  if (period === "this_month") {
    return monthKeyFromDate(transactionDate) === thisMonth;
  }
  if (period === "this_year") {
    return transactionDate.slice(0, 4) === thisYear;
  }
  const start = new Date(now.getFullYear(), now.getMonth() - 11, 1);
  const startKey = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, "0")}`;
  return monthKeyFromDate(transactionDate) >= startKey && monthKeyFromDate(transactionDate) <= thisMonth;
}

function isMonthInReportPeriod(month: string, period: ReportPeriod, now = new Date()): boolean {
  if (period === "all") {
    return true;
  }
  const year = now.getFullYear();
  const monthNum = String(now.getMonth() + 1).padStart(2, "0");
  const thisMonth = `${year}-${monthNum}`;
  if (period === "this_month") {
    return month === thisMonth;
  }
  if (period === "this_year") {
    return month.startsWith(String(year));
  }
  const start = new Date(now.getFullYear(), now.getMonth() - 11, 1);
  const startKey = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, "0")}`;
  return month >= startKey && month <= thisMonth;
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
  const [importAnalysis, setImportAnalysis] = useState<ImportAnalysis | null>(null);
  const [importWorkspaceTab, setImportWorkspaceTab] = useState<"smart" | "manual">("smart");
  const [activeTab, setActiveTab] = useState("Cash Flow");
  const [activeView, setActiveView] = useState<AppView>("overview");
  const [focusedAccountId, setFocusedAccountId] = useState<number | null>(null);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [categoryEditor, setCategoryEditor] = useState<{ transactionId: number; query: string } | null>(null);
  const [editingAccountId, setEditingAccountId] = useState<number | null>(null);
  const [newCategoryLabel, setNewCategoryLabel] = useState("");
  const [editingCategoryId, setEditingCategoryId] = useState<number | null>(null);
  const [editingCategoryLabel, setEditingCategoryLabel] = useState("");
  const [lastSavedRule, setLastSavedRule] = useState<SavedRuleAction | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [selectedTransactionIds, setSelectedTransactionIds] = useState<number[]>([]);
  const [lastSelectedTransactionId, setLastSelectedTransactionId] = useState<number | null>(null);
  const [selectedAccountIds, setSelectedAccountIds] = useState<number[]>([]);
  const [lastSelectedAccountId, setLastSelectedAccountId] = useState<number | null>(null);
  const [selectedHoldingIds, setSelectedHoldingIds] = useState<number[]>([]);
  const [lastSelectedHoldingId, setLastSelectedHoldingId] = useState<number | null>(null);
  const [appImportFile, setAppImportFile] = useState<File | null>(null);
  const [categorizedHistoryFile, setCategorizedHistoryFile] = useState<File | null>(null);
  const [categorizedHistoryFilename, setCategorizedHistoryFilename] = useState("");
  const [categorizedHistoryRows, setCategorizedHistoryRows] = useState<CategorizedHistoryRow[]>([]);
  const [bulkReviewCategoryId, setBulkReviewCategoryId] = useState<number | "">("");
  const [bulkReviewType, setBulkReviewType] = useState("expense");
  const [selectedTransactionAccountFilters, setSelectedTransactionAccountFilters] = useState<number[]>([]);
  const [selectedTransactionMonthFilters, setSelectedTransactionMonthFilters] = useState<string[]>([]);
  const [selectedTransactionYearFilters, setSelectedTransactionYearFilters] = useState<string[]>([]);
  const [selectedTransactionCategoryFilters, setSelectedTransactionCategoryFilters] = useState<string[]>([]);
  const [transactionFiltersInitialized, setTransactionFiltersInitialized] = useState(false);
  const [transactionSortKey, setTransactionSortKey] = useState<TransactionSortKey>("date");
  const [transactionSortDirection, setTransactionSortDirection] = useState<SortDirection>("desc");
  const [transactionPage, setTransactionPage] = useState(1);
  const [focusedTransactionId, setFocusedTransactionId] = useState<number | null>(null);
  const [editingTransactionId, setEditingTransactionId] = useState<number | null>(null);
  const [reportPeriod, setReportPeriod] = useState<ReportPeriod>("this_year");
  const [accountForm, setAccountForm] = useState({
    institution_name: "",
    display_name: "",
    account_type: "checking",
    last_four: "",
  });

  useEffect(() => {
    void loadBootstrap();
  }, []);

  useEffect(() => {
    if (transactionFiltersInitialized || transactions.length === 0) {
      return;
    }
    setSelectedTransactionAccountFilters(accounts.map((account) => account.id));
    setSelectedTransactionMonthFilters(monthOptions.map((month) => month.value));
    setSelectedTransactionYearFilters(Array.from(new Set(transactions.map((transaction) => transaction.transaction_date.slice(0, 4)).filter(Boolean))));
    setSelectedTransactionCategoryFilters([...categories.map((category) => String(category.id)), uncategorizedFilterValue]);
    setTransactionFiltersInitialized(true);
  }, [accounts, categories, transactions, transactionFiltersInitialized]);

  useEffect(() => {
    setTransactionPage(1);
  }, [
    activeView,
    focusedAccountId,
    selectedTransactionAccountFilters,
    selectedTransactionMonthFilters,
    selectedTransactionYearFilters,
    selectedTransactionCategoryFilters,
    transactionSortKey,
    transactionSortDirection,
  ]);
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
    setImportWorkspaceTab("manual");
    setAccountForm({
      institution_name: account.institution_name ?? "",
      display_name: account.display_name,
      account_type: account.account_type,
      last_four: account.last_four ?? "",
    });
  }

  function chooseImportFile(file: File | null) {
    setSelectedFile(file);
    setImportPreview(null);
    setImportAnalysis(null);
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
      try {
        await loadData();
      } catch (refreshError) {
        showToast({
          tone: "info",
          message: `Account saved, but the dashboard refresh failed: ${refreshError instanceof Error ? refreshError.message : "refresh unavailable"}`,
        });
        return;
      }
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
      const response = await fetch(apiUrl(`/api/imports/preview?account_id=${selectedAccountId}`), {
        method: "POST",
        credentials: "include",
        body: form,
      });
      if (!response.ok) {
        throw new Error(await readableApiError(response, `/api/imports/preview?account_id=${selectedAccountId}`));
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
      const response = await fetch(apiUrl(`/api/imports/commit?account_id=${selectedAccountId}`), {
        method: "POST",
        credentials: "include",
        headers: { "x-csrf-token": csrf },
        body: form,
      });
      if (!response.ok) {
        throw new Error(await readableApiError(response, `/api/imports/commit?account_id=${selectedAccountId}`));
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

  async function updateTransaction(transactionId: number, patch: Partial<Pick<TransactionRow, "category_id" | "transaction_type" | "review_status" | "user_note">>, refreshAfterSave = false) {
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
      if (refreshAfterSave) {
        await loadData();
      }
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Transaction could not be updated." });
    }
  }

  async function analyzeSelectedImport() {
    setToast(null);
    if (!selectedFile) {
      showToast({ tone: "error", message: "Choose a CSV first so the app can inspect it." });
      return;
    }
    const form = new FormData();
    form.append("file", selectedFile);
    try {
      const response = await fetch(apiUrl("/api/imports/analyze"), {
        method: "POST",
        credentials: "include",
        body: form,
      });
      if (!response.ok) {
        if (response.status === 405) {
          throw new Error("This backend is missing the CSV analysis endpoint. Restart the app with .\\run.ps1 so the latest backend code is running.");
        }
        throw new Error(await readableApiError(response, "/api/imports/analyze"));
      }
      const analysis = await parseApiJson<ImportAnalysis>(response, "/api/imports/analyze");
      setImportAnalysis(analysis);
      if (analysis.suggested_account_id) {
        setSelectedAccountId(analysis.suggested_account_id);
        showToast({ tone: "success", message: `Matched this CSV to an existing account with ${analysis.match_confidence}% confidence.` });
      } else {
        setSelectedAccountId("");
        setAccountForm({
          institution_name: analysis.proposed_account.institution_name ?? "",
          display_name: analysis.proposed_account.display_name,
          account_type: analysis.proposed_account.account_type,
          last_four: analysis.proposed_account.last_four ?? "",
        });
        showToast({ tone: "info", message: "No obvious account match found. I prefilled a new account for you to review." });
      }
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "CSV analysis failed." });
    }
  }

  async function createAccountFromAnalysis() {
    setToast(null);
    if (!importAnalysis) {
      showToast({ tone: "error", message: "Analyze a CSV before creating a suggested account." });
      return;
    }
    if (!accountForm.display_name.trim()) {
      showToast({ tone: "error", message: "Review and enter an account name before creating it." });
      return;
    }
    try {
      const result = await api<{ id: number }>("/api/accounts", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ ...accountForm, currency: importAnalysis.proposed_account.currency ?? "USD" }),
      });
      setSelectedAccountId(result.id);
      setEditingAccountId(null);
      await loadData();
      showToast({ tone: "success", message: "Suggested account created and selected for this import." });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Suggested account could not be created." });
    }
  }

  async function downloadAppExport() {
    setToast(null);
    try {
      const response = await fetch(apiUrl("/api/exports/app-data.json"), { credentials: "include" });
      if (!response.ok) {
        throw new Error(await readableApiError(response, "/api/exports/app-data.json"));
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `private-finance-app-data-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      showToast({ tone: "success", message: "App-data export downloaded. You can import this JSON back later." });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Export failed." });
    }
  }

  async function restoreAppExport() {
    setToast(null);
    if (!appImportFile) {
      showToast({ tone: "error", message: "Choose an app-data JSON export first." });
      return;
    }
    if (!window.confirm("Importing this file replaces the current accounts, transactions, holdings, rules, and import history in this local app. Continue?")) {
      return;
    }
    const form = new FormData();
    form.append("file", appImportFile);
    form.append("confirm_text", "IMPORT");
    try {
      const response = await fetch(apiUrl("/api/imports/app-data"), {
        method: "POST",
        credentials: "include",
        headers: { "x-csrf-token": csrf },
        body: form,
      });
      if (!response.ok) {
        throw new Error(await readableApiError(response, "/api/imports/app-data"));
      }
      setAppImportFile(null);
      await loadData();
      showToast({ tone: "success", message: "App data restored from export." });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Import failed." });
    }
  }

  function categorizedHistoryMissingFields(row: CategorizedHistoryRow) {
    return [
      ["Account", row.account],
      ["Posted Date", row.posted_date],
      ["Payee", row.payee],
      ["Amount", row.amount],
    ]
      .filter(([, value]) => !String(value ?? "").trim())
      .map(([label]) => label);
  }

  function updateCategorizedHistoryRow(index: number, patch: Partial<CategorizedHistoryRow>) {
    setCategorizedHistoryRows((current) => current.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch, errors: [] } : row)));
  }

  function deleteCategorizedHistoryRow(index: number) {
    setCategorizedHistoryRows((current) => current.filter((_, rowIndex) => rowIndex !== index));
  }

  async function commitReviewedCategorizedHistory() {
    setToast(null);
    const rowsWithMissingFields = categorizedHistoryRows.filter((row) => categorizedHistoryMissingFields(row).length > 0);
    if (rowsWithMissingFields.length > 0) {
      showToast({ tone: "error", message: `Fix or delete ${rowsWithMissingFields.length} categorized history rows before importing.` });
      return;
    }
    if (categorizedHistoryRows.length === 0) {
      showToast({ tone: "error", message: "There are no categorized history rows left to import." });
      return;
    }
    try {
      const result = await api<{ inserted: number; skipped: number; accounts_created: number; categories_created: number; warnings: string[] }>("/api/imports/categorized-history/reviewed", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ filename: categorizedHistoryFilename || "categorized-history", rows: categorizedHistoryRows }),
      });
      setCategorizedHistoryFile(null);
      setCategorizedHistoryFilename("");
      setCategorizedHistoryRows([]);
      await loadData();
      showToast({
        tone: "success",
        message: `Imported ${result.inserted} categorized transactions, created ${result.accounts_created} accounts and ${result.categories_created} categories. Skipped ${result.skipped} duplicates.`,
      });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Reviewed categorized history import failed." });
    }
  }

  async function importCategorizedHistory() {
    setToast(null);
    if (!categorizedHistoryFile) {
      showToast({ tone: "error", message: "Choose a categorized history spreadsheet first." });
      return;
    }
    const form = new FormData();
    form.append("file", categorizedHistoryFile);
    try {
      const response = await fetch(apiUrl("/api/imports/categorized-history"), {
        method: "POST",
        credentials: "include",
        headers: { "x-csrf-token": csrf },
        body: form,
      });
      if (!response.ok) {
        throw new Error(await readableApiError(response, "/api/imports/categorized-history"));
      }
      const result = await parseApiJson<CategorizedHistoryImportResponse>(response, "/api/imports/categorized-history");
      if (result.needs_review) {
        setCategorizedHistoryFilename(result.filename);
        setCategorizedHistoryRows(result.rows);
        showToast({ tone: "info", message: `${result.rows.filter((row) => row.errors?.length).length} rows need missing data before import.` });
        return;
      }
      setCategorizedHistoryFile(null);
      setCategorizedHistoryFilename("");
      setCategorizedHistoryRows([]);
      await loadData();
      showToast({
        tone: "success",
        message: `Imported ${result.inserted} categorized transactions, created ${result.accounts_created} accounts and ${result.categories_created} categories. Skipped ${result.skipped} duplicates.`,
      });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Categorized history import failed." });
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

  async function bulkConfirmSelectedReviewTransactions() {
    setToast(null);
    if (selectedVisibleReviewTransactions.length === 0) {
      showToast({ tone: "error", message: "Select at least one review item first." });
      return;
    }
    if (!bulkReviewCategoryId) {
      showToast({ tone: "error", message: "Choose a category before confirming selected review items." });
      return;
    }
    try {
      for (const transaction of selectedVisibleReviewTransactions) {
        await api(`/api/transactions/${transaction.id}`, {
          method: "PATCH",
          headers: { "x-csrf-token": csrf },
          body: JSON.stringify({ category_id: bulkReviewCategoryId, transaction_type: bulkReviewType, review_status: "confirmed" }),
        });
      }
      setSelectedTransactionIds((current) => current.filter((id) => !selectedVisibleReviewIds.includes(id)));
      setLastSelectedTransactionId(null);
      await loadData();
      showToast({ tone: "success", message: `Confirmed ${selectedVisibleReviewTransactions.length} selected review items.` });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Selected review items could not be confirmed." });
    }
  }

  async function bulkSaveRulesForSelectedReviewTransactions() {
    setToast(null);
    if (selectedVisibleReviewTransactions.length === 0) {
      showToast({ tone: "error", message: "Select at least one review item first." });
      return;
    }
    try {
      let created = 0;
      for (const transaction of selectedVisibleReviewTransactions) {
        const categoryId = transaction.category_id ?? (bulkReviewCategoryId || null);
        if (!categoryId) {
          continue;
        }
        await api<{ id: number }>("/api/rules", {
          method: "POST",
          headers: { "x-csrf-token": csrf },
          body: JSON.stringify({
            category_id: categoryId,
            field_name: "raw_description",
            match_text: suggestedRuleText(transaction.raw_description),
            suggested_transaction_type: transaction.transaction_type || bulkReviewType,
            priority: 100,
          }),
        });
        created += 1;
      }
      if (created === 0) {
        showToast({ tone: "error", message: "Choose a category or select rows that already have categories before saving bulk rules." });
        return;
      }
      await loadData();
      showToast({ tone: "success", message: `Saved ${created} rules from selected review items.` });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Bulk rules could not be saved." });
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

  function toggleTransactionSort(nextSortKey: TransactionSortKey) {
    if (transactionSortKey === nextSortKey) {
      setTransactionSortDirection((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }
    setTransactionSortKey(nextSortKey);
    setTransactionSortDirection("desc");
  }

  function sortIndicator(sortKey: TransactionSortKey) {
    if (transactionSortKey !== sortKey) {
      return "";
    }
    return transactionSortDirection === "asc" ? " (asc)" : " (desc)";
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

  function toggleAccountSelection(accountId: number, visibleIds: number[], shiftKey: boolean) {
    setSelectedAccountIds((current) => {
      const next = new Set(current);
      if (shiftKey && lastSelectedAccountId !== null) {
        const start = visibleIds.indexOf(lastSelectedAccountId);
        const end = visibleIds.indexOf(accountId);
        if (start >= 0 && end >= 0) {
          const [from, to] = start < end ? [start, end] : [end, start];
          visibleIds.slice(from, to + 1).forEach((id) => next.add(id));
          return Array.from(next);
        }
      }
      if (next.has(accountId)) {
        next.delete(accountId);
      } else {
        next.add(accountId);
      }
      return Array.from(next);
    });
    setLastSelectedAccountId(accountId);
  }

  function toggleHoldingSelection(holdingId: number, visibleIds: number[], shiftKey: boolean) {
    setSelectedHoldingIds((current) => {
      const next = new Set(current);
      if (shiftKey && lastSelectedHoldingId !== null) {
        const start = visibleIds.indexOf(lastSelectedHoldingId);
        const end = visibleIds.indexOf(holdingId);
        if (start >= 0 && end >= 0) {
          const [from, to] = start < end ? [start, end] : [end, start];
          visibleIds.slice(from, to + 1).forEach((id) => next.add(id));
          return Array.from(next);
        }
      }
      if (next.has(holdingId)) {
        next.delete(holdingId);
      } else {
        next.add(holdingId);
      }
      return Array.from(next);
    });
    setLastSelectedHoldingId(holdingId);
  }
  function requestBulkTransactionDelete(ids: number[]) {
    if (ids.length === 0) {
      showToast({ tone: "error", message: "Select at least one transaction before bulk delete." });
      return;
    }
    requestDelete({ kind: "transaction_bulk", ids, label: `${ids.length} selected transaction rows` });
  }

  function requestBulkAccountDelete(ids: number[]) {
    if (ids.length === 0) {
      showToast({ tone: "error", message: "Select at least one account before bulk delete." });
      return;
    }
    requestDelete({ kind: "account_bulk", ids, label: `${ids.length} selected accounts and their imported data` });
  }

  function requestBulkHoldingDelete(ids: number[]) {
    if (ids.length === 0) {
      showToast({ tone: "error", message: "Select at least one holding before bulk delete." });
      return;
    }
    requestDelete({ kind: "holding_bulk", ids, label: `${ids.length} selected holding rows` });
  }
  async function confirmDelete() {
    if (!deleteTarget) {
      return;
    }
    if (deleteConfirmText !== "DELETE") {
      showToast({ tone: "error", message: "Type DELETE to confirm removing this data." });
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
      } else if (deleteTarget.kind === "account_bulk") {
        await api("/api/accounts/bulk-delete", {
          method: "DELETE",
          headers: { "x-csrf-token": csrf },
          body: JSON.stringify({ ids: deleteTarget.ids, confirm_text: deleteConfirmText }),
        });
      } else if (deleteTarget.kind === "holding_bulk") {
        await api("/api/investments/holdings/bulk-delete", {
          method: "DELETE",
          headers: { "x-csrf-token": csrf },
          body: JSON.stringify({ ids: deleteTarget.ids, confirm_text: deleteConfirmText }),
        });
      } else {
        const path =
          deleteTarget.kind === "transaction"
            ? `/api/transactions/${deleteTarget.id}`
            : deleteTarget.kind === "account"
              ? `/api/accounts/${deleteTarget.id}`
              : `/api/investments/holdings/${deleteTarget.id}`;
        await api(path, {
          method: "DELETE",
          headers: { "x-csrf-token": csrf },
          body: JSON.stringify({ confirm_text: deleteConfirmText }),
        });
      }
      const deletedKind = deleteTarget.kind;
      setDeleteTarget(null);
      setDeleteConfirmText("");
      setSelectedTransactionIds([]);
      setLastSelectedTransactionId(null);
      setSelectedAccountIds([]);
      setLastSelectedAccountId(null);
      setSelectedHoldingIds([]);
      setLastSelectedHoldingId(null);
      await loadData();
      showToast({ tone: "success", message: deletedKind.endsWith("bulk") ? "Selected rows deleted." : "Row deleted." });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Rows could not be deleted." });
    }
  }

  const missingCategoryTransactions = transactions.filter((transaction) => transaction.transaction_type === "expense" && !transaction.category_id);
  const missingCategoryCountByAccount = useMemo(() => {
    const counts = new Map<number, number>();
    for (const transaction of missingCategoryTransactions) {
      counts.set(transaction.account_id, (counts.get(transaction.account_id) ?? 0) + 1);
    }
    return counts;
  }, [missingCategoryTransactions]);
  const accountBalances = useMemo(() => {
    const transactionBalances = new Map<number, number>();
    for (const transaction of transactions) {
      transactionBalances.set(transaction.account_id, (transactionBalances.get(transaction.account_id) ?? 0) + transaction.amount_cents);
    }
    const snapshotBalances = new Map<number, number>();
    for (const row of netWorthAccounts) {
      snapshotBalances.set(row.account_id, row.market_value_cents);
    }
    const balances = new Map<number, number>();
    for (const account of accounts) {
      if (isBrokerageAccountType(account.account_type)) {
        balances.set(account.id, snapshotBalances.get(account.id) ?? 0);
      } else {
        balances.set(account.id, transactionBalances.get(account.id) ?? 0);
      }
    }
    return balances;
  }, [accounts, netWorthAccounts, transactions]);
  const categorySuggestions = useMemo(() => {
    if (!categoryEditor) {
      return categories;
    }
    const query = categoryEditor.query.trim().toLowerCase();
    if (!query) {
      return categories;
    }
    return categories.filter((category) => category.label.toLowerCase().includes(query));
  }, [categories, categoryEditor]);

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

  const totalIncomeCents = transactions
    .filter((transaction) => transaction.transaction_type === "income" && isTransactionInReportPeriod(transaction.transaction_date, reportPeriod))
    .reduce((sum, transaction) => sum + transaction.amount_cents, 0);
  const totalExpenseCents = Math.abs(
    transactions
      .filter((transaction) => transaction.transaction_type === "expense" && isTransactionInReportPeriod(transaction.transaction_date, reportPeriod))
      .reduce((sum, transaction) => sum + transaction.amount_cents, 0),
  );
  const netIncomeCents = totalIncomeCents - totalExpenseCents;
  const savingsRate = totalIncomeCents > 0 ? Math.max(0, Math.round((netIncomeCents / totalIncomeCents) * 1000) / 10) : 0;
  const selectedAccount = accounts.find((account) => account.id === selectedAccountId);
  const focusedAccount = accounts.find((account) => account.id === focusedAccountId) ?? null;
  const analyzedAccount = accounts.find((account) => account.id === importAnalysis?.suggested_account_id);
  const previewRows = importPreview?.rows.slice(0, 6) ?? [];
  const reviewTransactions = transactions.filter((transaction) => ["needs_review", "suggested", "possible_duplicate"].includes(transaction.review_status));
  const visibleReviewTransactions = reviewTransactions.slice(0, 5);
  const bankAccounts = accounts.filter((account) => bankAccountTypes.has(account.account_type));
  const creditCardAccounts = accounts.filter((account) => creditCardAccountTypes.has(account.account_type));
  const brokerageAccounts = accounts.filter((account) => brokerageAccountTypes.has(account.account_type));
  const focusedMissingCategoryCount = focusedAccountId ? missingCategoryCountByAccount.get(focusedAccountId) ?? 0 : 0;
  const focusedAccountBalanceCents = focusedAccountId ? accountBalances.get(focusedAccountId) ?? 0 : 0;
  const transactionYears = Array.from(new Set(transactions.map((transaction) => transaction.transaction_date.slice(0, 4)).filter(Boolean))).sort((left, right) => right.localeCompare(left));
  const transactionCategoryOptions: FilterOption[] = [...categories.map((category) => ({ value: String(category.id), label: category.label })), { value: uncategorizedFilterValue, label: "Uncategorized" }];
  const filteredTransactions = (() => {
    let rows = transactions;
    if (activeView === "account" && focusedAccountId) {
      rows = rows.filter((transaction) => transaction.account_id === focusedAccountId);
    } else if (activeView === "all-accounts") {
      rows = rows.filter((transaction) => selectedTransactionAccountFilters.includes(transaction.account_id));
    }
    rows = rows
      .filter((transaction) => selectedTransactionMonthFilters.includes(transaction.transaction_date.slice(5, 7)))
      .filter((transaction) => selectedTransactionYearFilters.includes(transaction.transaction_date.slice(0, 4)))
      .filter((transaction) => selectedTransactionCategoryFilters.includes(transaction.category_id ? String(transaction.category_id) : uncategorizedFilterValue));
    return [...rows].sort((left, right) => {
      const direction = transactionSortDirection === "asc" ? 1 : -1;
      if (transactionSortKey === "amount") {
        return (left.amount_cents - right.amount_cents) * direction;
      }
      const dateCompare = left.transaction_date.localeCompare(right.transaction_date);
      return dateCompare === 0 ? (left.id - right.id) * direction : dateCompare * direction;
    });
  })();
  const transactionPageCount = Math.max(1, Math.ceil(filteredTransactions.length / TRANSACTION_PAGE_SIZE));
  const pagedTransactions = filteredTransactions.slice(0, transactionPage * TRANSACTION_PAGE_SIZE);
  const visibleReviewIds = visibleReviewTransactions.map((transaction) => transaction.id);
  const repositoryTransactionIds = filteredTransactions.map((transaction) => transaction.id);
  const selectedVisibleReviewIds = visibleIdsFilter(visibleReviewIds, selectedTransactionIds);
  const selectedVisibleReviewTransactions = visibleReviewTransactions.filter((transaction) => selectedVisibleReviewIds.includes(transaction.id));
  const selectedRepositoryTransactionIds = repositoryTransactionIds.filter((id) => selectedTransactionIds.includes(id));
  const accountIds = accounts.map((account) => account.id);
  const selectedVisibleAccountIds = accountIds.filter((id) => selectedAccountIds.includes(id));
  const visibleHoldingIds = holdingRows.slice(0, 12).map((row) => row.id);
  const selectedVisibleHoldingIds = visibleHoldingIds.filter((id) => selectedHoldingIds.includes(id));
  const periodCashFlowRows = cashFlowRows.filter((row) => isMonthInReportPeriod(row.month, reportPeriod));
  const reportIncomeCents = periodCashFlowRows.reduce((sum, row) => sum + row.income_cents, 0);
  const reportExpenseCents = periodCashFlowRows.reduce((sum, row) => sum + row.expense_cents, 0);
  const reportNetCents = periodCashFlowRows.reduce((sum, row) => sum + row.net_cents, 0);
  const periodCategoryTotals = (() => {
    const totals = new Map<string, number>();
    for (const transaction of transactions) {
      if (transaction.transaction_type !== "expense" || !transaction.category_id) {
        continue;
      }
      if (!isTransactionInReportPeriod(transaction.transaction_date, reportPeriod)) {
        continue;
      }
      const label = categories.find((category) => category.id === transaction.category_id)?.label ?? "Uncategorized";
      totals.set(label, (totals.get(label) ?? 0) + Math.abs(transaction.amount_cents));
    }
    return Array.from(totals.entries())
      .map(([category, amount_cents]) => ({ category, amount_cents }))
      .sort((left, right) => right.amount_cents - left.amount_cents);
  })();
  const netWorthCents = netWorthAccounts.reduce((sum, row) => sum + row.market_value_cents, 0);

  function openAccountView(accountId: number) {
    setFocusedAccountId(accountId);
    setSelectedAccountId(accountId);
    setActiveView("account");
    setCategoryEditor(null);
    setFocusedTransactionId(null);
    setEditingTransactionId(null);
  }

  function openImportModal(accountId?: number) {
    if (accountId) {
      setSelectedAccountId(accountId);
      setFocusedAccountId(accountId);
    } else if (focusedAccountId) {
      setSelectedAccountId(focusedAccountId);
    }
    setImportModalOpen(true);
  }

  function scrollToUncategorized() {
    const firstMissing = filteredTransactions.find((transaction) => transaction.transaction_type === "expense" && !transaction.category_id);
    if (!firstMissing) {
      return;
    }
    setFocusedTransactionId(firstMissing.id);
    document.getElementById(`transaction-row-${firstMissing.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function handleTransactionRowClick(transactionId: number) {
    if (editingTransactionId === transactionId) {
      return;
    }
    if (focusedTransactionId === transactionId) {
      setEditingTransactionId(transactionId);
      return;
    }
    setFocusedTransactionId(transactionId);
    setEditingTransactionId(null);
    setCategoryEditor(null);
  }

  return (
    <div className="appFrame">
      <aside className="sidebar">
        <div className="brandBlock">
          <strong>Private Finance</strong>
          <span>Local plan</span>
        </div>
        <nav>
          {primaryNavItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={activeView === item.id ? "navItem active" : "navItem"}
                key={item.id}
                title={item.label}
                onClick={() => {
                  setActiveView(item.id);
                  if (item.id !== "account") {
                    setFocusedAccountId(null);
                  }
                  setCategoryEditor(null);
                }}
              >
                <Icon size={16} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
        {[
          { label: "Bank Accounts", rows: bankAccounts, emptyText: "No bank accounts yet." },
          { label: "Credit Cards", rows: creditCardAccounts, emptyText: "No credit cards yet." },
          { label: "Brokerages", rows: brokerageAccounts, emptyText: "No brokerages yet." },
        ].map((section) => (
          <div className="sidebarSection" key={section.label}>
            <div className="sidebarSectionHeader">
              <span>{section.label}</span>
              <span>{formatMoney(section.rows.reduce((sum, account) => sum + (accountBalances.get(account.id) ?? 0), 0))}</span>
            </div>
            <div className="sidebarAccounts">
              {section.rows.map((account) => {
                const missingCount = missingCategoryCountByAccount.get(account.id) ?? 0;
                const isActive = activeView === "account" && focusedAccountId === account.id;
                return (
                  <button key={account.id} className={isActive ? "sidebarAccount active" : "sidebarAccount"} onClick={() => openAccountView(account.id)} title={account.display_name}>
                    <span className={missingCount > 0 ? "attentionDot" : "attentionDot hidden"} />
                    <span className="sidebarAccountName">
                      {account.display_name}
                      {account.last_four ? ` (${account.last_four})` : ""}
                    </span>
                    <span className="sidebarAccountBalance">{formatMoney(accountBalances.get(account.id) ?? 0)}</span>
                  </button>
                );
              })}
              {section.rows.length === 0 ? <p className="emptyText" style={{ color: "rgba(245,247,255,0.55)", padding: "0 12px" }}>{section.emptyText}</p> : null}
            </div>
          </div>
        ))}
        <div className="sidebarFooter">
          <button
            className="addAccountButton"
            onClick={() => {
              setImportWorkspaceTab("manual");
              setImportModalOpen(true);
            }}
          >
            <Plus size={16} />
            Add Account
          </button>
        </div>
      </aside>

      <main className="workspace">
        {toast ? (
          <div className={`toast ${toast.tone}`} style={{ margin: "16px 20px 0" }}>
            {toast.tone === "success" ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
            <span>{toast.message}</span>
          </div>
        ) : null}

        {(activeView === "overview" || activeView === "reports") && (
          <>
            <header className="topBar">
              <div className="reportTabs" role="tablist" aria-label="Report views">
                {reportTabs.map((tab) => (
                  <button className={tab === activeTab ? "reportTab active" : "reportTab"} key={tab} onClick={() => setActiveTab(tab)}>
                    {tab}
                  </button>
                ))}
              </div>
              <div className="toolbar">
                <div className="periodChips" role="group" aria-label="Report period">
                  {reportPeriodOptions.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      className={reportPeriod === option.value ? "periodChip active" : "periodChip"}
                      onClick={() => setReportPeriod(option.value)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <button className="ghostButton" title="Refresh data" onClick={() => void loadData()}>
                  <RefreshCw size={16} />
                </button>
                <button className="secondaryButton" onClick={() => openImportModal()}>
                  <FileUp size={16} />
                  File Import
                </button>
              </div>
            </header>

            <section className="metricsGrid overviewMetrics" aria-label="Financial summary">
              <MetricTile label="Income" value={formatMoney(reportIncomeCents || totalIncomeCents)} tone="green" />
              <MetricTile label="Expenses" value={formatMoney(reportExpenseCents || totalExpenseCents)} tone="red" />
              <MetricTile label="Net" value={formatMoney(reportNetCents || netIncomeCents)} tone="neutral" />
              <MetricTile label="Savings rate" value={`${savingsRate}%`} tone="neutral" />
            </section>

            <section className="contentGrid overviewContent">
              <section className="reportSurface">
                <div className="sectionHeader">
                  <div>
                    <span className="eyebrow">{activeTab}</span>
                    <h2>{reportTitle(activeTab)}</h2>
                    <p className="reportPeriodHint">Showing {reportPeriodOptions.find((option) => option.value === reportPeriod)?.label.toLowerCase()} totals.</p>
                  </div>
                </div>
                <ReportSurface
                  activeTab={activeTab}
                  income={reportIncomeCents}
                  expenses={reportExpenseCents}
                  net={reportNetCents}
                  categoryTotals={periodCategoryTotals}
                  cashFlowRows={periodCashFlowRows}
                  netWorthAccounts={netWorthAccounts}
                  allocationRows={allocationRows}
                  holdingRows={holdingRows}
                  selectedHoldingIds={selectedHoldingIds}
                  selectedVisibleHoldingIds={selectedVisibleHoldingIds}
                  visibleHoldingIds={visibleHoldingIds}
                  deleteTarget={deleteTarget}
                  deleteConfirmText={deleteConfirmText}
                  onToggleHoldingSelection={toggleHoldingSelection}
                  onRequestBulkHoldingDelete={requestBulkHoldingDelete}
                  onClearHoldingSelection={() => {
                    setSelectedHoldingIds((current) => current.filter((id) => !visibleHoldingIds.includes(id)));
                    setLastSelectedHoldingId(null);
                  }}
                  onUpdateHoldingDescription={updateHoldingDescription}
                  onRequestDelete={requestDelete}
                  onConfirmDelete={confirmDelete}
                  onDeleteConfirmTextChange={setDeleteConfirmText}
                  onCancelDelete={() => {
                    setDeleteTarget(null);
                    setDeleteConfirmText("");
                  }}
                />
              </section>
            </section>
          </>
        )}

        {activeView === "account" && focusedAccount ? (
          <>
            {focusedMissingCategoryCount > 0 ? (
              <div className="reviewNoticeBar">
                <span>
                  {focusedMissingCategoryCount} new transaction{focusedMissingCategoryCount === 1 ? "" : "s"} to approve or categorize.
                </span>
                <button type="button" onClick={scrollToUncategorized}>
                  View
                </button>
              </div>
            ) : null}
            <header className="accountLedgerHeader">
              <div>
                <h1>
                  {focusedAccount.display_name}
                  {focusedAccount.last_four ? ` (${focusedAccount.last_four})` : ""}
                </h1>
                <div className="accountMetaRow">
                  <span>{accountGroupLabel(focusedAccount.account_type)}</span>
                  <span>{readableAccountType(focusedAccount.account_type)}</span>
                  <span>{focusedAccount.institution_name ?? "Local account"}</span>
                  <span>{focusedAccount.status}</span>
                </div>
              </div>
              <div className="accountBalanceRow">
                <div>
                  <strong className={focusedAccountBalanceCents < 0 ? "amount negative" : "amount positive"}>{formatMoney(focusedAccountBalanceCents)}</strong>
                  <span>Working Balance</span>
                </div>
                <div>
                  <strong>{focusedMissingCategoryCount}</strong>
                  <span>Need category</span>
                </div>
              </div>
              <div className="accountActionBar">
                <button className="primaryButton" onClick={() => openImportModal(focusedAccount.id)}>
                  <FileUp size={16} />
                  File Import
                </button>
                <button className="secondaryButton" onClick={() => setActiveView("review")}>
                  <ListChecks size={16} />
                  Open Review
                </button>
                <button className="ghostButton" title="Refresh data" onClick={() => void loadData()}>
                  <RefreshCw size={16} />
                </button>
              </div>
            </header>
          </>
        ) : null}

        {activeView === "all-accounts" ? (
          <header className="accountLedgerHeader">
            <div>
              <h1>All Accounts</h1>
              <div className="accountMetaRow">
                <span>{accounts.length} accounts</span>
                <span>{missingCategoryTransactions.length} need a category</span>
              </div>
            </div>
            <div className="accountActionBar">
              <button className="primaryButton" onClick={() => openImportModal()}>
                <FileUp size={16} />
                File Import
              </button>
              <button className="ghostButton" title="Refresh data" onClick={() => void loadData()}>
                <RefreshCw size={16} />
              </button>
            </div>
          </header>
        ) : null}

        {(activeView === "review" || activeView === "settings") && (
        <section className="workGrid viewSection">
          {activeView === "settings" ? (
          <section className="toolPanel importWorkspace">
            <PanelTitle icon={FileUp} title="Import & Accounts" subtitle="Start with a CSV. The app will match an account or prefill one for your review." />
            <div className="workspaceTabs">
              <button className={importWorkspaceTab === "smart" ? "workspaceTab active" : "workspaceTab"} onClick={() => setImportWorkspaceTab("smart")}>
                Smart import
              </button>
              <button className={importWorkspaceTab === "manual" ? "workspaceTab active" : "workspaceTab"} onClick={() => setImportWorkspaceTab("manual")}>
                Manual accounts
              </button>
            </div>

            {importWorkspaceTab === "smart" ? (
              <>
                <div className="historyImportPanel">
                  <div>
                    <strong>Categorized history import</strong>
                    <span>Upload an older categorized spreadsheet. Expected columns: Account, Posted Date, Payee, Amount, and Expense Category. Missing accounts and categories are created automatically.</span>
                  </div>
                  <div className="buttonRow">
                    <input type="file" accept=".csv,.xlsx,.xlsm" onChange={(event) => { setCategorizedHistoryFile(event.target.files?.[0] ?? null); setCategorizedHistoryRows([]); setCategorizedHistoryFilename(""); }} />
                    <button className="primaryButton" onClick={() => void importCategorizedHistory()} disabled={!categorizedHistoryFile}>
                      <ArrowDownToLine size={16} />
                      Import categorized history
                    </button>
                  </div>
                </div>
                {categorizedHistoryRows.length > 0 ? (
                  <div className="historyReviewPanel">
                    <div className="historyReviewHeader">
                      <div>
                        <strong>Review categorized history rows</strong>
                        <span>Fill in highlighted fields or delete rows you do not want to import.</span>
                      </div>
                      <button className="primaryButton" onClick={() => void commitReviewedCategorizedHistory()}>
                        Import reviewed rows
                      </button>
                    </div>
                    <div className="historyReviewRows">
                      {categorizedHistoryRows.map((row, index) => {
                        const missing = categorizedHistoryMissingFields(row);
                        const fieldMissing = (label: string) => missing.includes(label) || (row.errors ?? []).includes(label);
                        return (
                          <div className="historyReviewRow" key={`${row.row_index}-${index}`}>
                            <small>Row {row.row_index}</small>
                            <input className={fieldMissing("Account") ? "missingField" : ""} value={row.account} onChange={(event) => updateCategorizedHistoryRow(index, { account: event.target.value })} placeholder="Account" />
                            <input className={fieldMissing("Posted Date") ? "missingField" : ""} value={row.posted_date} onChange={(event) => updateCategorizedHistoryRow(index, { posted_date: event.target.value })} placeholder="MM/DD/YYYY" />
                            <input className={fieldMissing("Payee") ? "missingField" : ""} value={row.payee} onChange={(event) => updateCategorizedHistoryRow(index, { payee: event.target.value })} placeholder="Payee" />
                            <input className={fieldMissing("Amount") ? "missingField" : ""} value={row.amount} onChange={(event) => updateCategorizedHistoryRow(index, { amount: event.target.value })} placeholder="Amount" />
                            <input value={row.category} onChange={(event) => updateCategorizedHistoryRow(index, { category: event.target.value })} placeholder="Category" />
                            <button className="dangerTextButton" onClick={() => deleteCategorizedHistoryRow(index)}>Delete</button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ) : null}
                <div className="compactForm">
                  <input type="file" accept=".csv" onChange={(event) => chooseImportFile(event.target.files?.[0] ?? null)} />
                  <div className="buttonRow">
                    <button className="secondaryButton" onClick={() => void analyzeSelectedImport()}>
                      <Sparkles size={16} />
                      Analyze CSV
                    </button>
                    <button className="secondaryButton" onClick={() => void previewSelectedImport()} disabled={!selectedAccountId || !selectedFile}>
                      <Search size={16} />
                      Preview
                    </button>
                    <button className="primaryButton" onClick={() => void commitSelectedImport()} disabled={!importPreview}>
                      <ArrowDownToLine size={16} />
                      Commit
                    </button>
                  </div>
                </div>

                {importAnalysis ? (
                  <div className="analysisPanel">
                    <div className="analysisHeader">
                      <div>
                        <strong>{importAnalysis.preset_type}</strong>
                        <span>{importAnalysis.reason}</span>
                      </div>
                      <span className="statusBadge suggested">{importAnalysis.suggested_account_id ? `${importAnalysis.match_confidence}% match` : "Needs review"}</span>
                    </div>
                    {analyzedAccount ? (
                      <div className="matchedAccountCard">
                        <Landmark size={16} />
                        <div>
                          <strong>{analyzedAccount.display_name}</strong>
                          <span>{analyzedAccount.institution_name ?? "No institution"} / {readableAccountType(analyzedAccount.account_type)} / {analyzedAccount.last_four ?? "no suffix"}</span>
                        </div>
                        <button className="secondaryButton" onClick={() => setSelectedAccountId(analyzedAccount.id)}>
                          Use this
                        </button>
                      </div>
                    ) : (
                      <div className="suggestedAccountForm">
                        <span className="eyebrow">Suggested new account</span>
                        <input value={accountForm.display_name} onChange={(event) => setAccountForm({ ...accountForm, display_name: event.target.value })} placeholder="Account name" />
                        <input value={accountForm.institution_name} onChange={(event) => setAccountForm({ ...accountForm, institution_name: event.target.value })} placeholder="Institution" />
                        <select value={accountForm.account_type} onChange={(event) => setAccountForm({ ...accountForm, account_type: event.target.value })}>
                          {accountTypeOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                        <input value={accountForm.last_four} onChange={(event) => setAccountForm({ ...accountForm, last_four: event.target.value })} placeholder="Last four" />
                        <button className="primaryButton" onClick={() => void createAccountFromAnalysis()}>
                          <Plus size={16} />
                          Create and use account
                        </button>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="emptyText">Choose a CSV and click Analyze. If confidence is high, the app selects the existing account; otherwise it drafts a new account you can edit.</p>
                )}

                <div className="manualOverride">
                  <label>Override account if the match is wrong</label>
                  <select value={selectedAccountId} onChange={(event) => setSelectedAccountId(event.target.value ? Number(event.target.value) : "")}>
                    <option value="">Choose existing account</option>
                    {accounts.map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.display_name}
                      </option>
                    ))}
                  </select>
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
                    <p className="emptyText">Preview shows the cleaned rows before they touch the ledger.</p>
                  )}
                </div>
              </>
            ) : (
              <>
                <div className="compactForm">
                  <input value={accountForm.display_name} onChange={(event) => setAccountForm({ ...accountForm, display_name: event.target.value })} placeholder="Account name" />
                  <input value={accountForm.institution_name} onChange={(event) => setAccountForm({ ...accountForm, institution_name: event.target.value })} placeholder="Institution" />
                  <select value={accountForm.account_type} onChange={(event) => setAccountForm({ ...accountForm, account_type: event.target.value })}>
                    {accountTypeOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
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
                {accounts.length > 0 ? (
                  <div className="selectionToolbar">
                    <span>{selectedVisibleAccountIds.length} selected</span>
                    <button className="dangerTextButton" onClick={() => requestBulkAccountDelete(selectedVisibleAccountIds)} disabled={selectedVisibleAccountIds.length === 0}>
                      Delete selected
                    </button>
                    <button
                      className="secondaryButton"
                      onClick={() => {
                        setSelectedAccountIds([]);
                        setLastSelectedAccountId(null);
                      }}
                    >
                      Clear
                    </button>
                  </div>
                ) : null}
                {deleteTarget?.kind === "account_bulk" ? (
                  <DeleteConfirmInline
                    target={deleteTarget}
                    confirmText={deleteConfirmText}
                    onConfirmTextChange={setDeleteConfirmText}
                    onConfirm={confirmDelete}
                    onCancel={() => {
                      setDeleteTarget(null);
                      setDeleteConfirmText("");
                    }}
                  />
                ) : null}
                <div className="denseList">
                  {accounts.map((account) => (
                    <div className="inlineDeleteGroup" key={account.id}>
                      <div className={selectedAccountId === account.id ? "accountRow selected" : "accountRow"}>
                        <input
                          type="checkbox"
                          checked={selectedAccountIds.includes(account.id)}
                          onChange={(event) => toggleAccountSelection(account.id, accountIds, (event.nativeEvent as MouseEvent).shiftKey)}
                          title="Select account. Hold Shift to select a range."
                        />
                        <button className="accountMainButton" onClick={() => beginEditAccount(account)}>
                          <Landmark size={16} />
                          <span>
                            {account.display_name}
                            {account.institution_name ? <small>{account.institution_name}</small> : null}
                          </span>
                        </button>
                        <small>
                          {accountGroupLabel(account.account_type)} · {readableAccountType(account.account_type)}
                        </small>
                        <div className="inlineActions">
                          <button className="secondaryButton" onClick={() => beginEditAccount(account)} title="Edit account">
                            <Pencil size={14} />
                          </button>
                          <button className="dangerTextButton" onClick={() => requestDelete({ kind: "account", id: account.id, label: account.display_name })}>
                            Delete
                          </button>
                        </div>
                      </div>
                      {deleteTarget?.kind === "account" && deleteTarget.id === account.id ? (
                        <DeleteConfirmInline
                          target={deleteTarget}
                          confirmText={deleteConfirmText}
                          onConfirmTextChange={setDeleteConfirmText}
                          onConfirm={confirmDelete}
                          onCancel={() => {
                            setDeleteTarget(null);
                            setDeleteConfirmText("");
                          }}
                        />
                      ) : null}
                    </div>
                  ))}
                </div>
              </>
            )}
          </section>
          ) : null}

          {activeView === "review" ? (
          <>
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
                        <span>{formatShortDate(candidate.from_transaction.transaction_date)} / {candidate.from_transaction.raw_description}</span>
                        <b>{formatMoney(candidate.from_transaction.amount_cents)}</b>
                      </div>
                      <div>
                        <small>Money in</small>
                        <strong>{toAccount?.display_name ?? `Account ${candidate.to_transaction.account_id}`}</strong>
                        <span>{formatShortDate(candidate.to_transaction.transaction_date)} / {candidate.to_transaction.raw_description}</span>
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

          <section className="toolPanel reviewInboxPanel">
            <PanelTitle icon={ListChecks} title="Review Inbox" subtitle={`${reviewTransactions.length} items need a human decision.`} />
            {visibleReviewTransactions.length > 0 ? (
              <div className="selectionToolbar reviewBulkToolbar">
                <span>{selectedVisibleReviewIds.length} selected</span>
                <select value={bulkReviewType} onChange={(event) => setBulkReviewType(event.target.value)}>
                  {transactionTypes.map((type) => (
                    <option key={type.value} value={type.value}>
                      {type.label}
                    </option>
                  ))}
                </select>
                <select value={bulkReviewCategoryId} onChange={(event) => setBulkReviewCategoryId(event.target.value ? Number(event.target.value) : "")}>
                  <option value="">Choose category</option>
                  {categories.map((category) => (
                    <option key={category.id} value={category.id}>
                      {category.label}
                    </option>
                  ))}
                </select>
                <button className="primaryButton" onClick={() => void bulkConfirmSelectedReviewTransactions()} disabled={selectedVisibleReviewIds.length === 0 || !bulkReviewCategoryId}>
                  Confirm selected
                </button>
                <button className="secondaryButton" onClick={() => void bulkSaveRulesForSelectedReviewTransactions()} disabled={selectedVisibleReviewIds.length === 0}>
                  Save rules
                </button>
                <button className="dangerTextButton" onClick={() => requestBulkTransactionDelete(selectedVisibleReviewIds)} disabled={selectedVisibleReviewIds.length === 0}>
                  Delete selected
                </button>
                <button className="secondaryButton" onClick={() => setSelectedTransactionIds((current) => current.filter((id) => !visibleReviewIds.includes(id)))}>
                  Clear
                </button>
              </div>
            ) : null}
            {deleteTarget?.kind === "transaction_bulk" ? (
              <DeleteConfirmInline
                target={deleteTarget}
                confirmText={deleteConfirmText}
                onConfirmTextChange={setDeleteConfirmText}
                onConfirm={confirmDelete}
                onCancel={() => {
                  setDeleteTarget(null);
                  setDeleteConfirmText("");
                }}
              />
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
                <div className="inlineDeleteGroup" key={transaction.id}>
                  <article className={selectedTransactionIds.includes(transaction.id) ? "reviewCard selected" : "reviewCard"}>
                    <div className="reviewCardTop">
                      <input
                        type="checkbox"
                        checked={selectedTransactionIds.includes(transaction.id)}
                        onChange={(event) => toggleTransactionSelection(transaction.id, visibleReviewIds, (event.nativeEvent as MouseEvent).shiftKey)}
                        title="Select transaction. Hold Shift to select a range."
                      />
                      <div>
                        <strong>{transaction.raw_description}</strong>
                        <span className="reviewMetaRow"><small>{formatShortDate(transaction.transaction_date)}</small><span className={reviewStatusClass(transaction.review_status)}>{reviewStatusLabel(transaction.review_status)}</span></span>
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
                  {deleteTarget?.kind === "transaction" && deleteTarget.id === transaction.id ? (
                    <DeleteConfirmInline
                      target={deleteTarget}
                      confirmText={deleteConfirmText}
                      onConfirmTextChange={setDeleteConfirmText}
                      onConfirm={confirmDelete}
                      onCancel={() => {
                        setDeleteTarget(null);
                        setDeleteConfirmText("");
                      }}
                    />
                  ) : null}
                </div>
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
          </>
          ) : null}

          {activeView === "settings" ? (
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
          ) : null}
        </section>
        )}

        {(activeView === "account" || activeView === "all-accounts") && (
        <section className="ledgerPanel ledgerWorkspace">
          <PanelTitle icon={ReceiptText} title={activeView === "account" ? "Account Transactions" : "All Transactions"} subtitle={activeView === "account" ? "Transactions for the selected account." : "A searchable repository for every imported transaction."} />
          <div className={activeView === "all-accounts" ? "transactionFilters" : "transactionFilters accountFilters"}>
            {activeView === "all-accounts" ? (
              <MultiSelectFilter
                label="Accounts"
                options={accounts.map((account) => ({ value: String(account.id), label: account.display_name }))}
                selectedValues={selectedTransactionAccountFilters.map(String)}
                onToggle={(value) => setSelectedTransactionAccountFilters((current) => toggleValue(current, Number(value)))}
                onSelectAll={() => setSelectedTransactionAccountFilters(accounts.map((account) => account.id))}
                onDeselectAll={() => setSelectedTransactionAccountFilters([])}
              />
            ) : null}
            <MultiSelectFilter
              label="Months"
              options={monthOptions}
              selectedValues={selectedTransactionMonthFilters}
              onToggle={(value) => setSelectedTransactionMonthFilters((current) => toggleValue(current, value))}
              onSelectAll={() => setSelectedTransactionMonthFilters(monthOptions.map((month) => month.value))}
              onDeselectAll={() => setSelectedTransactionMonthFilters([])}
            />
            <MultiSelectFilter
              label="Years"
              options={transactionYears.map((year) => ({ value: year, label: year }))}
              selectedValues={selectedTransactionYearFilters}
              onToggle={(value) => setSelectedTransactionYearFilters((current) => toggleValue(current, value))}
              onSelectAll={() => setSelectedTransactionYearFilters(transactionYears)}
              onDeselectAll={() => setSelectedTransactionYearFilters([])}
            />
            <MultiSelectFilter
              label="Categories"
              options={transactionCategoryOptions}
              selectedValues={selectedTransactionCategoryFilters}
              onToggle={(value) => setSelectedTransactionCategoryFilters((current) => toggleValue(current, value))}
              onSelectAll={() => setSelectedTransactionCategoryFilters(transactionCategoryOptions.map((category) => category.value))}
              onDeselectAll={() => setSelectedTransactionCategoryFilters([])}
            />
          </div>
          {filteredTransactions.length > 0 ? (
            <div className="selectionToolbar">
              <span>
                {selectedRepositoryTransactionIds.length} selected / {pagedTransactions.length} shown
                {filteredTransactions.length > pagedTransactions.length ? ` of ${filteredTransactions.length}` : ""}
              </span>
              <button className="dangerTextButton" onClick={() => requestBulkTransactionDelete(selectedRepositoryTransactionIds)} disabled={selectedRepositoryTransactionIds.length === 0}>
                Delete selected
              </button>
              <button className="secondaryButton" onClick={() => setSelectedTransactionIds((current) => current.filter((id) => !repositoryTransactionIds.includes(id)))}>
                Clear
              </button>
            </div>
          ) : null}
          {deleteTarget?.kind === "transaction_bulk" ? (
            <DeleteConfirmInline
              target={deleteTarget}
              confirmText={deleteConfirmText}
              onConfirmTextChange={setDeleteConfirmText}
              onConfirm={confirmDelete}
              onCancel={() => {
                setDeleteTarget(null);
                setDeleteConfirmText("");
              }}
            />
          ) : null}
          <div className="ledgerTable">
            <div className="ledgerHeader">
              <span>Select</span>
              <span>
                <button type="button" className="sortableHeader" onClick={() => toggleTransactionSort("date")}>
                  Date{sortIndicator("date")}
                </button>
              </span>
              <span>Institution</span>
              <span>Account</span>
              <span>Description</span>
              <span>Details</span>
              <span>Type</span>
              <span>Category</span>
              <span>
                <button type="button" className="sortableHeader" onClick={() => toggleTransactionSort("amount")}>
                  Amount{sortIndicator("amount")}
                </button>
              </span>
              <span>Action</span>
            </div>
            {pagedTransactions.map((transaction) => {
              const needsCategory = transaction.transaction_type === "expense" && !transaction.category_id;
              const categoryLabel = categories.find((category) => category.id === transaction.category_id)?.label;
              const editorOpen = categoryEditor?.transactionId === transaction.id;
              const isFocused = focusedTransactionId === transaction.id;
              const isEditing = editingTransactionId === transaction.id;
              const typeLabel = transactionTypes.find((type) => type.value === transaction.transaction_type)?.label ?? transaction.transaction_type;
              return (
              <div className="inlineDeleteGroup ledgerDeleteGroup" key={transaction.id} id={`transaction-row-${transaction.id}`}>
                <div
                  className={[
                    "ledgerRow",
                    selectedTransactionIds.includes(transaction.id) ? "selected" : "",
                    isFocused ? "focused" : "",
                    isEditing ? "editing" : "",
                    needsCategory ? "needsAttention" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onClick={() => handleTransactionRowClick(transaction.id)}
                >
                  <input
                    type="checkbox"
                    checked={selectedTransactionIds.includes(transaction.id)}
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) => toggleTransactionSelection(transaction.id, repositoryTransactionIds, (event.nativeEvent as MouseEvent).shiftKey)}
                    title="Select transaction. Hold Shift to select a range."
                  />
                  <span>{formatShortDate(transaction.transaction_date)}</span>
                  <span>{transaction.institution_name ?? "-"}</span>
                  <span>{transaction.account_name}</span>
                  <strong className="ledgerDescription">{transaction.raw_description}</strong>
                  {isEditing ? (
                    <textarea
                      className="editableCell detailsCell"
                      defaultValue={transaction.user_note ?? ""}
                      onClick={(event) => event.stopPropagation()}
                      onBlur={(event) => {
                        const nextNote = event.currentTarget.value;
                        if (nextNote !== (transaction.user_note ?? "")) {
                          void updateTransaction(transaction.id, { user_note: nextNote }, false);
                        }
                      }}
                      placeholder="Add details"
                      rows={1}
                      title="Add your own context, like what you actually bought."
                    />
                  ) : (
                    <span className="ledgerReadonlyCell">{transaction.user_note || "Add details"}</span>
                  )}
                  {isEditing ? (
                    <select
                      className="editableCell"
                      value={transaction.transaction_type}
                      onClick={(event) => event.stopPropagation()}
                      onChange={(event) => void updateTransaction(transaction.id, { transaction_type: event.target.value }, false)}
                    >
                      {transactionTypes.map((type) => (
                        <option key={type.value} value={type.value}>
                          {type.label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="ledgerReadonlyCell">{typeLabel}</span>
                  )}
                  <div className="categoryPopupAnchor" onClick={(event) => event.stopPropagation()}>
                    {isEditing ? (
                      <>
                        <button
                          type="button"
                          className={["categoryTrigger", needsCategory ? "needsCategory" : "", editorOpen ? "open" : ""].filter(Boolean).join(" ")}
                          onClick={() => setCategoryEditor({ transactionId: transaction.id, query: categoryLabel ?? "" })}
                          title="Search and assign a category"
                        >
                          <span>{needsCategory ? "This needs a category" : categoryLabel ?? "No category"}</span>
                        </button>
                        {editorOpen ? (
                          <div className="categoryPopup" role="dialog" aria-label="Choose category">
                            <input
                              autoFocus
                              value={categoryEditor?.query ?? ""}
                              placeholder="Search for a category..."
                              onChange={(event) => setCategoryEditor({ transactionId: transaction.id, query: event.target.value })}
                              onKeyDown={(event) => {
                                if (event.key === "Escape") {
                                  setCategoryEditor(null);
                                }
                              }}
                            />
                            <div className="categoryPopupList">
                              <button
                                type="button"
                                className="categoryPopupOption"
                                onClick={() => {
                                  void updateTransaction(transaction.id, { category_id: null }, false);
                                  setCategoryEditor(null);
                                }}
                              >
                                <span>No category</span>
                              </button>
                              {categorySuggestions.map((categoryOption) => (
                                <button
                                  type="button"
                                  className="categoryPopupOption"
                                  key={categoryOption.id}
                                  onClick={() => {
                                    void updateTransaction(transaction.id, { category_id: categoryOption.id }, false);
                                    setCategoryEditor(null);
                                  }}
                                >
                                  <span>{categoryOption.label}</span>
                                </button>
                              ))}
                              {categorySuggestions.length === 0 ? <div className="categoryPopupEmpty">No matching categories.</div> : null}
                            </div>
                            <div className="categoryPopupActions">
                              <button
                                type="button"
                                onClick={() => {
                                  void updateTransaction(transaction.id, { transaction_type: "transfer" }, false);
                                  setCategoryEditor(null);
                                }}
                              >
                                Payment/Transfer
                              </button>
                              <button type="button" onClick={() => setCategoryEditor(null)}>
                                Close
                              </button>
                            </div>
                          </div>
                        ) : null}
                      </>
                    ) : (
                      <span className={needsCategory ? "categoryTrigger needsCategory" : "ledgerReadonlyCell"}>
                        {needsCategory ? "This needs a category" : categoryLabel ?? "No category"}
                      </span>
                    )}
                  </div>
                  <span className={transaction.amount_cents < 0 ? "amount negative" : "amount positive"}>{formatMoney(transaction.amount_cents)}</span>
                  <button
                    className="dangerTextButton"
                    onClick={(event) => {
                      event.stopPropagation();
                      requestDelete({ kind: "transaction", id: transaction.id, label: transaction.raw_description });
                    }}
                  >
                    Delete
                  </button>
                </div>
                {isEditing ? (
                  <div className="rowEditActions">
                    <button
                      type="button"
                      className="secondaryButton"
                      onClick={() => {
                        setEditingTransactionId(null);
                        setCategoryEditor(null);
                      }}
                    >
                      Done
                    </button>
                  </div>
                ) : null}
                {deleteTarget?.kind === "transaction" && deleteTarget.id === transaction.id ? (
                  <DeleteConfirmInline
                    target={deleteTarget}
                    confirmText={deleteConfirmText}
                    onConfirmTextChange={setDeleteConfirmText}
                    onConfirm={confirmDelete}
                    onCancel={() => {
                      setDeleteTarget(null);
                      setDeleteConfirmText("");
                    }}
                  />
                ) : null}
              </div>
              );
            })}
            {filteredTransactions.length === 0 ? <p className="emptyText">No transactions match those filters.</p> : null}
          </div>
          {pagedTransactions.length < filteredTransactions.length ? (
            <div className="paginationBar">
              <span>
                Showing {pagedTransactions.length} of {filteredTransactions.length}
              </span>
              <button className="secondaryButton" onClick={() => setTransactionPage((current) => Math.min(transactionPageCount, current + 1))}>
                Load more
              </button>
            </div>
          ) : null}
        </section>
        )}

        {activeView === "settings" ? (
        <section className="settingsPanel viewSection">
          <PanelTitle icon={Settings} title="Settings" subtitle="Backup and restore this local app data." />
          <div className="appDataPanel">
            <div>
              <strong>App data export</strong>
              <span>Download a JSON backup that can be imported back into this app later. Importing a backup replaces the local app data.</span>
            </div>
            <div className="buttonRow">
              <button className="secondaryButton" onClick={() => void downloadAppExport()}>
                <ArrowDownToLine size={16} />
                Export app data
              </button>
              <input type="file" accept="application/json,.json" onChange={(event) => setAppImportFile(event.target.files?.[0] ?? null)} />
              <button className="dangerTextButton" onClick={() => void restoreAppExport()} disabled={!appImportFile}>
                Import backup
              </button>
            </div>
          </div>
        </section>
        ) : null}

        {importModalOpen ? (
          <div className="modalBackdrop" onClick={() => setImportModalOpen(false)}>
            <div className="modalCard" onClick={(event) => event.stopPropagation()}>
              <div className="modalHeader">
                <div>
                  <h2>File Import</h2>
                  <p>Choose a CSV, match or create an account, then preview and commit.</p>
                </div>
                <button className="ghostButton" onClick={() => setImportModalOpen(false)} title="Close">
                  <X size={16} />
                </button>
              </div>
              <div className="workspaceTabs">
                <button className={importWorkspaceTab === "smart" ? "workspaceTab active" : "workspaceTab"} onClick={() => setImportWorkspaceTab("smart")}>
                  Smart import
                </button>
                <button className={importWorkspaceTab === "manual" ? "workspaceTab active" : "workspaceTab"} onClick={() => setImportWorkspaceTab("manual")}>
                  Manual accounts
                </button>
              </div>
              {importWorkspaceTab === "smart" ? (
                <div className="compactForm">
                  <label>
                    Account
                    <select value={selectedAccountId} onChange={(event) => setSelectedAccountId(event.target.value ? Number(event.target.value) : "")}>
                      <option value="">Choose account</option>
                      {accounts.map((account) => (
                        <option key={account.id} value={account.id}>
                          {account.display_name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <input type="file" accept=".csv,text/csv" onChange={(event) => { setSelectedFile(event.target.files?.[0] ?? null); setImportPreview(null); setImportAnalysis(null); }} />
                  <div className="buttonRow">
                    <button className="secondaryButton" onClick={() => void analyzeSelectedImport()} disabled={!selectedFile}>
                      Analyze
                    </button>
                    <button className="secondaryButton" onClick={() => void previewSelectedImport()} disabled={!selectedAccountId || !selectedFile}>
                      Preview
                    </button>
                    <button className="primaryButton" onClick={() => void commitSelectedImport()} disabled={!selectedAccountId || !selectedFile || !importPreview}>
                      Commit import
                    </button>
                  </div>
                  {importAnalysis ? (
                    <div className="importSummary">
                      <span>
                        Detected <strong>{importAnalysis.preset_type}</strong> · {importAnalysis.reason}
                      </span>
                      {analyzedAccount ? <span>Matched account: {analyzedAccount.display_name}</span> : null}
                    </div>
                  ) : null}
                  {importPreview ? (
                    <div className="importSummary">
                      <span>
                        Preview ready for <strong>{selectedAccount?.display_name ?? "selected account"}</strong>
                      </span>
                      <span>{importPreview.rows.length} sample rows · {importPreview.warnings.length} warnings</span>
                    </div>
                  ) : null}
                  {previewRows.length > 0 ? (
                    <div className="previewTable">
                      {previewRows.map((row, index) => (
                        <div className="previewRow" key={`${String(row.date ?? "")}-${index}`}>
                          <span>{String(row.date ?? "")}</span>
                          <strong>{String(row.description ?? row.payee ?? "")}</strong>
                          <span>{String(row.amount ?? "")}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="compactForm">
                  <p className="emptyText">Use Settings → Import & Accounts for full account management, or create a quick account here.</p>
                  <input value={accountForm.display_name} onChange={(event) => setAccountForm((current) => ({ ...current, display_name: event.target.value }))} placeholder="Account name" />
                  <input value={accountForm.institution_name} onChange={(event) => setAccountForm((current) => ({ ...current, institution_name: event.target.value }))} placeholder="Institution" />
                  <select value={accountForm.account_type} onChange={(event) => setAccountForm((current) => ({ ...current, account_type: event.target.value }))}>
                    {accountTypeOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <button className="primaryButton" onClick={() => void saveAccount()}>
                    Save account
                  </button>
                </div>
              )}
            </div>
          </div>
        ) : null}
      </main>
    </div>
  );
}

function MultiSelectFilter({
  label,
  options,
  selectedValues,
  onToggle,
  onSelectAll,
  onDeselectAll,
}: {
  label: string;
  options: FilterOption[];
  selectedValues: string[];
  onToggle: (value: string) => void;
  onSelectAll: () => void;
  onDeselectAll: () => void;
}) {
  const selectedCount = selectedValues.length;
  const summary = selectedCount === options.length ? "All" : selectedCount === 0 ? "None" : `${selectedCount} selected`;

  return (
    <details className="multiFilter">
      <summary>
        <span>{label}</span>
        <strong>{summary}</strong>
      </summary>
      <div className="multiFilterMenu">
        <div className="multiFilterActions">
          <button type="button" className="ghostButton" onClick={onSelectAll}>Select all</button>
          <button type="button" className="ghostButton" onClick={onDeselectAll}>Deselect all</button>
        </div>
        <div className="multiFilterOptions">
          {options.map((option) => (
            <label key={option.value}>
              <input type="checkbox" checked={selectedValues.includes(option.value)} onChange={() => onToggle(option.value)} />
              <span>{option.label}</span>
            </label>
          ))}
          {options.length === 0 ? <span className="emptyText">No options yet.</span> : null}
        </div>
      </div>
    </details>
  );
}
function DeleteConfirmInline({
  target,
  confirmText,
  onConfirmTextChange,
  onConfirm,
  onCancel,
}: {
  target: DeleteTarget;
  confirmText: string;
  onConfirmTextChange: (value: string) => void;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}) {
  return (
    <section className="deleteConfirmPanel inlineDeleteConfirm">
      <div>
        <strong>{target.kind.endsWith("bulk") ? "Delete selected items?" : target.kind === "account" ? "Delete this account and its imported data?" : `Delete this ${target.kind} row?`}</strong>
        <span>{target.label}</span>
        <small>Accounts delete their imported transactions, holdings, presets, and import history. Audit history remains append-only.</small>
      </div>
      <input value={confirmText} onChange={(event) => onConfirmTextChange(event.target.value)} placeholder="Type DELETE to confirm" />
      <div className="buttonRow">
        <button className="dangerButton" onClick={() => void onConfirm()} disabled={confirmText !== "DELETE"}>
          Delete
        </button>
        <button className="secondaryButton" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </section>
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
  selectedHoldingIds,
  selectedVisibleHoldingIds,
  visibleHoldingIds,
  deleteTarget,
  deleteConfirmText,
  onToggleHoldingSelection,
  onRequestBulkHoldingDelete,
  onClearHoldingSelection,
  onUpdateHoldingDescription,
  onRequestDelete,
  onConfirmDelete,
  onDeleteConfirmTextChange,
  onCancelDelete,
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
  selectedHoldingIds: number[];
  selectedVisibleHoldingIds: number[];
  visibleHoldingIds: number[];
  deleteTarget: DeleteTarget | null;
  deleteConfirmText: string;
  onToggleHoldingSelection: (holdingId: number, visibleIds: number[], shiftKey: boolean) => void;
  onRequestBulkHoldingDelete: (ids: number[]) => void;
  onClearHoldingSelection: () => void;
  onUpdateHoldingDescription: (symbol: string | null, userDescription: string) => Promise<void>;
  onRequestDelete: (target: DeleteTarget) => void;
  onConfirmDelete: () => Promise<void>;
  onDeleteConfirmTextChange: (value: string) => void;
  onCancelDelete: () => void;
}) {
  if (activeTab === "Spending") {
    return <SpendingReport rows={categoryTotals} />;
  }
  if (activeTab === "Income") {
    return <IncomeReport income={income} expenses={expenses} net={net} />;
  }
  if (activeTab === "Net Worth") {
    return <NetWorthReport accounts={netWorthAccounts} allocationRows={allocationRows} holdingRows={holdingRows} selectedHoldingIds={selectedHoldingIds} selectedVisibleHoldingIds={selectedVisibleHoldingIds} visibleHoldingIds={visibleHoldingIds} deleteTarget={deleteTarget} deleteConfirmText={deleteConfirmText} onToggleHoldingSelection={onToggleHoldingSelection} onRequestBulkHoldingDelete={onRequestBulkHoldingDelete} onClearHoldingSelection={onClearHoldingSelection} onUpdateHoldingDescription={onUpdateHoldingDescription} onRequestDelete={onRequestDelete} onConfirmDelete={onConfirmDelete} onDeleteConfirmTextChange={onDeleteConfirmTextChange} onCancelDelete={onCancelDelete} />;
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
  const yearly = new Map<string, { income_cents: number; expense_cents: number; net_cents: number }>();
  for (const row of rows) {
    const year = row.month.slice(0, 4);
    const current = yearly.get(year) ?? { income_cents: 0, expense_cents: 0, net_cents: 0 };
    current.income_cents += row.income_cents;
    current.expense_cents += row.expense_cents;
    current.net_cents += row.net_cents;
    yearly.set(year, current);
  }
  const yearlyRows = Array.from(yearly.entries())
    .map(([year, values]) => ({ year, ...values }))
    .sort((left, right) => right.year.localeCompare(left.year));

  return (
    <div className="reportStack">
      <CashFlowGraphic income={income} expenses={expenses} net={net} />
      <div className="reportMiniGrid">
        <ReportStat label="Period income" value={formatMoney(income)} />
        <ReportStat label="Period expenses" value={formatMoney(expenses)} />
        <ReportStat label="Period net" value={formatMoney(net)} />
      </div>
      <div className="reportTable">
        <div className="reportTableHeader">
          <span>Month</span>
          <span>Income</span>
          <span>Expenses</span>
          <span>Net</span>
        </div>
        {rows.slice(-12).map((row) => (
          <div className="reportTableRow" key={row.month}>
            <strong>{row.month}</strong>
            <span>{formatMoney(row.income_cents)}</span>
            <span>{formatMoney(row.expense_cents)}</span>
            <span className={row.net_cents < 0 ? "amount negative" : "amount positive"}>{formatMoney(row.net_cents)}</span>
          </div>
        ))}
        {rows.length === 0 ? <p className="emptyText">No cash-flow months in this period yet.</p> : null}
      </div>
      {yearlyRows.length > 0 ? (
        <div className="reportTable">
          <div className="reportTableHeader">
            <span>Year</span>
            <span>Income</span>
            <span>Expenses</span>
            <span>Net</span>
          </div>
          {yearlyRows.map((row) => (
            <div className="reportTableRow" key={row.year}>
              <strong>{row.year}</strong>
              <span>{formatMoney(row.income_cents)}</span>
              <span>{formatMoney(row.expense_cents)}</span>
              <span className={row.net_cents < 0 ? "amount negative" : "amount positive"}>{formatMoney(row.net_cents)}</span>
            </div>
          ))}
        </div>
      ) : null}
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
  selectedHoldingIds,
  selectedVisibleHoldingIds,
  visibleHoldingIds,
  deleteTarget,
  deleteConfirmText,
  onToggleHoldingSelection,
  onRequestBulkHoldingDelete,
  onClearHoldingSelection,
  onUpdateHoldingDescription,
  onRequestDelete,
  onConfirmDelete,
  onDeleteConfirmTextChange,
  onCancelDelete,
}: {
  accounts: NetWorthAccount[];
  allocationRows: AllocationRow[];
  holdingRows: HoldingRow[];
  selectedHoldingIds: number[];
  selectedVisibleHoldingIds: number[];
  visibleHoldingIds: number[];
  deleteTarget: DeleteTarget | null;
  deleteConfirmText: string;
  onToggleHoldingSelection: (holdingId: number, visibleIds: number[], shiftKey: boolean) => void;
  onRequestBulkHoldingDelete: (ids: number[]) => void;
  onClearHoldingSelection: () => void;
  onUpdateHoldingDescription: (symbol: string | null, userDescription: string) => Promise<void>;
  onRequestDelete: (target: DeleteTarget) => void;
  onConfirmDelete: () => Promise<void>;
  onDeleteConfirmTextChange: (value: string) => void;
  onCancelDelete: () => void;
}) {
  const total = accounts.reduce((sum, row) => sum + row.market_value_cents, 0);
  const max = Math.max(...accounts.map((row) => row.market_value_cents), 1);
  const sharedPriceDate = holdingRows.find((row) => row.price_date)?.price_date ?? "-";
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
              <span>{formatMoney(row.market_value_cents)} / {formatShortDate(row.latest_date)}</span>
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
        {holdingRows.length > 0 ? (
          <div className="selectionToolbar">
            <span>{selectedVisibleHoldingIds.length} selected</span>
            <button className="dangerTextButton" onClick={() => onRequestBulkHoldingDelete(selectedVisibleHoldingIds)} disabled={selectedVisibleHoldingIds.length === 0}>
              Delete selected
            </button>
            <button className="secondaryButton" onClick={onClearHoldingSelection}>
              Clear
            </button>
          </div>
        ) : null}
        {deleteTarget?.kind === "holding_bulk" ? (
          <DeleteConfirmInline
            target={deleteTarget}
            confirmText={deleteConfirmText}
            onConfirmTextChange={onDeleteConfirmTextChange}
            onConfirm={onConfirmDelete}
            onCancel={onCancelDelete}
          />
        ) : null}
        <div className="holdingsTable">
          <div className="holdingsHeader">
            <span>Select</span>
            <span>Account</span>
            <span>Symbol</span>
            <span>Description</span>
            <span>Quantity</span>
            <span className="stackedHeader">
              Price
              <small>{formatShortDate(sharedPriceDate)}</small>
            </span>
            <span>Value</span>
            <span>Action</span>
          </div>
          {holdingRows.slice(0, 12).map((row) => (
            <div className="inlineDeleteGroup holdingsDeleteGroup" key={row.id}>
              <div className={selectedHoldingIds.includes(row.id) ? "holdingsRow selected" : "holdingsRow"}>
                <input
                  type="checkbox"
                  checked={selectedHoldingIds.includes(row.id)}
                  onChange={(event) => onToggleHoldingSelection(row.id, visibleHoldingIds, (event.nativeEvent as MouseEvent).shiftKey)}
                  title="Select holding. Hold Shift to select a range."
                />
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
                <span>{formatMoney(row.display_market_value_cents)}</span>
                <button className="dangerTextButton" onClick={() => onRequestDelete({ kind: "holding", id: row.id, label: `${row.symbol || row.description || "Holding"} in ${row.account}` })}>
                  Delete
                </button>
              </div>
              {deleteTarget?.kind === "holding" && deleteTarget.id === row.id ? (
                <DeleteConfirmInline
                  target={deleteTarget}
                  confirmText={deleteConfirmText}
                  onConfirmTextChange={onDeleteConfirmTextChange}
                  onConfirm={onConfirmDelete}
                  onCancel={onCancelDelete}
                />
              ) : null}
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
