import {
  AlertCircle,
  ArrowDownToLine,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileUp,
  History,
  Landmark,
  LayoutDashboard,
  LogOut,
  ListChecks,
  Pencil,
  PiggyBank,
  Plus,
  ReceiptText,
  RefreshCw,
  RotateCcw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Trash2,
  WalletCards,
  X,
} from "lucide-react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { readAppRoute, routeUrl, type NetWorthPeriod, type RouteView, type TxnFilter } from "./lib/filters";

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
  sidebar_balance_cents: number;
  sidebar_balance_kind: "running_balance" | "investment_snapshot" | "recent_activity";
  sidebar_balance_as_of: string | null;
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
  monthly_allocation_count: number;
  split_count: number;
};

type SplitDraft = { category_id: number | ""; amount: string; note: string };
type MonthlyAllocationDraft = { transactionId: number; category_id: number | ""; start_month: string; end_month: string };

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
  operationId?: string;
  unconflictedOnly?: boolean;
};

type DeleteTarget =
  | { kind: "transaction"; id: number; label: string }
  | { kind: "transaction_bulk"; ids: number[]; label: string }
  | { kind: "transaction_permanent"; id: number; label: string }
  | { kind: "transaction_bulk_permanent"; ids: number[]; label: string }
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
type NetWorthPoint = { date: string; total_cents: number; by_account: Record<string, number> };
type NetWorthSeriesResponse = { from: string; to: string; bucket: "day" | "week" | "month"; series: NetWorthPoint[] };
type NetWorthStats = {
  from: string;
  to: string;
  start_cents: number;
  end_cents: number;
  change_cents: number;
  change_pct: number | null;
  min_cents: number;
  min_date: string;
  max_cents: number;
  max_date: string;
  best_day: { date: string; delta_cents: number };
  worst_day: { date: string; delta_cents: number };
};

type OperationSummary = {
  id: string;
  kind: string;
  entity_type: string;
  actor: string;
  description: string;
  created_at: string;
  change_count: number;
  undone_by: string | null;
  undo_of: string | null;
  can_undo: boolean;
};

type OperationDetail = OperationSummary & {
  changes: Array<{ id: number; entity_id: string; before: Record<string, unknown> | null; after: Record<string, unknown> | null }>;
};

type PeekDrawerState = {
  title: string;
  from: string;
  to: string;
  rows: TransactionRow[];
};
type AllocationRow = { asset_class: string; market_value_cents: number };
type TransactionSortKey = "date" | "amount";
type SortDirection = "asc" | "desc";
type BulkTransactionField = "institution" | "account" | "description" | "details" | "type" | "category";
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

type AppView = RouteView;
type AccountTaxonomyOverrides = Record<string, string>;
type TaxonomySection = { label: string; rows: AccountSummary[]; emptyText: string };
type TaxonomyGroup = { label: string; rows: AccountSummary[]; totalCents: number };
type CollapsedTaxonomyGroups = Record<string, boolean>;
type DashboardWidgetKey = "taxonomy" | "review" | "spending" | "cashflow" | "imports";
type DashboardWidgetConfig = Record<DashboardWidgetKey, boolean>;

const primaryNavItems: Array<{ id: AppView; label: string; icon: typeof LayoutDashboard }> = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "reports", label: "Reports", icon: TrendingUp },
  { id: "all-accounts", label: "All Accounts", icon: Landmark },
  { id: "review", label: "Review", icon: ListChecks },
  { id: "history", label: "Activity", icon: History },
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
const taxonomyStorageKey = "privateFinance.accountTaxonomy.v1";
const collapsedTaxonomyStorageKey = "privateFinance.collapsedTaxonomy.v1";
const sidebarWidthStorageKey = "privateFinance.sidebarWidth.v1";
const minSidebarWidth = 190;
const maxSidebarWidth = 420;
const dashboardWidgetStorageKey = "privateFinance.dashboardWidgets.v1";
const defaultDashboardWidgets: DashboardWidgetConfig = {
  taxonomy: true,
  review: true,
  spending: true,
  cashflow: true,
  imports: true,
};
const dashboardWidgetOptions: Array<{ key: DashboardWidgetKey; label: string; description: string }> = [
  { key: "taxonomy", label: "Account map", description: "Balances by account type and institution/custom group." },
  { key: "review", label: "Review workload", description: "Transactions that still need categorization or duplicate review." },
  { key: "spending", label: "Top spending", description: "Largest expense categories for the selected period." },
  { key: "cashflow", label: "Cash-flow trend", description: "Recent income, expense, and net movement." },
  { key: "imports", label: "Import readiness", description: "Quick next steps for loading new CSV files." },
];

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

const bulkTransactionFields: Array<{ value: BulkTransactionField; label: string }> = [
  { value: "institution", label: "Institution" },
  { value: "account", label: "Account" },
  { value: "description", label: "Description" },
  { value: "details", label: "Details" },
  { value: "type", label: "Type" },
  { value: "category", label: "Category" },
];

const formatMoney = (cents: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);

const sameFilterValues = (left: Array<string | number>, right: Array<string | number>) =>
  left.length === right.length && new Set(left.map(String)).size === new Set([...left, ...right].map(String)).size;

const selectionSummary = (label: string, selected: string[], options: FilterOption[]) => {
  if (selected.length === 0) return `${label}: none`;
  if (selected.length === 1) return `${label}: ${options.find((option) => option.value === selected[0])?.label ?? selected[0]}`;
  return `${label}: ${selected.length} selected`;
};

type InboxBatch = {
  id: number;
  filename: string;
  preset_type: string | null;
  account_id: number;
  account_name: string;
  account_last_four: string | null;
  match_confidence: number;
  match_reason: string | null;
  row_count: number;
  warnings: string[];
  preview: Array<Record<string, string | number | null>>;
  created_at: string;
};

type ImportInboxState = { folder: string; pending: InboxBatch[] };
type ImportInboxScan = ImportInboxState & {
  files_found: number;
  staged: Array<{ batch_id: number; filename: string; account_id: number; row_count: number }>;
  skipped: Array<{ filename: string; reason: string }>;
  needs_account: Array<{ filename: string; preset_type: string; reason: string; proposed_account: Record<string, string | null> }>;
  errors: Array<{ filename: string; message: string }>;
};

const accountOptionLabel = (account: AccountSummary) => {
  const name = account.display_name.trim();
  const lastFour = account.last_four?.trim();
  if (!lastFour || name.endsWith(lastFour) || name.endsWith(`(${lastFour})`)) return name;
  return `${name} (${lastFour})`;
};

const sidebarBalanceLabel = (account: AccountSummary) => {
  const source = account.sidebar_balance_kind === "running_balance"
    ? "Latest imported balance"
    : account.sidebar_balance_kind === "investment_snapshot"
      ? "Latest investment value"
      : "Net activity in the last 30 days";
  return account.sidebar_balance_as_of ? `${source}, as of ${formatShortDate(account.sidebar_balance_as_of)}` : source;
};

const centsToInput = (cents: number) => (cents / 100).toFixed(2);
const moneyInputToCents = (value: string) => {
  const amount = Number(value);
  return Number.isFinite(amount) ? Math.round(amount * 100) : null;
};

function addMonthsToMonth(month: string, offset: number): string {
  const [year, monthNumber] = month.split("-").map(Number);
  const value = new Date(year, monthNumber - 1 + offset, 1);
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}`;
}

function inclusiveMonthCount(startMonth: string, endMonth: string): number {
  const [startYear, startNumber] = startMonth.split("-").map(Number);
  const [endYear, endNumber] = endMonth.split("-").map(Number);
  if (![startYear, startNumber, endYear, endNumber].every(Number.isFinite)) return 0;
  return (endYear - startYear) * 12 + endNumber - startNumber + 1;
}

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

function categoryTotalsPath(period: ReportPeriod, now = new Date()): string {
  if (period === "all") return "/api/category-totals";
  const year = now.getFullYear();
  const month = now.getMonth();
  const start = period === "this_month" ? new Date(year, month, 1) : period === "this_year" ? new Date(year, 0, 1) : new Date(year, month - 11, 1);
  const formatDate = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
  return `/api/category-totals?start_date=${formatDate(start)}&end_date=${formatDate(now)}`;
}

function readStoredJson<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") {
    return fallback;
  }
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? ({ ...fallback, ...JSON.parse(raw) } as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeStoredJson<T>(key: string, value: T) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(key, JSON.stringify(value));
}

function readStoredNumber(key: string, fallback: number, min: number, max: number): number {
  if (typeof window === "undefined") {
    return fallback;
  }
  const parsed = Number(window.localStorage.getItem(key));
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, parsed));
}

function taxonomyLabelForAccount(account: AccountSummary, overrides: AccountTaxonomyOverrides): string {
  const override = overrides[String(account.id)]?.trim();
  if (override) {
    return override;
  }
  return account.institution_name?.trim() || "Unassigned";
}

function buildTaxonomyGroups(rows: AccountSummary[], accountBalances: Map<number, number>, overrides: AccountTaxonomyOverrides): TaxonomyGroup[] {
  const groups = new Map<string, TaxonomyGroup>();
  for (const account of rows) {
    const label = taxonomyLabelForAccount(account, overrides);
    const existing = groups.get(label) ?? { label, rows: [], totalCents: 0 };
    existing.rows.push(account);
    existing.totalCents += accountBalances.get(account.id) ?? 0;
    groups.set(label, existing);
  }
  return Array.from(groups.values()).sort((left, right) => {
    if (left.label === "Unassigned") return 1;
    if (right.label === "Unassigned") return -1;
    return left.label.localeCompare(right.label);
  });
}

export function App() {
  const initialRoute = useRef(readAppRoute(window.location));
  const [configured, setConfigured] = useState(false);
  const [csrf, setCsrf] = useState("");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [toast, setToast] = useState<ToastState | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null);
  const [categories, setCategories] = useState<BootstrapCategory[]>([]);
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [review, setReview] = useState<ReviewItem[]>([]);
  const [transactions, setTransactions] = useState<TransactionRow[]>([]);
  const [operations, setOperations] = useState<OperationSummary[]>([]);
  const [expandedOperationId, setExpandedOperationId] = useState<string | null>(null);
  const [expandedOperation, setExpandedOperation] = useState<OperationDetail | null>(null);
  const [peekDrawer, setPeekDrawer] = useState<PeekDrawerState | null>(null);
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
  const [importInbox, setImportInbox] = useState<ImportInboxState>({ folder: "", pending: [] });
  const [lastInboxScan, setLastInboxScan] = useState<ImportInboxScan | null>(null);
  const [importWorkspaceTab, setImportWorkspaceTab] = useState<"smart" | "manual">("smart");
  const [activeTab, setActiveTab] = useState("Cash Flow");
  const [activeView, setActiveView] = useState<AppView>(initialRoute.current.view);
  const [focusedAccountId, setFocusedAccountId] = useState<number | null>(initialRoute.current.accountId);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [categoryEditor, setCategoryEditor] = useState<{ transactionId: number; query: string } | null>(null);
  const [editingAccountId, setEditingAccountId] = useState<number | null>(null);
  const [newCategoryLabel, setNewCategoryLabel] = useState("");
  const [editingCategoryId, setEditingCategoryId] = useState<number | null>(null);
  const [editingCategoryLabel, setEditingCategoryLabel] = useState("");
  const [categoryReassignId, setCategoryReassignId] = useState<number | "">("");
  const [editingRule, setEditingRule] = useState<RuleSummary | null>(null);
  const [ruleFeedback, setRuleFeedback] = useState<{ ruleId: number; message: string } | null>(null);
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
  const [selectedTransactionAccountFilters, setSelectedTransactionAccountFilters] = useState<number[]>(() => (initialRoute.current.filters.accounts ?? []).map(Number).filter(Number.isFinite));
  const [selectedTransactionMonthFilters, setSelectedTransactionMonthFilters] = useState<string[]>(() => initialRoute.current.filters.months ?? []);
  const [selectedTransactionYearFilters, setSelectedTransactionYearFilters] = useState<string[]>(() => initialRoute.current.filters.years ?? []);
  const [selectedTransactionCategoryFilters, setSelectedTransactionCategoryFilters] = useState<string[]>(() => initialRoute.current.filters.categories ?? []);
  const [transactionDateFrom, setTransactionDateFrom] = useState(initialRoute.current.filters.dateFrom ?? "");
  const [transactionDateTo, setTransactionDateTo] = useState(initialRoute.current.filters.dateTo ?? "");
  const [transactionAmountMin, setTransactionAmountMin] = useState<number | undefined>(initialRoute.current.filters.amountMin);
  const [transactionAmountMax, setTransactionAmountMax] = useState<number | undefined>(initialRoute.current.filters.amountMax);
  const [transactionDirection, setTransactionDirection] = useState<TxnFilter["direction"]>(initialRoute.current.filters.direction);
  const [transactionView, setTransactionView] = useState<TxnFilter["view"]>(() => ["account", "all-accounts"].includes(initialRoute.current.view) ? initialRoute.current.filters.view ?? "live" : "live");
  const [transactionFiltersInitialized, setTransactionFiltersInitialized] = useState(false);
  const [transactionSortKey, setTransactionSortKey] = useState<TransactionSortKey>(initialRoute.current.filters.sort ?? "date");
  const [transactionSortDirection, setTransactionSortDirection] = useState<SortDirection>(initialRoute.current.filters.sortDirection ?? "desc");
  const [transactionPage, setTransactionPage] = useState(1);
  const [transactionSearch, setTransactionSearch] = useState(initialRoute.current.filters.search ?? "");
  const [focusedTransactionId, setFocusedTransactionId] = useState<number | null>(null);
  const [editingTransactionId, setEditingTransactionId] = useState<number | null>(null);
  const [splitEditor, setSplitEditor] = useState<{ transactionId: number; rows: SplitDraft[] } | null>(null);
  const [monthlyAllocationEditor, setMonthlyAllocationEditor] = useState<MonthlyAllocationDraft | null>(null);
  const [reportPeriod, setReportPeriod] = useState<ReportPeriod>("this_year");
  const [taxonomyOverrides, setTaxonomyOverrides] = useState<AccountTaxonomyOverrides>(() => readStoredJson<AccountTaxonomyOverrides>(taxonomyStorageKey, {}));
  const [collapsedTaxonomyGroups, setCollapsedTaxonomyGroups] = useState<CollapsedTaxonomyGroups>(() =>
    readStoredJson<CollapsedTaxonomyGroups>(collapsedTaxonomyStorageKey, {}),
  );
  const [taxonomyEditorOpen, setTaxonomyEditorOpen] = useState(false);
  const [taxonomyAccountId, setTaxonomyAccountId] = useState<number | "">("");
  const [taxonomyGroupDraft, setTaxonomyGroupDraft] = useState("");
  const [dashboardCustomizeOpen, setDashboardCustomizeOpen] = useState(false);
  const [dashboardWidgets, setDashboardWidgets] = useState<DashboardWidgetConfig>(() =>
    readStoredJson<DashboardWidgetConfig>(dashboardWidgetStorageKey, defaultDashboardWidgets),
  );
  const [sidebarWidth, setSidebarWidth] = useState(() => readStoredNumber(sidebarWidthStorageKey, 244, minSidebarWidth, maxSidebarWidth));
  const [bulkEditorOpen, setBulkEditorOpen] = useState(false);
  const [bulkEditField, setBulkEditField] = useState<BulkTransactionField>("category");
  const [bulkEditValue, setBulkEditValue] = useState("");
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
    if (!csrf) {
      return;
    }
    api<CategoryTotal[]>(categoryTotalsPath(reportPeriod))
      .then(setCategoryTotals)
      .catch(() => undefined);
  }, [csrf, reportPeriod]);

  useEffect(() => {
    if (!toast) {
      return;
    }
    const timer = window.setTimeout(() => setToast(null), toast.operationId || toast.tone === "error" ? 10000 : 5000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (transactionFiltersInitialized || transactions.length === 0) {
      return;
    }
    const routeFilters = initialRoute.current.filters;
    setSelectedTransactionAccountFilters(routeFilters.accounts === undefined ? accounts.map((account) => account.id) : routeFilters.accounts.map(Number).filter(Number.isFinite));
    setSelectedTransactionMonthFilters(routeFilters.months === undefined ? monthOptions.map((month) => month.value) : routeFilters.months);
    setSelectedTransactionYearFilters(routeFilters.years === undefined ? Array.from(new Set(transactions.map((transaction) => transaction.transaction_date.slice(0, 4)).filter(Boolean))) : routeFilters.years);
    setSelectedTransactionCategoryFilters(routeFilters.categories === undefined ? [...categories.map((category) => String(category.id)), uncategorizedFilterValue] : routeFilters.categories);
    setTransactionFiltersInitialized(true);
  }, [accounts, categories, transactions, transactionFiltersInitialized]);

  useEffect(() => {
    function onPopState() {
      const route = readAppRoute(window.location);
      setActiveView(route.view);
      setFocusedAccountId(route.accountId);
      setSelectedTransactionAccountFilters(route.filters.accounts === undefined ? accounts.map((account) => account.id) : route.filters.accounts.map(Number).filter(Number.isFinite));
      setSelectedTransactionMonthFilters(route.filters.months === undefined ? monthOptions.map((month) => month.value) : route.filters.months);
      setSelectedTransactionYearFilters(route.filters.years === undefined ? Array.from(new Set(transactions.map((transaction) => transaction.transaction_date.slice(0, 4)).filter(Boolean))) : route.filters.years);
      setSelectedTransactionCategoryFilters(route.filters.categories === undefined ? [...categories.map((category) => String(category.id)), uncategorizedFilterValue] : route.filters.categories);
      setTransactionDateFrom(route.filters.dateFrom ?? "");
      setTransactionDateTo(route.filters.dateTo ?? "");
      setTransactionAmountMin(route.filters.amountMin);
      setTransactionAmountMax(route.filters.amountMax);
      setTransactionDirection(route.filters.direction);
      setTransactionView(["account", "all-accounts"].includes(route.view) ? route.filters.view ?? "live" : "live");
      setTransactionSearch(route.filters.search ?? "");
      setTransactionSortKey(route.filters.sort ?? "date");
      setTransactionSortDirection(route.filters.sortDirection ?? "desc");
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [accounts, categories, transactions]);

  useEffect(() => {
    if (!transactionFiltersInitialized) return;
    const allAccountIds = accounts.map((account) => account.id);
    const allMonths = monthOptions.map((month) => month.value);
    const allYears = Array.from(new Set(transactions.map((transaction) => transaction.transaction_date.slice(0, 4)).filter(Boolean)));
    const allCategories = [...categories.map((category) => String(category.id)), uncategorizedFilterValue];
    const filters: TxnFilter = {
      accounts: sameFilterValues(selectedTransactionAccountFilters, allAccountIds) ? undefined : selectedTransactionAccountFilters.map(String),
      months: sameFilterValues(selectedTransactionMonthFilters, allMonths) ? undefined : selectedTransactionMonthFilters,
      years: sameFilterValues(selectedTransactionYearFilters, allYears) ? undefined : selectedTransactionYearFilters,
      categories: sameFilterValues(selectedTransactionCategoryFilters, allCategories) ? undefined : selectedTransactionCategoryFilters,
      dateFrom: transactionDateFrom || undefined,
      dateTo: transactionDateTo || undefined,
      amountMin: transactionAmountMin,
      amountMax: transactionAmountMax,
      direction: transactionDirection,
      view: transactionView,
      search: transactionSearch || undefined,
      sort: transactionSortKey,
      sortDirection: transactionSortDirection,
      netWorthPeriod: readAppRoute(window.location).filters.netWorthPeriod,
    };
    const nextUrl = routeUrl(activeView, focusedAccountId, filters);
    const currentUrl = `${window.location.pathname}${window.location.search}`;
    if (nextUrl !== currentUrl) window.history.replaceState({}, "", nextUrl);
  }, [
    accounts,
    activeView,
    categories,
    focusedAccountId,
    selectedTransactionAccountFilters,
    selectedTransactionCategoryFilters,
    selectedTransactionMonthFilters,
    selectedTransactionYearFilters,
    transactionAmountMax,
    transactionAmountMin,
    transactionDateFrom,
    transactionDateTo,
    transactionDirection,
    transactionView,
    transactionFiltersInitialized,
    transactionSearch,
    transactionSortDirection,
    transactionSortKey,
    transactions,
  ]);

  useEffect(() => {
    setTransactionPage(1);
  }, [
    activeView,
    focusedAccountId,
    selectedTransactionAccountFilters,
    selectedTransactionMonthFilters,
    selectedTransactionYearFilters,
    selectedTransactionCategoryFilters,
    transactionAmountMax,
    transactionAmountMin,
    transactionDateFrom,
    transactionDateTo,
    transactionDirection,
    transactionSortKey,
    transactionSortDirection,
    transactionSearch,
    transactionView,
  ]);

  useEffect(() => {
    if (!csrf) return;
    api<TransactionRow[]>(`/api/transactions?view=${transactionView}`)
      .then((rows) => {
        setTransactions(rows);
        setSelectedTransactionIds([]);
        setFocusedTransactionId(null);
        setEditingTransactionId(null);
      })
      .catch(() => undefined);
  }, [csrf, transactionView]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") {
        return;
      }
      setEditingTransactionId(null);
      setFocusedTransactionId(null);
      setCategoryEditor(null);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
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
    const [dashboardData, accountsData, reviewData, transactionData, rulesData, categoryData, cashFlowData, netWorthData, allocationData, holdingsData, transferData, inboxData, operationData] = await Promise.all([
      api<DashboardSummary>("/api/dashboard/summary"),
      api<AccountSummary[]>("/api/accounts"),
      api<ReviewItem[]>("/api/review"),
      api<TransactionRow[]>(`/api/transactions?view=${transactionView}`),
      api<RuleSummary[]>("/api/rules"),
      api<CategoryTotal[]>(categoryTotalsPath(reportPeriod)),
      api<MonthlyCashFlow[]>("/api/cash-flow"),
      api<NetWorthAccount[]>("/api/net-worth/accounts"),
      api<AllocationRow[]>("/api/investments/allocation"),
      api<HoldingRow[]>("/api/investments/holdings"),
      api<TransferCandidate[]>("/api/transfers/unconfirmed"),
      api<ImportInboxState>("/api/imports/inbox"),
      api<OperationSummary[]>("/api/operations?limit=100"),
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
    setImportInbox(inboxData);
    setOperations(operationData);
  }

  function showToast(nextToast: ToastState) {
    setToast(nextToast);
  }

  async function undoLoggedOperation(operationId: string, unconflictedOnly = false) {
    setBusyAction(`undo-${operationId}`);
    try {
      const response = await fetch(apiUrl(`/api/operations/${operationId}/undo`), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", "x-csrf-token": csrf },
        body: JSON.stringify({ unconflicted_only: unconflictedOnly }),
      });
      if (response.status === 409) {
        const payload = await response.json() as { detail?: { conflicts?: string[] } };
        const count = payload.detail?.conflicts?.length ?? 0;
        showToast({ tone: "info", message: `${count} row${count === 1 ? " was" : "s were"} changed later. You can undo only the unaffected rows.`, operationId, unconflictedOnly: true });
        return;
      }
      if (!response.ok) throw new Error(await readableApiError(response, `/api/operations/${operationId}/undo`));
      const result = await parseApiJson<{ operation_id: string; undone: number }>(response, `/api/operations/${operationId}/undo`);
      await loadData();
      setExpandedOperationId(null);
      setExpandedOperation(null);
      showToast({ tone: "success", message: `Reverted ${result.undone} row${result.undone === 1 ? "" : "s"}.`, operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "This change could not be undone." });
    } finally {
      setBusyAction(null);
    }
  }

  async function toggleOperationDetail(operationId: string) {
    if (expandedOperationId === operationId) {
      setExpandedOperationId(null);
      setExpandedOperation(null);
      return;
    }
    try {
      const detail = await api<OperationDetail>(`/api/operations/${operationId}`);
      setExpandedOperationId(operationId);
      setExpandedOperation(detail);
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Activity details could not be loaded." });
    }
  }

  async function restoreDeletedTransaction(transaction: TransactionRow) {
    try {
      const result = await api<{ operation_id: string }>(`/api/transactions/${transaction.id}/restore`, { method: "POST", headers: { "x-csrf-token": csrf } });
      await loadData();
      showToast({ tone: "success", message: `Restored “${transaction.raw_description}”.`, operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Transaction could not be restored." });
    }
  }

  async function restoreSelectedTransactions(ids: number[]) {
    try {
      const result = await api<{ operation_id: string; restored: number }>("/api/transactions/bulk-restore", { method: "POST", headers: { "x-csrf-token": csrf }, body: JSON.stringify({ ids }) });
      setSelectedTransactionIds([]);
      await loadData();
      showToast({ tone: "success", message: `Restored ${result.restored} transactions.`, operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Transactions could not be restored." });
    }
  }

  async function openTransactionPeek(from: string, to: string) {
    try {
      const rows = await api<TransactionRow[]>(`/api/transactions?dateFrom=${from}&dateTo=${to}`);
      setPeekDrawer({ title: `${formatShortDate(from)} – ${formatShortDate(to)}`, from, to, rows: rows.slice(0, 20) });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Transaction preview could not be loaded." });
    }
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
    setBusyAction("auth");
    try {
      await api("/api/setup", { method: "POST", body: JSON.stringify({ password }) });
      setConfigured(true);
      setPassword("");
      showToast({ tone: "success", message: "Workspace initialized. Sign in with your new password." });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Setup failed.");
    } finally {
      setBusyAction(null);
    }
  }

  async function handleLogin() {
    setErrorMessage("");
    setBusyAction("auth");
    try {
      const result = await api<{ csrf_token: string }>("/api/login", { method: "POST", body: JSON.stringify({ password }) });
      setCsrf(result.csrf_token);
      setPassword("");
      await loadData();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Login failed.");
    } finally {
      setBusyAction(null);
    }
  }

  async function handleLogout() {
    try {
      await api("/api/logout", { method: "POST", headers: { "x-csrf-token": csrf } });
    } catch {
      // Even if the server call fails, drop local session state.
    }
    setCsrf("");
    setPassword("");
    showToast({ tone: "success", message: "Signed out." });
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

  async function setAccountStatus(account: AccountSummary, status: "active" | "archived") {
    try {
      await api(`/api/accounts/${account.id}`, {
        method: "PATCH",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ status }),
      });
      if (status === "archived" && focusedAccountId === account.id) {
        navigateToView("all-accounts");
      }
      await loadData();
      showToast({ tone: "success", message: status === "archived" ? `${account.display_name} moved to Archived Accounts.` : `${account.display_name} restored.` });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Account status could not be updated." });
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
    if (busyAction) {
      return;
    }
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
    setBusyAction("import");
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
    } finally {
      setBusyAction(null);
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
    setBusyAction("import");
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
      const result = (await response.json()) as { inserted: number; skipped: number; operation_id?: string };
      setImportPreview(null);
      setSelectedFile(null);
      await loadData();
      showToast({ tone: "success", message: `Imported ${result.inserted} rows. Skipped ${result.skipped} duplicates.`, operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Import failed." });
    } finally {
      setBusyAction(null);
    }
  }

  async function updateTransaction(transactionId: number, patch: Partial<Pick<TransactionRow, "account_id" | "category_id" | "transaction_type" | "review_status" | "user_note">>, refreshAfterSave = false) {
    setToast(null);
    try {
      const result = await api<{ operation_id: string }>(`/api/transactions/${transactionId}`, {
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
      showToast({ tone: "success", message: "Transaction updated.", operationId: result.operation_id });
      return result.operation_id;
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Transaction could not be updated." });
      return undefined;
    }
  }

  async function deleteOrMergeCategory() {
    if (!editingCategoryId) return;
    const category = categories.find((item) => item.id === editingCategoryId);
    const replacement = categories.find((item) => item.id === categoryReassignId);
    try {
      const suffix = replacement ? `?reassign_to=${replacement.id}` : "";
      await api(`/api/categories/${editingCategoryId}${suffix}`, { method: "DELETE", headers: { "x-csrf-token": csrf } });
      setCategories((current) => current.filter((item) => item.id !== editingCategoryId));
      setEditingCategoryId(null);
      setEditingCategoryLabel("");
      setCategoryReassignId("");
      await loadData();
      showToast({ tone: "success", message: replacement ? `${category?.label ?? "Category"} merged into ${replacement.label}.` : "Unused category deleted." });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Category could not be deleted." });
    }
  }

  async function openSplitEditor(transaction: TransactionRow) {
    try {
      const existing = await api<Array<{ category_id: number; amount_cents: number; note: string | null }>>(`/api/transactions/${transaction.id}/splits`);
      const rows = existing.length > 0
        ? existing.map((split) => ({ category_id: split.category_id, amount: centsToInput(split.amount_cents), note: split.note ?? "" }))
        : [{ category_id: transaction.category_id ?? categories[0]?.id ?? "", amount: centsToInput(transaction.amount_cents), note: "" }];
      setMonthlyAllocationEditor(null);
      setSplitEditor({ transactionId: transaction.id, rows });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Could not load splits." });
    }
  }

  async function saveSplits(transaction: TransactionRow) {
    if (!splitEditor || splitEditor.transactionId !== transaction.id) return;
    const splits = splitEditor.rows.map((split) => ({
      category_id: Number(split.category_id),
      amount_cents: moneyInputToCents(split.amount),
      note: split.note.trim() || null,
    }));
    if (splits.length < 2 || splits.some((split) => !split.category_id || split.amount_cents === null)) {
      showToast({ tone: "error", message: "Add at least two categories and valid amounts." });
      return;
    }
    if (splits.reduce((sum, split) => sum + (split.amount_cents ?? 0), 0) !== transaction.amount_cents) {
      showToast({ tone: "error", message: `Split amounts must add up to ${formatMoney(transaction.amount_cents)}.` });
      return;
    }
    setBusyAction(`split-${transaction.id}`);
    try {
      await api(`/api/transactions/${transaction.id}/splits`, { method: "POST", headers: { "x-csrf-token": csrf }, body: JSON.stringify({ splits }) });
      setSplitEditor(null);
      await loadData();
      showToast({ tone: "success", message: "Transaction split saved." });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Split could not be saved." });
    } finally {
      setBusyAction(null);
    }
  }

  async function saveMonthlyAllocation(transaction: TransactionRow) {
    if (!monthlyAllocationEditor || monthlyAllocationEditor.transactionId !== transaction.id || !monthlyAllocationEditor.category_id) return;
    const months = inclusiveMonthCount(monthlyAllocationEditor.start_month, monthlyAllocationEditor.end_month);
    if (months < 2 || months > 120) {
      showToast({ tone: "error", message: "Choose a range from 2 to 120 months." });
      return;
    }
    setBusyAction(`allocation-${transaction.id}`);
    try {
      await api(`/api/transactions/${transaction.id}/monthly-allocation`, {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ category_id: monthlyAllocationEditor.category_id, months, allocation_start: `${monthlyAllocationEditor.start_month}-01` }),
      });
      setMonthlyAllocationEditor(null);
      await loadData();
      showToast({ tone: "success", message: `Expense spread evenly from ${monthlyAllocationEditor.start_month} through ${monthlyAllocationEditor.end_month}.` });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Monthly allocation could not be saved." });
    } finally {
      setBusyAction(null);
    }
  }

  async function removeMonthlyAllocation(transaction: TransactionRow) {
    setBusyAction(`allocation-${transaction.id}`);
    try {
      await api(`/api/transactions/${transaction.id}/monthly-allocation`, { method: "DELETE", headers: { "x-csrf-token": csrf } });
      await loadData();
      showToast({ tone: "success", message: "Monthly spread removed; the expense is again counted on its charge date." });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Monthly allocation could not be removed." });
    } finally {
      setBusyAction(null);
    }
  }

  function exitTransactionEdit() {
    setEditingTransactionId(null);
    setFocusedTransactionId(null);
    setCategoryEditor(null);
    setSplitEditor(null);
    setMonthlyAllocationEditor(null);
  }

  async function confirmTransactionEdit(transaction: TransactionRow, noteValue?: string) {
    if (noteValue !== undefined && noteValue !== (transaction.user_note ?? "")) {
      await updateTransaction(transaction.id, { user_note: noteValue }, false);
    }
    exitTransactionEdit();
  }

  async function bulkUpdateSelectedTransactions() {
    if (selectedRepositoryTransactionIds.length === 0) {
      showToast({ tone: "error", message: "Select one or more transactions first." });
      return;
    }
    if (!bulkEditValue.trim()) {
      showToast({ tone: "error", message: "Choose or enter the new value first." });
      return;
    }
    try {
      const result = await api<{ updated: number; affected_accounts: number; operation_id: string }>("/api/transactions/bulk-update", {
        method: "PATCH",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ ids: selectedRepositoryTransactionIds, field: bulkEditField, value: bulkEditValue }),
      });
      await loadData();
      setBulkEditValue("");
      setBulkEditorOpen(false);
      setSelectedTransactionIds((current) => current.filter((id) => !selectedRepositoryTransactionIds.includes(id)));
      const accountNote = result.affected_accounts ? ` This changed ${result.affected_accounts} account record${result.affected_accounts === 1 ? "" : "s"}.` : "";
      const fieldLabel = bulkTransactionFields.find((field) => field.value === bulkEditField)?.label.toLowerCase() ?? "value";
      showToast({ tone: "success", message: `Updated ${fieldLabel} for ${result.updated} transaction${result.updated === 1 ? "" : "s"}.${accountNote}`, operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Bulk transaction update failed." });
    }
  }

  async function cleanupImportedAccounts() {
    setToast(null);
    try {
      const result = await api<{ updated: number; merged: number; moved_transactions: number }>("/api/accounts/cleanup-imported", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
      });
      await loadData();
      showToast({
        tone: "success",
        message: `Cleaned imported accounts: ${result.updated} updated, ${result.merged} merged, ${result.moved_transactions} transactions moved.`,
      });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Imported account cleanup failed." });
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
    setBusyAction("restore");
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
    } finally {
      setBusyAction(null);
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
    setBusyAction("import");
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
    } finally {
      setBusyAction(null);
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
    if (!accounts.some((account) => account.id === transaction.account_id)) {
      showToast({ tone: "error", message: "Choose an account before confirming this transaction." });
      return;
    }
    if (transaction.transaction_type === "expense" && !transaction.category_id) {
      showToast({ tone: "error", message: "Choose a category before confirming an expense." });
      return;
    }
    const operationId = await updateTransaction(transaction.id, { review_status: "confirmed" });
    if (operationId) showToast({ tone: "success", message: "Transaction confirmed.", operationId });
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

  async function previewRule(ruleId: number) {
    try {
      const result = await api<{ matched: number }>(`/api/rules/${ruleId}/preview?scope=unreviewed`);
      setRuleFeedback({ ruleId, message: `Matches ${result.matched} unreviewed transaction${result.matched === 1 ? "" : "s"}.` });
    } catch (error) {
      setRuleFeedback({ ruleId, message: error instanceof Error ? error.message : "Rule preview failed." });
    }
  }

  async function saveRuleEdit() {
    if (!editingRule || !editingRule.match_text.trim()) return;
    try {
      await api(`/api/rules/${editingRule.id}`, {
        method: "PATCH",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({
          category_id: editingRule.category_id,
          match_text: editingRule.match_text.trim(),
          suggested_transaction_type: editingRule.suggested_transaction_type,
          priority: editingRule.priority,
        }),
      });
      setEditingRule(null);
      await loadData();
      showToast({ tone: "success", message: "Rule updated." });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Rule could not be updated." });
    }
  }

  async function deleteRule(rule: RuleSummary) {
    try {
      await api(`/api/rules/${rule.id}`, { method: "DELETE", headers: { "x-csrf-token": csrf } });
      if (editingRule?.id === rule.id) setEditingRule(null);
      await loadData();
      showToast({ tone: "success", message: `Rule “${rule.match_text}” deleted.` });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Rule could not be deleted." });
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
          const range = visibleIds.slice(from, to + 1);
          const rangeIsSelected = range.every((id) => next.has(id));
          range.forEach((id) => rangeIsSelected ? next.delete(id) : next.add(id));
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
      let operationId: string | undefined;
      if (deleteTarget.kind === "transaction_bulk") {
        const result = await api<{ operation_id: string }>("/api/transactions/bulk-delete", {
          method: "DELETE",
          headers: { "x-csrf-token": csrf },
          body: JSON.stringify({ ids: deleteTarget.ids, confirm_text: deleteConfirmText }),
        });
        operationId = result.operation_id;
      } else if (deleteTarget.kind === "transaction_bulk_permanent") {
        await api("/api/transactions/bulk-permanent-delete", {
          method: "DELETE",
          headers: { "x-csrf-token": csrf },
          body: JSON.stringify({ ids: deleteTarget.ids, confirm_text: deleteConfirmText }),
        });
      } else if (deleteTarget.kind === "transaction_permanent") {
        await api(`/api/transactions/${deleteTarget.id}/permanent`, {
          method: "DELETE",
          headers: { "x-csrf-token": csrf },
          body: JSON.stringify({ confirm_text: deleteConfirmText }),
        });
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
        const result = await api<{ operation_id?: string }>(path, {
          method: "DELETE",
          headers: { "x-csrf-token": csrf },
          body: JSON.stringify({ confirm_text: deleteConfirmText }),
        });
        operationId = result.operation_id;
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
      const permanent = deletedKind.includes("permanent");
      showToast({ tone: "success", message: permanent ? "Transaction data permanently deleted." : deletedKind.includes("bulk") ? "Selected rows moved to Trash." : "Row moved to Trash.", operationId });
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
    const balances = new Map<number, number>();
    for (const account of accounts) {
      balances.set(account.id, account.sidebar_balance_cents);
    }
    return balances;
  }, [accounts]);
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
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void handleSetup();
            }}
          >
            <label className="visuallyHidden" htmlFor="setup-password">
              New password
            </label>
            <input
              id="setup-password"
              type="password"
              autoComplete="new-password"
              autoFocus
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Create password, 12+ characters"
              aria-describedby={errorMessage ? "auth-error" : undefined}
            />
            {errorMessage ? (
              <p className="formError" id="auth-error" role="alert">
                {errorMessage}
              </p>
            ) : null}
            <button className="primaryButton" type="submit" disabled={busyAction === "auth"}>
              <CheckCircle2 size={16} />
              Initialize
            </button>
          </form>
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
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void handleLogin();
            }}
          >
            <label className="visuallyHidden" htmlFor="login-password">
              Password
            </label>
            <input
              id="login-password"
              type="password"
              autoComplete="current-password"
              autoFocus
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Password"
              aria-describedby={errorMessage ? "auth-error" : undefined}
            />
            {errorMessage ? (
              <p className="formError" id="auth-error" role="alert">
                {errorMessage}
              </p>
            ) : null}
            <button className="primaryButton" type="submit" disabled={busyAction === "auth"}>
              <ShieldCheck size={16} />
              Sign in
            </button>
          </form>
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
  const normalizedTransactionSearch = transactionSearch.trim().toLowerCase();
  const transactionMatchesSearch = (transaction: TransactionRow) => {
    if (!normalizedTransactionSearch) return true;
    const category = categories.find((item) => item.id === transaction.category_id)?.label ?? "";
    const splitLabel = transaction.split_count > 0 ? `split split categories split into ${transaction.split_count} categories` : "";
    const allocationLabel = transaction.monthly_allocation_count > 0 ? `spread spread across months spread across ${transaction.monthly_allocation_count} months monthly allocation` : "";
    return [transaction.raw_description, transaction.user_note, transaction.account_name, transaction.institution_name, transaction.transaction_type, category, splitLabel, allocationLabel, formatMoney(transaction.amount_cents), transaction.transaction_date]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(normalizedTransactionSearch));
  };
  const reviewTransactions = transactions.filter((transaction) => ["needs_review", "suggested", "possible_duplicate"].includes(transaction.review_status) && transactionMatchesSearch(transaction));
  const visibleReviewTransactions = reviewTransactions.slice(0, 5);
  const activeAccounts = accounts.filter((account) => account.status === "active");
  const archivedAccounts = accounts.filter((account) => account.status === "archived");
  const bankAccounts = activeAccounts.filter((account) => bankAccountTypes.has(account.account_type));
  const creditCardAccounts = activeAccounts.filter((account) => creditCardAccountTypes.has(account.account_type));
  const brokerageAccounts = activeAccounts.filter((account) => brokerageAccountTypes.has(account.account_type));
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
      .filter(transactionMatchesSearch)
      .filter((transaction) => selectedTransactionMonthFilters.includes(transaction.transaction_date.slice(5, 7)))
      .filter((transaction) => selectedTransactionYearFilters.includes(transaction.transaction_date.slice(0, 4)))
      .filter((transaction) => selectedTransactionCategoryFilters.includes(transaction.category_id ? String(transaction.category_id) : uncategorizedFilterValue))
      .filter((transaction) => !transactionDateFrom || transaction.transaction_date >= transactionDateFrom)
      .filter((transaction) => !transactionDateTo || transaction.transaction_date <= transactionDateTo)
      .filter((transaction) => transactionAmountMin === undefined || Math.abs(transaction.amount_cents) >= transactionAmountMin)
      .filter((transaction) => transactionAmountMax === undefined || Math.abs(transaction.amount_cents) <= transactionAmountMax)
      .filter((transaction) => transactionDirection === undefined || (transactionDirection === "inflow" ? transaction.amount_cents > 0 : transaction.amount_cents < 0));
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
  const allRepositoryTransactionsSelected = repositoryTransactionIds.length > 0 && selectedRepositoryTransactionIds.length === repositoryTransactionIds.length;
  const accountIds = accounts.map((account) => account.id);
  const selectedVisibleAccountIds = accountIds.filter((id) => selectedAccountIds.includes(id));
  const visibleHoldingIds = holdingRows.slice(0, 12).map((row) => row.id);
  const selectedVisibleHoldingIds = visibleHoldingIds.filter((id) => selectedHoldingIds.includes(id));
  const periodCashFlowRows = cashFlowRows.filter((row) => isMonthInReportPeriod(row.month, reportPeriod));
  const reportIncomeCents = periodCashFlowRows.reduce((sum, row) => sum + row.income_cents, 0);
  const reportExpenseCents = periodCashFlowRows.reduce((sum, row) => sum + row.expense_cents, 0);
  const reportNetCents = periodCashFlowRows.reduce((sum, row) => sum + row.net_cents, 0);
  const periodCategoryTotals = categoryTotals;
  const netWorthCents = netWorthAccounts.reduce((sum, row) => sum + row.market_value_cents, 0);
  const taxonomySections: TaxonomySection[] = [
    { label: "Bank Accounts", rows: bankAccounts, emptyText: "No bank accounts yet." },
    { label: "Credit Cards", rows: creditCardAccounts, emptyText: "No credit cards yet." },
    { label: "Brokerages", rows: brokerageAccounts, emptyText: "No brokerages yet." },
  ];
  const taxonomyTree = taxonomySections.map((section) => ({
    ...section,
    totalCents: section.rows.reduce((sum, account) => sum + (accountBalances.get(account.id) ?? 0), 0),
    groups: buildTaxonomyGroups(section.rows, accountBalances, taxonomyOverrides),
  }));
  const sidebarTaxonomyTree = archivedAccounts.length > 0
    ? [...taxonomyTree, {
        label: "Archived Accounts",
        rows: archivedAccounts,
        emptyText: "",
        totalCents: archivedAccounts.reduce((sum, account) => sum + (accountBalances.get(account.id) ?? 0), 0),
        groups: buildTaxonomyGroups(archivedAccounts, accountBalances, taxonomyOverrides),
      }]
    : taxonomyTree;
  const latestCashFlowRows = periodCashFlowRows.slice(-4).reverse();
  const reviewCount = reviewTransactions.length;
  const accountNeedingTaxonomy = accounts.find((account) => !taxonomyOverrides[String(account.id)] && !account.institution_name);
  const transactionFilterChips: Array<{ key: string; label: string; onRemove: () => void }> = [];
  if (activeView === "account" && focusedAccount) {
    transactionFilterChips.push({ key: "account-route", label: `Account: ${accountOptionLabel(focusedAccount)}`, onRemove: () => navigateToView("all-accounts") });
  } else if (activeView === "all-accounts" && !sameFilterValues(selectedTransactionAccountFilters, accounts.map((account) => account.id))) {
    transactionFilterChips.push({ key: "accounts", label: selectionSummary("Accounts", selectedTransactionAccountFilters.map(String), accounts.map((account) => ({ value: String(account.id), label: accountOptionLabel(account) }))), onRemove: () => setSelectedTransactionAccountFilters(accounts.map((account) => account.id)) });
  }

  async function scanImportInbox() {
    setBusyAction("inbox-scan");
    try {
      const result = await api<ImportInboxScan>("/api/imports/inbox/scan", { method: "POST", headers: { "x-csrf-token": csrf } });
      setImportInbox({ folder: result.folder, pending: result.pending });
      setLastInboxScan(result);
      const followUpCount = result.needs_account.length + result.errors.length;
      showToast({
        tone: followUpCount ? "info" : "success",
        message: `${result.staged.length} file${result.staged.length === 1 ? "" : "s"} staged, ${result.skipped.length} already recorded${followUpCount ? `, ${followUpCount} need attention` : ""}.`,
      });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Import inbox could not be scanned." });
    } finally {
      setBusyAction(null);
    }
  }

  async function confirmInboxBatch(batch: InboxBatch) {
    setBusyAction(`inbox-confirm-${batch.id}`);
    try {
      const result = await api<{ inserted: number; skipped: number; operation_id?: string }>(`/api/imports/${batch.id}/confirm`, { method: "POST", headers: { "x-csrf-token": csrf } });
      await loadData();
      showToast({ tone: "success", message: `Imported ${result.inserted} rows from ${batch.filename}. ${result.skipped} duplicates skipped.`, operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Inbox import could not be confirmed." });
    } finally {
      setBusyAction(null);
    }
  }

  async function discardInboxBatch(batch: InboxBatch) {
    setBusyAction(`inbox-discard-${batch.id}`);
    try {
      await api(`/api/imports/${batch.id}/discard`, { method: "POST", headers: { "x-csrf-token": csrf } });
      setImportInbox((current) => ({ ...current, pending: current.pending.filter((item) => item.id !== batch.id) }));
      showToast({ tone: "info", message: `${batch.filename} was removed from pending review. The source file was not changed.` });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Inbox import could not be discarded." });
    } finally {
      setBusyAction(null);
    }
  }
  if (transactionSearch.trim()) transactionFilterChips.push({ key: "search", label: `Search: ${transactionSearch.trim()}`, onRemove: () => setTransactionSearch("") });
  if (!sameFilterValues(selectedTransactionMonthFilters, monthOptions.map((month) => month.value))) transactionFilterChips.push({ key: "months", label: selectionSummary("Months", selectedTransactionMonthFilters, monthOptions), onRemove: () => setSelectedTransactionMonthFilters(monthOptions.map((month) => month.value)) });
  if (!sameFilterValues(selectedTransactionYearFilters, transactionYears)) transactionFilterChips.push({ key: "years", label: selectionSummary("Years", selectedTransactionYearFilters, transactionYears.map((year) => ({ value: year, label: year }))), onRemove: () => setSelectedTransactionYearFilters(transactionYears) });
  if (!sameFilterValues(selectedTransactionCategoryFilters, transactionCategoryOptions.map((option) => option.value))) transactionFilterChips.push({ key: "categories", label: selectionSummary("Categories", selectedTransactionCategoryFilters, transactionCategoryOptions), onRemove: () => setSelectedTransactionCategoryFilters(transactionCategoryOptions.map((option) => option.value)) });
  if (transactionDateFrom) transactionFilterChips.push({ key: "date-from", label: `From: ${formatShortDate(transactionDateFrom)}`, onRemove: () => setTransactionDateFrom("") });
  if (transactionDateTo) transactionFilterChips.push({ key: "date-to", label: `Through: ${formatShortDate(transactionDateTo)}`, onRemove: () => setTransactionDateTo("") });
  if (transactionAmountMin !== undefined) transactionFilterChips.push({ key: "amount-min", label: `Minimum: ${formatMoney(transactionAmountMin)}`, onRemove: () => setTransactionAmountMin(undefined) });
  if (transactionAmountMax !== undefined) transactionFilterChips.push({ key: "amount-max", label: `Maximum: ${formatMoney(transactionAmountMax)}`, onRemove: () => setTransactionAmountMax(undefined) });
  if (transactionDirection) transactionFilterChips.push({ key: "direction", label: transactionDirection === "inflow" ? "Inflows" : "Outflows", onRemove: () => setTransactionDirection(undefined) });

  function startSidebarResize(event: ReactPointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = sidebarWidth;
    const pointerId = event.pointerId;
    event.currentTarget.setPointerCapture(pointerId);
    let latestWidth = startWidth;

    function onPointerMove(moveEvent: PointerEvent) {
      const nextWidth = Math.min(maxSidebarWidth, Math.max(minSidebarWidth, startWidth + moveEvent.clientX - startX));
      latestWidth = nextWidth;
      setSidebarWidth(nextWidth);
    }

    function onPointerUp() {
      window.localStorage.setItem(sidebarWidthStorageKey, String(latestWidth));
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
    }

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp, { once: true });
  }

  function openAccountView(accountId: number) {
    setSelectedAccountId(accountId);
    navigateToView("account", accountId);
    setCategoryEditor(null);
    setFocusedTransactionId(null);
    setEditingTransactionId(null);
  }

  function navigateToView(view: AppView, accountId: number | null = null) {
    const nextAccountId = view === "account" ? accountId : null;
    const nextFilters = readAppRoute(window.location).filters;
    if (view !== "account" && view !== "all-accounts") {
      nextFilters.view = undefined;
      if (transactionView === "trash") setTransactionView("live");
    }
    window.history.pushState({}, "", routeUrl(view, nextAccountId, nextFilters));
    setActiveView(view);
    setFocusedAccountId(nextAccountId);
    setCategoryEditor(null);
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

  function saveTaxonomyOverride() {
    if (!taxonomyAccountId || !taxonomyGroupDraft.trim()) {
      showToast({ tone: "error", message: "Choose an account and enter a group name first." });
      return;
    }
    const next = { ...taxonomyOverrides, [String(taxonomyAccountId)]: taxonomyGroupDraft.trim() };
    setTaxonomyOverrides(next);
    writeStoredJson(taxonomyStorageKey, next);
    showToast({ tone: "success", message: "Account taxonomy updated." });
  }

  function clearTaxonomyOverride() {
    if (!taxonomyAccountId) {
      showToast({ tone: "error", message: "Choose an account to reset." });
      return;
    }
    const next = { ...taxonomyOverrides };
    delete next[String(taxonomyAccountId)];
    setTaxonomyOverrides(next);
    writeStoredJson(taxonomyStorageKey, next);
    setTaxonomyGroupDraft("");
    showToast({ tone: "success", message: "Account now uses its institution as the group." });
  }

  function toggleDashboardWidget(key: DashboardWidgetKey) {
    const next = { ...dashboardWidgets, [key]: !dashboardWidgets[key] };
    setDashboardWidgets(next);
    writeStoredJson(dashboardWidgetStorageKey, next);
  }

  function toggleTaxonomyGroup(sectionLabel: string, groupLabel: string) {
    const key = `${sectionLabel}::${groupLabel}`;
    const currentlyCollapsed = key === "section::Archived Accounts"
      ? collapsedTaxonomyGroups[key] !== false
      : Boolean(collapsedTaxonomyGroups[key]);
    const next = { ...collapsedTaxonomyGroups, [key]: !currentlyCollapsed };
    setCollapsedTaxonomyGroups(next);
    writeStoredJson(collapsedTaxonomyStorageKey, next);
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
      openTransactionEditor(transactionId);
      return;
    }
    setFocusedTransactionId(transactionId);
    setEditingTransactionId(null);
    setCategoryEditor(null);
  }

  function openTransactionEditor(transactionId: number) {
    setFocusedTransactionId(transactionId);
    setEditingTransactionId(transactionId);
    setCategoryEditor(null);
    setSplitEditor(null);
    setMonthlyAllocationEditor(null);
  }

  return (
    <div className="appFrame" style={{ gridTemplateColumns: `${sidebarWidth}px minmax(0, 1fr)` }}>
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
                  navigateToView(item.id);
                }}
              >
                <Icon size={16} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
        {sidebarTaxonomyTree.map((section) => {
          const sectionCollapseKey = `section::${section.label}`;
          const sectionCollapsed = section.label === "Archived Accounts"
            ? collapsedTaxonomyGroups[sectionCollapseKey] !== false
            : Boolean(collapsedTaxonomyGroups[sectionCollapseKey]);
          return (
          <div className="sidebarSection" key={section.label}>
            <button
              className="sidebarSectionHeader"
              type="button"
              aria-expanded={!sectionCollapsed}
              onClick={() => toggleTaxonomyGroup("section", section.label)}
              title={`${sectionCollapsed ? "Expand" : "Collapse"} ${section.label}`}
            >
              {sectionCollapsed ? <ChevronRight size={11} /> : <ChevronDown size={11} />}
              <span>{section.label}</span>
              <span className={section.totalCents < 0 ? "sidebarSectionBalance negative" : "sidebarSectionBalance"}>{formatMoney(section.totalCents)}</span>
            </button>
            {sectionCollapsed ? null : <div className="sidebarAccounts">
              {section.groups.map((group) => {
                const collapseKey = `${section.label}::${group.label}`;
                const isCollapsed = Boolean(collapsedTaxonomyGroups[collapseKey]);
                return (
                  <div className="sidebarTaxonomyGroup" key={`${section.label}-${group.label}`}>
                    <button className="sidebarGroupHeader" type="button" aria-expanded={!isCollapsed} onClick={() => toggleTaxonomyGroup(section.label, group.label)} title={`${isCollapsed ? "Expand" : "Collapse"} ${group.label}`}>
                      <span className="sidebarGroupToggle">{isCollapsed ? <ChevronRight size={10} /> : <ChevronDown size={10} />}</span>
                      <span>{group.label}</span>
                      <span className={group.totalCents < 0 ? "sidebarGroupBalance negative" : "sidebarGroupBalance"}>{formatMoney(group.totalCents)}</span>
                    </button>
                    {isCollapsed
                      ? null
                      : group.rows.map((account) => {
                          const missingCount = missingCategoryCountByAccount.get(account.id) ?? 0;
                          const isActive = activeView === "account" && focusedAccountId === account.id;
                          return (
                            <button key={account.id} className={isActive ? "sidebarAccount active" : "sidebarAccount"} onClick={() => openAccountView(account.id)} title={`${account.display_name} · ${sidebarBalanceLabel(account)}`}>
                              <span className={missingCount > 0 ? "attentionDot" : "attentionDot hidden"} />
                              <span className="sidebarAccountName">
                                {account.display_name}
                                {account.last_four ? ` (${account.last_four})` : ""}
                              </span>
                              <span className="sidebarAccountBalanceWrap">
                                <span className={(accountBalances.get(account.id) ?? 0) < 0 ? "sidebarAccountBalance negative" : "sidebarAccountBalance"}>{formatMoney(accountBalances.get(account.id) ?? 0)}</span>
                                {account.sidebar_balance_kind === "recent_activity" ? <small>30d</small> : null}
                              </span>
                            </button>
                          );
                        })}
                  </div>
                );
              })}
              {section.rows.length === 0 ? <p className="emptyText" style={{ color: "rgba(245,247,255,0.55)", padding: "0 12px" }}>{section.emptyText}</p> : null}
            </div>}
          </div>
        );})}
        <div className="sidebarFooter">
          <button className="taxonomyToggleButton" onClick={() => setTaxonomyEditorOpen((current) => !current)}>
            <span className="sidebarActionIcon">
              <Sparkles size={11} />
            </span>
            <span>Customize Taxonomy</span>
          </button>
          {taxonomyEditorOpen ? (
            <div className="taxonomyEditor">
              <label>Account</label>
              <select
                value={taxonomyAccountId}
                onChange={(event) => {
                  const nextId = event.target.value ? Number(event.target.value) : "";
                  setTaxonomyAccountId(nextId);
                  const account = accounts.find((candidate) => candidate.id === nextId);
                  setTaxonomyGroupDraft(account ? taxonomyLabelForAccount(account, taxonomyOverrides) : "");
                }}
              >
                <option value="">Choose account</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.display_name}
                  </option>
                ))}
              </select>
              <label>Group under</label>
              <input value={taxonomyGroupDraft} onChange={(event) => setTaxonomyGroupDraft(event.target.value)} placeholder="Chase, BoA, Fidelity..." />
              <div className="taxonomyActions">
                <button onClick={saveTaxonomyOverride}>Save</button>
                <button onClick={clearTaxonomyOverride}>Reset</button>
              </div>
              <p>{accountNeedingTaxonomy ? `${accountNeedingTaxonomy.display_name} still needs an institution or custom group.` : "Defaults come from each account's institution."}</p>
            </div>
          ) : null}
          <button
            className="addAccountButton"
            onClick={() => {
              setImportWorkspaceTab("manual");
              setImportModalOpen(true);
            }}
          >
            <span className="sidebarActionIcon">
              <Plus size={11} />
            </span>
            Add Account
          </button>
          <button className="taxonomyToggleButton" onClick={() => void handleLogout()}>
            <span className="sidebarActionIcon">
              <LogOut size={11} />
            </span>
            <span>Sign out</span>
          </button>
        </div>
        <button className="sidebarResizeHandle" aria-label="Resize sidebar" title="Drag to resize sidebar" onPointerDown={startSidebarResize} />
      </aside>

      <main className="workspace">
        {toast ? (
          <div className={`toast ${toast.tone}`} style={{ margin: "16px 20px 0" }} role="status" aria-live="polite">
            {toast.tone === "success" ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
            <span>{toast.message}</span>
            {toast.operationId ? (
              <button className="toastAction" onClick={() => void undoLoggedOperation(toast.operationId!, toast.unconflictedOnly)} disabled={busyAction === `undo-${toast.operationId}`}>
                {toast.unconflictedOnly ? "Undo safe rows" : "Undo"}
              </button>
            ) : null}
            <button className="toastClose" onClick={() => setToast(null)} aria-label="Dismiss notification">
              <X size={14} />
            </button>
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
              <MetricTile label="Income" value={formatMoney(cashFlowRows.length > 0 ? reportIncomeCents : totalIncomeCents)} tone="green" />
              <MetricTile label="Expenses" value={formatMoney(cashFlowRows.length > 0 ? reportExpenseCents : totalExpenseCents)} tone="red" />
              <MetricTile label="Net" value={formatMoney(cashFlowRows.length > 0 ? reportNetCents : netIncomeCents)} tone="neutral" />
              <MetricTile label="Savings rate" value={`${savingsRate}%`} tone="neutral" />
            </section>

            <section className="dashboardControls overviewTools">
              <div>
                <span className="eyebrow">Custom dashboard</span>
                <h2>Your finance cockpit</h2>
                <p>Toggle the cards that help you decide what needs attention next.</p>
              </div>
              <button className="secondaryButton" onClick={() => setDashboardCustomizeOpen((current) => !current)}>
                <Sparkles size={16} />
                Customize
              </button>
            </section>
            {dashboardCustomizeOpen ? (
              <section className="dashboardCustomizer overviewTools">
                {dashboardWidgetOptions.map((option) => (
                  <label className="widgetToggle" key={option.key}>
                    <input type="checkbox" checked={dashboardWidgets[option.key]} onChange={() => toggleDashboardWidget(option.key)} />
                    <span>
                      <strong>{option.label}</strong>
                      <small>{option.description}</small>
                    </span>
                  </label>
                ))}
              </section>
            ) : null}

            <section className="dashboardWidgetGrid overviewTools" aria-label="Dashboard widgets">
              {dashboardWidgets.taxonomy ? (
                <article className="dashboardWidget wide">
                  <div className="widgetHeader">
                    <span className="eyebrow">Account map</span>
                    <strong>{formatMoney(taxonomyTree.reduce((sum, section) => sum + section.totalCents, 0))}</strong>
                  </div>
                  <div className="taxonomySummaryRows">
                    {taxonomyTree.map((section) => (
                      <div className="taxonomySummaryRow" key={section.label}>
                        <div>
                          <strong>{section.label}</strong>
                          <span>{section.groups.length} group{section.groups.length === 1 ? "" : "s"}</span>
                        </div>
                        <span>{formatMoney(section.totalCents)}</span>
                      </div>
                    ))}
                  </div>
                </article>
              ) : null}

              {dashboardWidgets.review ? (
                <article className="dashboardWidget">
                  <div className="widgetHeader">
                    <span className="eyebrow">Review workload</span>
                    <strong>{reviewCount}</strong>
                  </div>
                  <p>{reviewCount === 0 ? "No transactions are waiting for review." : "Categorize, confirm, or resolve these before trusting reports."}</p>
                  <button className="secondaryButton compactButton" onClick={() => navigateToView("review")}>
                    Open Review
                  </button>
                </article>
              ) : null}

              {dashboardWidgets.spending ? (
                <article className="dashboardWidget">
                  <div className="widgetHeader">
                    <span className="eyebrow">Top spending</span>
                    <strong>{periodCategoryTotals.length}</strong>
                  </div>
                  <div className="miniRankList">
                    {periodCategoryTotals.slice(0, 4).map((row) => (
                      <div key={row.category}>
                        <span>{row.category}</span>
                        <strong>{formatMoney(row.amount_cents)}</strong>
                      </div>
                    ))}
                    {periodCategoryTotals.length === 0 ? <p className="emptyText">No categorized expenses in this period yet.</p> : null}
                  </div>
                </article>
              ) : null}

              {dashboardWidgets.cashflow ? (
                <article className="dashboardWidget">
                  <div className="widgetHeader">
                    <span className="eyebrow">Cash-flow trend</span>
                    <strong>{formatMoney(reportNetCents)}</strong>
                  </div>
                  <div className="miniRankList">
                    {latestCashFlowRows.map((row) => (
                      <div key={row.month}>
                        <span>{row.month}</span>
                        <strong className={row.net_cents < 0 ? "amount negative" : "amount positive"}>{formatMoney(row.net_cents)}</strong>
                      </div>
                    ))}
                    {latestCashFlowRows.length === 0 ? <p className="emptyText">Import transactions to build a monthly trend.</p> : null}
                  </div>
                </article>
              ) : null}

              {dashboardWidgets.imports ? (
                <article className="dashboardWidget">
                  <div className="widgetHeader">
                    <span className="eyebrow">Import readiness</span>
                    <strong>{accounts.length}</strong>
                  </div>
                  <p>{accounts.length === 0 ? "Start with a CSV so the app can suggest or create accounts." : "Use Smart import when you have a new bank, card, or brokerage CSV."}</p>
                  <button className="primaryButton compactButton" onClick={() => openImportModal()}>
                    <FileUp size={14} />
                    Import CSV
                  </button>
                </article>
              ) : null}
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
                  onViewTransactions={(fromDate, toDate) => {
                    setTransactionDateFrom(fromDate);
                    setTransactionDateTo(toDate);
                    navigateToView("all-accounts");
                  }}
                  onPeekTransactions={openTransactionPeek}
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

        {activeView === "history" ? (
          <section className="ledgerPanel activityWorkspace">
            <PanelTitle icon={History} title="Activity" subtitle="Review changes, inspect row-level details, and safely undo mistakes." />
            <div className="activityIntro">
              <div>
                <strong>{operations.length} recent operation{operations.length === 1 ? "" : "s"}</strong>
                <span>Undo is blocked when a later change would be overwritten.</span>
              </div>
              <button className="secondaryButton compactButton" onClick={() => void loadData()}><RefreshCw size={14} /> Refresh</button>
            </div>
            <div className="activityList">
              {operations.map((operation) => (
                <article className={operation.undone_by ? "activityCard undone" : "activityCard"} key={operation.id}>
                  <div className="activityCardHeader">
                    <button className="activitySummary" onClick={() => void toggleOperationDetail(operation.id)} aria-expanded={expandedOperationId === operation.id}>
                      {expandedOperationId === operation.id ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                      <span>
                        <strong>{operation.description}</strong>
                        <small>{new Date(operation.created_at).toLocaleString()} · {operation.change_count} row{operation.change_count === 1 ? "" : "s"} · {operation.actor}</small>
                      </span>
                    </button>
                    <div className="activityActions">
                      {operation.undo_of ? <span className="statusBadge confirmed">Undo</span> : null}
                      {operation.undone_by ? <span className="statusBadge possible-duplicate">Reverted</span> : null}
                      <button className="secondaryButton compactButton" disabled={!operation.can_undo || busyAction === `undo-${operation.id}`} onClick={() => void undoLoggedOperation(operation.id)}>
                        <RotateCcw size={13} /> {operation.kind === "undo" ? "Redo" : "Undo"}
                      </button>
                    </div>
                  </div>
                  {expandedOperationId === operation.id && expandedOperation ? (
                    <div className="activityDiffs">
                      {expandedOperation.changes.map((change) => {
                        const fields = Array.from(new Set([...Object.keys(change.before ?? {}), ...Object.keys(change.after ?? {})])).filter((field) => field !== "id");
                        return (
                          <div className="activityDiff" key={change.id}>
                            <strong>Row {change.entity_id}</strong>
                            {fields.length === 0 ? <span>{change.before ? "Removed" : "Created"}</span> : fields.map((field) => (
                              <div key={field}>
                                <span>{readableAccountType(field)}</span>
                                <code>{formatOperationDiffValue(operation, field, change.before?.[field], "before")}</code>
                                <span>→</span>
                                <code>{formatOperationDiffValue(operation, field, change.after?.[field], "after")}</code>
                              </div>
                            ))}
                          </div>
                        );
                      })}
                    </div>
                  ) : null}
                </article>
              ))}
              {operations.length === 0 ? <p className="emptyText">No recoverable activity has been recorded yet.</p> : null}
            </div>
          </section>
        ) : null}

        {activeView === "account" && focusedAccount ? (
          <div className="stickyAccountChrome">
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
                  <span>{focusedAccount.sidebar_balance_kind === "recent_activity" ? "Last 30 days" : "Current balance"}</span>
                </div>
                <div>
                  <strong>{focusedMissingCategoryCount}</strong>
                  <span>Need category</span>
                </div>
              </div>
              <div className="accountActionBar">
                <button className="primaryButton compactButton" onClick={() => openImportModal(focusedAccount.id)}>
                  <FileUp size={14} />
                  File Import
                </button>
                <button className="secondaryButton compactButton" onClick={() => navigateToView("review")}>
                  <ListChecks size={14} />
                  Open Review
                </button>
                <button className="ghostButton compactIconButton" title="Refresh data" onClick={() => void loadData()}>
                  <RefreshCw size={14} />
                </button>
              </div>
            </header>
            <div className="transactionDiscovery stickyFilters">
              <label className="transactionSearchBox"><Search size={16} /><input value={transactionSearch} onChange={(event) => setTransactionSearch(event.target.value)} placeholder="Search institution, account, description, details, or labels" /></label>
              <div className="transactionFilterRow">
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
            </div>
          </div>
        ) : null}

        {activeView === "all-accounts" ? (
          <div className="stickyAccountChrome">
            <header className="accountLedgerHeader">
              <div>
                <h1>All Accounts</h1>
                <div className="accountMetaRow">
                  <span>{accounts.length} accounts</span>
                  <span>{missingCategoryTransactions.length} need a category</span>
                </div>
              </div>
              <div className="accountActionBar">
                <button className="primaryButton compactButton" onClick={() => openImportModal()}>
                  <FileUp size={14} />
                  File Import
                </button>
                <button className="ghostButton compactIconButton" title="Refresh data" onClick={() => void loadData()}>
                  <RefreshCw size={14} />
                </button>
              </div>
            </header>
            <div className="transactionDiscovery stickyFilters">
              <label className="transactionSearchBox"><Search size={16} /><input value={transactionSearch} onChange={(event) => setTransactionSearch(event.target.value)} placeholder="Search institution, account, description, details, or labels" /></label>
              <div className="transactionFilterRow">
              <MultiSelectFilter
                label="Accounts"
                options={accounts.map((account) => ({ value: String(account.id), label: account.display_name }))}
                selectedValues={selectedTransactionAccountFilters.map(String)}
                onToggle={(value) => setSelectedTransactionAccountFilters((current) => toggleValue(current, Number(value)))}
                onSelectAll={() => setSelectedTransactionAccountFilters(accounts.map((account) => account.id))}
                onDeselectAll={() => setSelectedTransactionAccountFilters([])}
              />
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
            </div>
          </div>
        ) : null}

        {(activeView === "review" || activeView === "settings") && (
        <section className={activeView === "review" ? "workGrid viewSection reviewWorkspace" : "workGrid viewSection settingsWorkspace"}>
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
                <div className="importInboxPanel">
                  <div className="importInboxHeader">
                    <div>
                      <strong>Import Inbox</strong>
                      <span>Copy statement CSVs into this private local folder, then scan and review them before anything is imported.</span>
                      <code>{importInbox.folder || "The inbox folder will be created when the backend starts."}</code>
                    </div>
                    <button className="primaryButton" onClick={() => void scanImportInbox()} disabled={busyAction !== null}>
                      <RefreshCw size={16} />
                      {busyAction === "inbox-scan" ? "Scanning…" : "Scan inbox"}
                    </button>
                  </div>
                  <small>Files stay in place. Their fingerprints prevent accidental re-imports.</small>
                  {lastInboxScan && (lastInboxScan.needs_account.length > 0 || lastInboxScan.errors.length > 0) ? (
                    <div className="inboxScanIssues">
                      {lastInboxScan.needs_account.map((item) => (
                        <div key={`account-${item.filename}`}>
                          <strong>{item.filename}</strong>
                          <span>Needs an account match: {item.reason} Use Smart import below to analyze it manually.</span>
                        </div>
                      ))}
                      {lastInboxScan.errors.map((item) => (
                        <div key={`error-${item.filename}`}>
                          <strong>{item.filename}</strong>
                          <span>{item.message}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {importInbox.pending.length > 0 ? (
                    <div className="pendingInboxList">
                      {importInbox.pending.map((batch) => (
                        <article className="pendingInboxCard" key={batch.id}>
                          <div className="pendingInboxTitle">
                            <div>
                              <strong>{batch.filename}</strong>
                              <span>{batch.preset_type ?? "Detected CSV"} · {batch.row_count} rows</span>
                            </div>
                            <span className="statusBadge suggested">{batch.match_confidence}% match</span>
                          </div>
                          <div className="matchedAccountCard">
                            <Landmark size={16} />
                            <div>
                              <strong>{batch.account_name}{batch.account_last_four && !batch.account_name.endsWith(batch.account_last_four) ? ` (${batch.account_last_four})` : ""}</strong>
                              <span>{batch.match_reason ?? "Matched from the file name and contents."}</span>
                            </div>
                          </div>
                          {batch.preview.length > 0 ? (
                            <div className="inboxPreviewRows">
                              {batch.preview.slice(0, 3).map((row, index) => (
                                <div key={`${batch.id}-${index}`}>
                                  <span>{String(row.transaction_date ?? row.snapshot_date ?? `Row ${index + 1}`)}</span>
                                  <strong>{String(row.raw_description ?? row.description ?? row.symbol ?? row.account_name ?? "Imported row")}</strong>
                                  <span>{String(row.amount ?? row.market_value ?? "")}</span>
                                </div>
                              ))}
                            </div>
                          ) : null}
                          {batch.warnings.length > 0 ? <small>{batch.warnings.join(" ")}</small> : null}
                          <div className="buttonRow">
                            <button className="primaryButton" onClick={() => void confirmInboxBatch(batch)} disabled={busyAction !== null}>Confirm import</button>
                            <button className="secondaryButton" onClick={() => void discardInboxBatch(batch)} disabled={busyAction !== null}>Discard batch</button>
                          </div>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p className="emptyText">No files are waiting for confirmation.</p>
                  )}
                </div>
                <div className="historyImportPanel">
                  <div>
                    <strong>Categorized history import</strong>
                    <span>Upload an older categorized spreadsheet. Expected columns: Account, Posted Date, Payee, Amount, and Expense Category. Missing accounts and categories are created automatically.</span>
                  </div>
                  <div className="buttonRow">
                    <input type="file" accept=".csv,.xlsx,.xlsm" onChange={(event) => { setCategorizedHistoryFile(event.target.files?.[0] ?? null); setCategorizedHistoryRows([]); setCategorizedHistoryFilename(""); }} />
                    <button className="primaryButton" onClick={() => void importCategorizedHistory()} disabled={!categorizedHistoryFile || busyAction !== null}>
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
                    <button className="secondaryButton" onClick={() => void previewSelectedImport()} disabled={!selectedAccountId || !selectedFile || busyAction !== null}>
                      <Search size={16} />
                      Preview
                    </button>
                    <button className="primaryButton" onClick={() => void commitSelectedImport()} disabled={!importPreview || busyAction !== null}>
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
                {!editingAccountId ? <div className="compactForm">
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
                      <Plus size={16} />
                      Add account
                    </button>
                  </div>
                </div> : null}
                <div className="cleanupPanel">
                  <div>
                    <strong>Clean imported account labels</strong>
                    <span>Infer institutions and account types from names like BoA, Chase, Citi, Discover, AMEX, Target, and Venmo. Also merges exact casing duplicates like Checkings/checkings.</span>
                  </div>
                  <button className="secondaryButton" onClick={() => void cleanupImportedAccounts()}>
                    <Sparkles size={16} />
                    Clean imported accounts
                  </button>
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
                      <div className={editingAccountId === account.id || selectedAccountId === account.id ? "accountRow selected" : "accountRow"}>
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
                          {account.status === "archived" ? "Archived" : accountGroupLabel(account.account_type)} · {readableAccountType(account.account_type)}
                        </small>
                        <div className="inlineActions">
                          <button className="secondaryButton" onClick={() => beginEditAccount(account)} title="Edit account">
                            <Pencil size={14} />
                          </button>
                          <button className="secondaryButton" onClick={() => void setAccountStatus(account, account.status === "archived" ? "active" : "archived")}>
                            {account.status === "archived" ? "Restore" : "Archive"}
                          </button>
                          <button className="dangerTextButton" onClick={() => requestDelete({ kind: "account", id: account.id, label: account.display_name })}>
                            Delete
                          </button>
                        </div>
                      </div>
                      {editingAccountId === account.id ? (
                        <section
                          className="accountInlineEditor"
                          aria-label={`Edit ${account.display_name}`}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" && !(event.target instanceof HTMLButtonElement)) {
                              event.preventDefault();
                              void saveAccount();
                            }
                          }}
                        >
                          <div className="accountInlineEditorHeader">
                            <strong><Pencil size={15} /> Edit {account.display_name}</strong>
                            <span>Update the account details below, then choose Save account. Press Enter to save at any time.</span>
                          </div>
                          <div className="accountInlineFields">
                            <label>Account name<input autoFocus value={accountForm.display_name} onChange={(event) => setAccountForm({ ...accountForm, display_name: event.target.value })} /></label>
                            <label>Institution<input value={accountForm.institution_name} onChange={(event) => setAccountForm({ ...accountForm, institution_name: event.target.value })} placeholder="Optional" /></label>
                            <label>Account type<select value={accountForm.account_type} onChange={(event) => setAccountForm({ ...accountForm, account_type: event.target.value })}>{accountTypeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
                            <label>Last four<input value={accountForm.last_four} onChange={(event) => setAccountForm({ ...accountForm, last_four: event.target.value })} placeholder="Optional" inputMode="numeric" /></label>
                          </div>
                          <div className="buttonRow">
                            <button type="button" className="primaryButton" onClick={() => void saveAccount()}><Pencil size={15} /> Save account</button>
                            <button type="button" className="secondaryButton" onClick={clearAccountForm}>Cancel</button>
                          </div>
                        </section>
                      ) : null}
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
          <nav className="reviewWorkspaceNav" aria-label="Review workspace sections">
            <a href="#transfer-review">Transfers <span>{transferCandidates.length}</span></a>
            <a href="#review-inbox">Inbox <span>{reviewTransactions.length}</span></a>
            <a href="#saved-rules">Rules <span>{rules.length}</span></a>
          </nav>
          <section className="toolPanel transferReviewPanel" id="transfer-review">
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

          <section className="toolPanel reviewInboxPanel" id="review-inbox">
            <PanelTitle icon={ListChecks} title="Review Inbox" subtitle={`${reviewTransactions.length} items need a human decision.`} />
            <label className="transactionSearchBox reviewSearch"><Search size={14} /><input value={transactionSearch} onChange={(event) => setTransactionSearch(event.target.value)} placeholder="Search review transactions" /></label>
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
                        className={!accounts.some((account) => account.id === transaction.account_id) ? "needsAccountSelect" : ""}
                        aria-label={`Account for ${transaction.raw_description}`}
                        value={transaction.account_id}
                        onChange={(event) => void updateTransaction(transaction.id, { account_id: Number(event.target.value) }, true)}
                      >
                        {!accounts.some((account) => account.id === transaction.account_id) ? <option value={transaction.account_id} disabled>{transaction.account_name}</option> : null}
                        {accounts.map((account) => (
                          <option key={account.id} value={account.id}>{account.display_name}</option>
                        ))}
                      </select>
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
          </section>

          <aside className="toolPanel rulesPanel" id="saved-rules">
            <PanelTitle icon={Sparkles} title="Saved Rules" subtitle="Preview, edit, and apply automatic categorization." />
            {lastSavedRule ? (
              <div className="ruleApplyPanel">
                <div>
                  <strong>Rule saved for "{lastSavedRule.matchText}"</strong>
                  <span>Apply it now to categorize and confirm matching transactions.</span>
                </div>
                <div className="buttonRow">
                  <button className="secondaryButton" onClick={() => void applySavedRule("unreviewed")}>Apply unreviewed</button>
                  <button className="secondaryButton" onClick={() => void applySavedRule("all")}>Apply previous</button>
                </div>
              </div>
            ) : null}
            {rules.length > 0 ? (
              <div className="savedRulesPanel">
                {rules.map((rule) => {
                  const category = categories.find((item) => item.id === rule.category_id);
                  return (
                    <div className="savedRuleGroup" key={rule.id}>
                      <div className="savedRuleRow">
                        <div>
                          <span>{rule.match_text}</span>
                          <small>{category?.label ?? "Unknown category"} / {readableAccountType(rule.suggested_transaction_type)} / priority {rule.priority}</small>
                        </div>
                        <div className="savedRuleActions">
                          <button className="secondaryButton" onClick={() => void previewRule(rule.id)}>Preview</button>
                          <button className="secondaryButton" onClick={() => void applyRule(rule.id, "unreviewed")}>Apply unreviewed</button>
                          <button className="secondaryButton" onClick={() => void applyRule(rule.id, "all")}>Apply previous</button>
                          <button className="secondaryButton" onClick={() => setEditingRule({ ...rule })}>Edit</button>
                          <button className="dangerTextButton" onClick={() => void deleteRule(rule)}>Delete</button>
                        </div>
                      </div>
                      {ruleFeedback?.ruleId === rule.id ? <div className="ruleInlineFeedback" role="status">{ruleFeedback.message}</div> : null}
                      {editingRule?.id === rule.id ? (
                        <div className="ruleEditRow">
                          <label>Contains<input value={editingRule.match_text} onChange={(event) => setEditingRule({ ...editingRule, match_text: event.target.value })} /></label>
                          <label>Category<select value={editingRule.category_id} onChange={(event) => setEditingRule({ ...editingRule, category_id: Number(event.target.value) })}>{categories.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}</select></label>
                          <label>Type<select value={editingRule.suggested_transaction_type} onChange={(event) => setEditingRule({ ...editingRule, suggested_transaction_type: event.target.value })}>{transactionTypes.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select></label>
                          <label>Priority<input type="number" value={editingRule.priority} onChange={(event) => setEditingRule({ ...editingRule, priority: Number(event.target.value) })} /><small>Smaller numbers run first.</small></label>
                          <button className="primaryButton" onClick={() => void saveRuleEdit()}>Save</button>
                          <button className="ghostButton" onClick={() => setEditingRule(null)}>Cancel</button>
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            ) : <div className="rulesEmptyState"><strong>No saved rules yet</strong><span>Choose a category on an inbox item, then select Save rule.</span></div>}
          </aside>
          </>
          ) : null}

          {activeView === "settings" ? (
          <section className="toolPanel categoriesWorkspace">
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
                <div className="categoryManagementEditor">
                  <div className="inlineEdit">
                    <input value={editingCategoryLabel} onChange={(event) => setEditingCategoryLabel(event.target.value)} placeholder="Rename category" />
                    <button className="secondaryButton" onClick={() => void updateCategory()}>Save rename</button>
                  </div>
                  <div className="categoryMergeRow">
                    <select value={categoryReassignId} onChange={(event) => setCategoryReassignId(event.target.value ? Number(event.target.value) : "")}>
                      <option value="">No replacement (delete only if unused)</option>
                      {categories.filter((category) => category.id !== editingCategoryId).map((category) => <option key={category.id} value={category.id}>Merge into {category.label}</option>)}
                    </select>
                    <button className="dangerButton" onClick={() => void deleteOrMergeCategory()}>{categoryReassignId ? "Merge and delete" : "Delete unused"}</button>
                    <button className="ghostButton" onClick={() => { setEditingCategoryId(null); setEditingCategoryLabel(""); setCategoryReassignId(""); }}>Cancel</button>
                  </div>
                  <small>Deleting a category in use requires a replacement. Transactions, splits, monthly spreads, and rules will move to it.</small>
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
                    setCategoryReassignId("");
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
          <PanelTitle icon={transactionView === "trash" ? Trash2 : ReceiptText} title={transactionView === "trash" ? "Transaction Trash" : activeView === "account" ? "Account Transactions" : "All Transactions"} subtitle={transactionView === "trash" ? "Restore deleted transactions or permanently remove them." : activeView === "account" ? "Transactions for the selected account." : "A searchable repository for every imported transaction."} />
          <div className="trashViewToggle" role="group" aria-label="Transaction view">
            <button className={transactionView === "live" ? "active" : ""} onClick={() => setTransactionView("live")}><ReceiptText size={14} /> Transactions</button>
            <button className={transactionView === "trash" ? "active" : ""} onClick={() => setTransactionView("trash")}><Trash2 size={14} /> Trash</button>
          </div>
          {transactionFilterChips.length > 0 ? (
            <div className="transactionFilterChips" aria-label="Active transaction filters">
              {transactionFilterChips.map((chip) => (
                <button type="button" key={chip.key} onClick={chip.onRemove} title={`Remove ${chip.label} filter`}>
                  <span>{chip.label}</span>
                  <X size={12} />
                </button>
              ))}
              <button
                type="button"
                className="clearFilterChips"
                onClick={() => {
                  if (activeView === "account") navigateToView("all-accounts");
                  setSelectedTransactionAccountFilters(accounts.map((account) => account.id));
                  setSelectedTransactionMonthFilters(monthOptions.map((month) => month.value));
                  setSelectedTransactionYearFilters(transactionYears);
                  setSelectedTransactionCategoryFilters(transactionCategoryOptions.map((option) => option.value));
                  setTransactionDateFrom("");
                  setTransactionDateTo("");
                  setTransactionAmountMin(undefined);
                  setTransactionAmountMax(undefined);
                  setTransactionDirection(undefined);
                  setTransactionSearch("");
                }}
              >
                Clear filters
              </button>
            </div>
          ) : null}
          <div className="ledgerListToolbar">
            <div className="ledgerSummaryGroup">
              <div className="ledgerSummaryText">
                <strong>{filteredTransactions.length} transaction{filteredTransactions.length === 1 ? "" : "s"}</strong>
                <span>Showing {pagedTransactions.length}{filteredTransactions.length > pagedTransactions.length ? ` of ${filteredTransactions.length}` : ""}</span>
              </div>
              <button
                type="button"
                className="secondaryButton compactButton"
                disabled={repositoryTransactionIds.length === 0}
                onClick={() => {
                  setSelectedTransactionIds((current) => {
                    const repositoryIds = new Set(repositoryTransactionIds);
                    if (allRepositoryTransactionsSelected) {
                      return current.filter((id) => !repositoryIds.has(id));
                    }
                    return Array.from(new Set([...current, ...repositoryTransactionIds]));
                  });
                }}
              >
                {allRepositoryTransactionsSelected ? "Clear all" : `Select all ${repositoryTransactionIds.length}`}
              </button>
            </div>
            {pagedTransactions.length < filteredTransactions.length ? (
              <>
                <button type="button" className="secondaryButton compactButton" onClick={() => setTransactionPage((current) => Math.min(transactionPageCount, current + 1))}>
                  Show next {Math.min(TRANSACTION_PAGE_SIZE, filteredTransactions.length - pagedTransactions.length)}
                </button>
                <button type="button" className="ghostButton compactButton" onClick={() => setTransactionPage(transactionPageCount)}>
                  Show all
                </button>
              </>
            ) : null}
          </div>
          {selectedRepositoryTransactionIds.length > 0 ? (
            <div className="bulkSelectionBar">
              <div className="bulkSelectionContext">
                <div>
                  <strong>{selectedRepositoryTransactionIds.length} selected</strong>
                  <span>{pagedTransactions.length} shown{filteredTransactions.length > pagedTransactions.length ? ` of ${filteredTransactions.length}` : ""}</span>
                </div>
                {transactionView === "live" ? <button className="secondaryButton compactButton" onClick={() => setBulkEditorOpen((current) => !current)}>{bulkEditorOpen ? "Close bulk edit" : "Bulk edit"}</button> : null}
              </div>
              {transactionView === "live" ? (
                <button className="dangerTextButton" onClick={() => requestBulkTransactionDelete(selectedRepositoryTransactionIds)}>Delete selected</button>
              ) : (
                <>
                  <button className="secondaryButton compactButton" onClick={() => void restoreSelectedTransactions(selectedRepositoryTransactionIds)}>Restore selected</button>
                  <button className="dangerTextButton" onClick={() => requestDelete({ kind: "transaction_bulk_permanent", ids: selectedRepositoryTransactionIds, label: `${selectedRepositoryTransactionIds.length} deleted transactions` })}>Delete forever</button>
                </>
              )}
              <button className="ghostButton compactButton" onClick={() => { setSelectedTransactionIds((current) => current.filter((id) => !repositoryTransactionIds.includes(id))); setBulkEditorOpen(false); }}>Clear</button>
            </div>
          ) : null}
          {transactionView === "live" && bulkEditorOpen && selectedRepositoryTransactionIds.length > 0 ? (
            <div
              className="bulkEditPanel"
              onKeyDown={(event) => {
                if (event.key === "Enter" && bulkEditValue.trim() && !(event.target instanceof HTMLButtonElement)) {
                  event.preventDefault();
                  void bulkUpdateSelectedTransactions();
                }
              }}
            >
              <div>
                <strong>Edit {selectedRepositoryTransactionIds.length} transactions</strong>
                <span>Choose a field, then provide its new value.</span>
              </div>
              <label>Field<select value={bulkEditField} onChange={(event) => { setBulkEditField(event.target.value as BulkTransactionField); setBulkEditValue(""); }}>{bulkTransactionFields.map((field) => <option key={field.value} value={field.value}>{field.label}</option>)}</select></label>
              <label>New value
                {bulkEditField === "account" ? (
                  <select value={bulkEditValue} onChange={(event) => setBulkEditValue(event.target.value)}><option value="">Choose account</option>{accounts.map((account) => <option key={account.id} value={account.id}>{accountOptionLabel(account)}</option>)}</select>
                ) : bulkEditField === "type" ? (
                  <select value={bulkEditValue} onChange={(event) => setBulkEditValue(event.target.value)}><option value="">Choose type</option>{transactionTypes.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}</select>
                ) : bulkEditField === "category" ? (
                  <select value={bulkEditValue} onChange={(event) => setBulkEditValue(event.target.value)}><option value="">Choose category</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.label}</option>)}</select>
                ) : (
                  <input value={bulkEditValue} onChange={(event) => setBulkEditValue(event.target.value)} placeholder={`New ${bulkTransactionFields.find((field) => field.value === bulkEditField)?.label.toLowerCase()}`} />
                )}
              </label>
              <div className="bulkEditActions">
                <button className="primaryButton" onClick={() => void bulkUpdateSelectedTransactions()} disabled={!bulkEditValue.trim()}>Apply change</button>
                <button className="ghostButton" onClick={() => { setBulkEditorOpen(false); setBulkEditValue(""); }}>Cancel</button>
              </div>
              {bulkEditField === "institution" ? <small>Institution changes apply to the account records associated with the selected transactions.</small> : null}
            </div>
          ) : null}
          {deleteTarget?.kind === "transaction_bulk" || deleteTarget?.kind === "transaction_bulk_permanent" ? (
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
              <span>Selected</span>
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
              const isEditing = transactionView === "live" && editingTransactionId === transaction.id;
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
                  onClick={() => { if (transactionView === "live") handleTransactionRowClick(transaction.id); }}
                  onDoubleClick={() => { if (transactionView === "live") openTransactionEditor(transaction.id); }}
                  onKeyDown={(event) => {
                    if (!isEditing || event.key !== "Enter" || event.shiftKey) return;
                    const target = event.target as HTMLElement;
                    if (target.closest(".categoryPopup") || target instanceof HTMLButtonElement) return;
                    event.preventDefault();
                    const noteValue = target instanceof HTMLTextAreaElement ? target.value : undefined;
                    void confirmTransactionEdit(transaction, noteValue);
                  }}
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
                  <div className="transactionDetailsCell">
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
                    {transaction.split_count > 0 || transaction.monthly_allocation_count > 0 ? (
                      <div className="transactionLabels">
                        {transaction.split_count > 0 ? <span>Split into {transaction.split_count} categories</span> : null}
                        {transaction.monthly_allocation_count > 0 ? <span>Spread across {transaction.monthly_allocation_count} months</span> : null}
                      </div>
                    ) : null}
                  </div>
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
                          onClick={() => setCategoryEditor({ transactionId: transaction.id, query: "" })}
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
                                } else if (event.key === "Enter" && categorySuggestions[0]) {
                                  event.preventDefault();
                                  void updateTransaction(transaction.id, { category_id: categorySuggestions[0].id }, false);
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
                  {transactionView === "trash" ? (
                    <div className="trashRowActions">
                      <button className="secondaryButton compactButton" onClick={(event) => { event.stopPropagation(); void restoreDeletedTransaction(transaction); }}>Restore</button>
                      <button className="dangerTextButton" onClick={(event) => { event.stopPropagation(); requestDelete({ kind: "transaction_permanent", id: transaction.id, label: transaction.raw_description }); }}>Delete forever</button>
                    </div>
                  ) : (
                    <button
                      className="dangerTextButton"
                      onClick={(event) => {
                        event.stopPropagation();
                        requestDelete({ kind: "transaction", id: transaction.id, label: transaction.raw_description });
                      }}
                    >
                      Delete
                    </button>
                  )}
                </div>
                {isEditing ? (
                  <div className="rowEditActions">
                    <button type="button" className="secondaryButton compactButton" onClick={() => void openSplitEditor(transaction)} disabled={transaction.monthly_allocation_count > 0}>
                      Split categories
                    </button>
                    {transaction.transaction_type === "expense" ? (
                      transaction.monthly_allocation_count > 0 ? (
                        <button type="button" className="secondaryButton compactButton" onClick={() => void removeMonthlyAllocation(transaction)} disabled={busyAction === `allocation-${transaction.id}`}>
                          Remove {transaction.monthly_allocation_count}-month spread
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="secondaryButton compactButton"
                          onClick={() => {
                            setSplitEditor(null);
                            const startMonth = transaction.transaction_date.slice(0, 7);
                            setMonthlyAllocationEditor({ transactionId: transaction.id, category_id: transaction.category_id ?? categories[0]?.id ?? "", start_month: startMonth, end_month: addMonthsToMonth(startMonth, 5) });
                          }}
                        >
                          Spread across months
                        </button>
                      )
                    ) : null}
                    <button type="button" className="secondaryButton compactButton" onClick={exitTransactionEdit}>
                      Cancel
                    </button>
                    <button
                      type="button"
                      className="primaryButton compactButton"
                      onClick={() => void confirmTransactionEdit(transaction)}
                    >
                      Done
                    </button>
                  </div>
                ) : null}
                {splitEditor?.transactionId === transaction.id ? (
                  <section className="transactionAllocationEditor" onClick={(event) => event.stopPropagation()}>
                    <div>
                      <strong>Split this charge by category</strong>
                      <span>Amounts must add up exactly to {formatMoney(transaction.amount_cents)}.</span>
                    </div>
                    {splitEditor.rows.map((split, index) => (
                      <div className="splitDraftRow" key={index}>
                        <select value={split.category_id} onChange={(event) => setSplitEditor((current) => current ? { ...current, rows: current.rows.map((row, rowIndex) => rowIndex === index ? { ...row, category_id: event.target.value ? Number(event.target.value) : "" } : row) } : current)}>
                          <option value="">Choose category</option>
                          {categories.map((category) => <option key={category.id} value={category.id}>{category.label}</option>)}
                        </select>
                        <input inputMode="decimal" value={split.amount} onChange={(event) => setSplitEditor((current) => current ? { ...current, rows: current.rows.map((row, rowIndex) => rowIndex === index ? { ...row, amount: event.target.value } : row) } : current)} aria-label={`Split ${index + 1} amount`} />
                        <input value={split.note} onChange={(event) => setSplitEditor((current) => current ? { ...current, rows: current.rows.map((row, rowIndex) => rowIndex === index ? { ...row, note: event.target.value } : row) } : current)} placeholder="Optional note" aria-label={`Split ${index + 1} note`} />
                        <button type="button" className="dangerTextButton" onClick={() => setSplitEditor((current) => current ? { ...current, rows: current.rows.filter((_, rowIndex) => rowIndex !== index) } : current)} disabled={splitEditor.rows.length <= 2}>Remove</button>
                      </div>
                    ))}
                    <div className="buttonRow">
                      <button type="button" className="secondaryButton compactButton" onClick={() => setSplitEditor((current) => current ? { ...current, rows: [...current.rows, { category_id: "", amount: "0.00", note: "" }] } : current)}>Add category</button>
                      <button type="button" className="primaryButton compactButton" onClick={() => void saveSplits(transaction)} disabled={busyAction === `split-${transaction.id}`}>Save split</button>
                      <button type="button" className="ghostButton compactButton" onClick={() => setSplitEditor(null)}>Cancel</button>
                    </div>
                  </section>
                ) : null}
                {monthlyAllocationEditor?.transactionId === transaction.id ? (
                  <section className="transactionAllocationEditor" onClick={(event) => event.stopPropagation()}>
                    <div>
                      <strong>Spread this charge across months</strong>
                      <span>The bank charge stays on {formatShortDate(transaction.transaction_date)}; only Spending is divided evenly by month.</span>
                    </div>
                    <div className="monthlyAllocationFields">
                      <label>Category<select value={monthlyAllocationEditor.category_id} onChange={(event) => setMonthlyAllocationEditor((current) => current ? { ...current, category_id: event.target.value ? Number(event.target.value) : "" } : current)}><option value="">Choose category</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.label}</option>)}</select></label>
                      <label>First month<input type="month" value={monthlyAllocationEditor.start_month} onChange={(event) => setMonthlyAllocationEditor((current) => current ? { ...current, start_month: event.target.value } : current)} /></label>
                      <label>Last month<input type="month" value={monthlyAllocationEditor.end_month} onChange={(event) => setMonthlyAllocationEditor((current) => current ? { ...current, end_month: event.target.value } : current)} /></label>
                      <span className="allocationPreview">{inclusiveMonthCount(monthlyAllocationEditor.start_month, monthlyAllocationEditor.end_month) > 0 ? `${inclusiveMonthCount(monthlyAllocationEditor.start_month, monthlyAllocationEditor.end_month)} months · about ${formatMoney(transaction.amount_cents / inclusiveMonthCount(monthlyAllocationEditor.start_month, monthlyAllocationEditor.end_month))} per month` : "Choose a valid month range"}</span>
                    </div>
                    <div className="buttonRow">
                      <button type="button" className="primaryButton compactButton" onClick={() => void saveMonthlyAllocation(transaction)} disabled={!monthlyAllocationEditor.category_id || inclusiveMonthCount(monthlyAllocationEditor.start_month, monthlyAllocationEditor.end_month) < 2 || inclusiveMonthCount(monthlyAllocationEditor.start_month, monthlyAllocationEditor.end_month) > 120 || busyAction === `allocation-${transaction.id}`}>Save monthly spread</button>
                      <button type="button" className="ghostButton compactButton" onClick={() => setMonthlyAllocationEditor(null)}>Cancel</button>
                    </div>
                  </section>
                ) : null}
                {(deleteTarget?.kind === "transaction" || deleteTarget?.kind === "transaction_permanent") && deleteTarget.id === transaction.id ? (
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
              <button className="dangerTextButton" onClick={() => void restoreAppExport()} disabled={!appImportFile || busyAction !== null}>
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
                    <button className="secondaryButton" onClick={() => void previewSelectedImport()} disabled={!selectedAccountId || !selectedFile || busyAction !== null}>
                      Preview
                    </button>
                    <button className="primaryButton" onClick={() => void commitSelectedImport()} disabled={!selectedAccountId || !selectedFile || !importPreview || busyAction !== null}>
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
        {peekDrawer ? (
          <div className="peekBackdrop" onClick={() => setPeekDrawer(null)}>
            <aside className="peekDrawer" aria-label="Matching transactions" onClick={(event) => event.stopPropagation()}>
              <header>
                <div>
                  <span className="eyebrow">Transaction peek</span>
                  <h2>{peekDrawer.title}</h2>
                  <p>{peekDrawer.rows.length === 20 ? "Top 20 matching transactions" : `${peekDrawer.rows.length} matching transaction${peekDrawer.rows.length === 1 ? "" : "s"}`}</p>
                </div>
                <button className="ghostButton compactButton" onClick={() => setPeekDrawer(null)} aria-label="Close transaction preview"><X size={16} /></button>
              </header>
              <div className="peekRows">
                {peekDrawer.rows.map((row) => (
                  <div className="peekRow" key={row.id}>
                    <span>{formatShortDate(row.transaction_date)}</span>
                    <div><strong>{row.raw_description}</strong><small>{row.account_name}</small></div>
                    <strong className={row.amount_cents < 0 ? "amount negative" : "amount positive"}>{formatMoney(row.amount_cents)}</strong>
                  </div>
                ))}
                {peekDrawer.rows.length === 0 ? <p className="emptyText">No transactions occurred in this range.</p> : null}
              </div>
              <footer>
                <button className="primaryButton" onClick={() => {
                  setTransactionDateFrom(peekDrawer.from);
                  setTransactionDateTo(peekDrawer.to);
                  setTransactionView("live");
                  setPeekDrawer(null);
                  navigateToView("all-accounts");
                }}>Open full view →</button>
              </footer>
            </aside>
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
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const selectedCount = selectedValues.length;
  const summary = selectedCount === options.length ? "All" : selectedCount === 0 ? "None" : `${selectedCount} selected`;

  useEffect(() => {
    function closeOnOutsideClick(event: PointerEvent) {
      if (detailsRef.current?.open && !detailsRef.current.contains(event.target as Node)) {
        detailsRef.current.open = false;
      }
    }
    document.addEventListener("pointerdown", closeOnOutsideClick);
    return () => document.removeEventListener("pointerdown", closeOnOutsideClick);
  }, []);

  return (
    <details className="multiFilter" ref={detailsRef}>
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
  const isBulk = target.kind.includes("bulk");
  const isPermanent = target.kind.includes("permanent");
  const isAccount = target.kind === "account" || target.kind === "account_bulk";
  return (
    <section className="deleteConfirmPanel inlineDeleteConfirm">
      <div>
        <strong>{isPermanent ? `Permanently delete ${isBulk ? "these transactions" : "this transaction"}?` : isBulk ? "Delete selected items?" : target.kind === "account" ? "Delete this account?" : "Move this row to Trash?"}</strong>
        <span>{target.label}</span>
        <small>{isPermanent ? "This cannot be undone. The transaction and its related split or allocation data will be removed." : isAccount ? "Deleting an account keeps its transactions and returns them to Review for account selection. Holdings, presets, and import history are removed; audit history remains." : "The transaction can be restored from Trash or immediately with Undo."}</small>
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
  onViewTransactions,
  onPeekTransactions,
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
  onViewTransactions: (fromDate: string, toDate: string) => void;
  onPeekTransactions: (fromDate: string, toDate: string) => void;
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
    return <NetWorthReport accounts={netWorthAccounts} allocationRows={allocationRows} holdingRows={holdingRows} selectedHoldingIds={selectedHoldingIds} selectedVisibleHoldingIds={selectedVisibleHoldingIds} visibleHoldingIds={visibleHoldingIds} deleteTarget={deleteTarget} deleteConfirmText={deleteConfirmText} onToggleHoldingSelection={onToggleHoldingSelection} onRequestBulkHoldingDelete={onRequestBulkHoldingDelete} onClearHoldingSelection={onClearHoldingSelection} onUpdateHoldingDescription={onUpdateHoldingDescription} onViewTransactions={onViewTransactions} onPeekTransactions={onPeekTransactions} onRequestDelete={onRequestDelete} onConfirmDelete={onConfirmDelete} onDeleteConfirmTextChange={onDeleteConfirmTextChange} onCancelDelete={onCancelDelete} />;
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

function NetWorthHistoryChart({ onViewTransactions, onPeekTransactions }: { onViewTransactions: (fromDate: string, toDate: string) => void; onPeekTransactions: (fromDate: string, toDate: string) => void }) {
  const [period, setPeriod] = useState<NetWorthPeriod>(() => readAppRoute(window.location).filters.netWorthPeriod ?? "6M");
  const [data, setData] = useState<NetWorthSeriesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [dragStart, setDragStart] = useState<number | null>(null);
  const [dragEnd, setDragEnd] = useState<number | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [selectionStats, setSelectionStats] = useState<NetWorthStats | null>(null);

  useEffect(() => {
    let cancelled = false;
    const range = netWorthPeriodRange(period);
    setLoading(true);
    setSelectionStats(null);
    setDragStart(null);
    setDragEnd(null);
    setIsDragging(false);
    api<NetWorthSeriesResponse>(`/api/snapshots/networth?${range.params.toString()}`)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch(() => {
        if (!cancelled) setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [period]);

  useEffect(() => {
    function clearSelection(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setSelectionStats(null);
      setDragStart(null);
      setDragEnd(null);
      setIsDragging(false);
    }
    window.addEventListener("keydown", clearSelection);
    return () => window.removeEventListener("keydown", clearSelection);
  }, []);

  function choosePeriod(nextPeriod: NetWorthPeriod) {
    setPeriod(nextPeriod);
    const route = readAppRoute(window.location);
    route.filters.netWorthPeriod = nextPeriod;
    window.history.replaceState({}, "", routeUrl(route.view, route.accountId, route.filters));
  }

  const rows = data?.series ?? [];
  const width = 800;
  const height = 280;
  const left = 58;
  const right = 18;
  const top = 24;
  const bottom = 36;
  const chartWidth = width - left - right;
  const chartHeight = height - top - bottom;
  const values = rows.map((row) => row.total_cents);
  const rawMinimum = values.length > 0 ? Math.min(...values) : 0;
  const rawMaximum = values.length > 0 ? Math.max(...values) : 0;
  const chartPadding = Math.max((rawMaximum - rawMinimum) * 0.08, Math.abs(rawMaximum) * 0.01, 100);
  const minimum = rawMinimum - chartPadding;
  const maximum = rawMaximum + chartPadding;
  const span = Math.max(maximum - minimum, 1);
  const xFor = (index: number) => left + (rows.length <= 1 ? chartWidth / 2 : (index / (rows.length - 1)) * chartWidth);
  const yFor = (value: number) => top + ((maximum - value) / span) * chartHeight;
  const linePath = rows.map((row, index) => `${index === 0 ? "M" : "L"} ${xFor(index)} ${yFor(row.total_cents)}`).join(" ");
  const areaPath = rows.length > 0 ? `${linePath} L ${xFor(rows.length - 1)} ${top + chartHeight} L ${xFor(0)} ${top + chartHeight} Z` : "";
  const latest = rows.at(-1)?.total_cents ?? 0;
  const first = rows[0]?.total_cents ?? 0;
  const periodChange = latest - first;
  const activeIndex = hoverIndex ?? dragEnd;
  const selectedStart = dragStart === null || dragEnd === null ? null : Math.min(dragStart, dragEnd);
  const selectedEnd = dragStart === null || dragEnd === null ? null : Math.max(dragStart, dragEnd);

  function pointerIndex(event: ReactPointerEvent<SVGSVGElement>) {
    if (rows.length <= 1) return 0;
    const bounds = event.currentTarget.getBoundingClientRect();
    const viewX = ((event.clientX - bounds.left) / bounds.width) * width;
    const ratio = Math.max(0, Math.min(1, (viewX - left) / chartWidth));
    return Math.round(ratio * (rows.length - 1));
  }

  async function finishSelection(startIndex: number, endIndex: number) {
    const startDate = rows[Math.min(startIndex, endIndex)]?.date;
    const endDate = rows[Math.max(startIndex, endIndex)]?.date;
    if (!startDate || !endDate) return;
    try {
      const stats = await api<NetWorthStats>(`/api/snapshots/networth/stats?from=${startDate}&to=${endDate}`);
      setSelectionStats(stats);
    } catch {
      setSelectionStats(null);
    }
  }

  return (
    <section className="netWorthHistoryPanel">
      <div className="netWorthHistoryHeader">
        <div>
          <span>Net worth history</span>
          <strong>{formatMoney(latest)}</strong>
          <small className={periodChange < 0 ? "amount negative" : "amount positive"}>{periodChange >= 0 ? "+" : ""}{formatMoney(periodChange)} during this period</small>
        </div>
        <div className="periodSelector" aria-label="Net worth period">
          {(["1M", "6M", "1Y", "Max"] as NetWorthPeriod[]).map((option) => (
            <button type="button" className={period === option ? "active" : ""} key={option} onClick={() => choosePeriod(option)}>{option}</button>
          ))}
        </div>
      </div>
      {loading ? <p className="emptyText">Loading net worth history…</p> : rows.length === 0 ? <p className="emptyText">Import account balances or brokerage positions to build net worth history.</p> : (
        <div className="netWorthChartWrap">
          <svg
            className="netWorthChart"
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label="Interactive net worth history. Drag across the chart to inspect a date range."
            onPointerDown={(event) => {
              const index = pointerIndex(event);
              event.currentTarget.setPointerCapture(event.pointerId);
              setDragStart(index);
              setDragEnd(index);
              setIsDragging(true);
              setSelectionStats(null);
            }}
            onPointerMove={(event) => {
              const index = pointerIndex(event);
              setHoverIndex(index);
              if (isDragging) setDragEnd(index);
            }}
            onPointerUp={(event) => {
              if (!isDragging || dragStart === null) return;
              const index = pointerIndex(event);
              setDragEnd(index);
              void finishSelection(dragStart, index);
              setIsDragging(false);
            }}
            onPointerLeave={() => setHoverIndex(null)}
          >
            <defs>
              <linearGradient id="netWorthFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#3b6ae8" stopOpacity="0.3" />
                <stop offset="100%" stopColor="#3b6ae8" stopOpacity="0.03" />
              </linearGradient>
            </defs>
            <line x1={left} x2={width - right} y1={top + chartHeight} y2={top + chartHeight} className="chartAxis" />
            <text x={left} y={height - 10} className="chartLabel">{formatShortDate(rows[0].date)}</text>
            <text x={width - right} y={height - 10} textAnchor="end" className="chartLabel">{formatShortDate(rows.at(-1)?.date)}</text>
            <text x={left - 8} y={top + 4} textAnchor="end" className="chartLabel">{formatCompactMoney(maximum)}</text>
            <text x={left - 8} y={top + chartHeight} textAnchor="end" className="chartLabel">{formatCompactMoney(minimum)}</text>
            {selectedStart !== null && selectedEnd !== null ? <rect x={xFor(selectedStart)} y={top} width={Math.max(2, xFor(selectedEnd) - xFor(selectedStart))} height={chartHeight} className="chartSelection" /> : null}
            <path d={areaPath} fill="url(#netWorthFill)" />
            <path d={linePath} className="netWorthLine" />
            {activeIndex !== null && rows[activeIndex] ? (
              <g>
                <line x1={xFor(activeIndex)} x2={xFor(activeIndex)} y1={top} y2={top + chartHeight} className="chartHoverLine" />
                <circle cx={xFor(activeIndex)} cy={yFor(rows[activeIndex].total_cents)} r="5" className="chartHoverPoint" />
                <g transform={`translate(${Math.min(width - 175, Math.max(left, xFor(activeIndex) - 75))}, ${Math.max(8, yFor(rows[activeIndex].total_cents) - 54)})`}>
                  <rect width="150" height="42" rx="6" className="chartTooltip" />
                  <text x="10" y="16" className="chartTooltipDate">{formatShortDate(rows[activeIndex].date)}</text>
                  <text x="10" y="33" className="chartTooltipValue">{formatMoney(rows[activeIndex].total_cents)}</text>
                </g>
              </g>
            ) : null}
          </svg>
          <small>Drag across the chart to compare a range. Balance gaps are forward-filled from the latest snapshot.</small>
        </div>
      )}
      {selectionStats ? (
        <div className="netWorthSelectionStats">
          <div>
            <strong>{formatShortDate(selectionStats.from)} – {formatShortDate(selectionStats.to)}</strong>
            <span className={selectionStats.change_cents < 0 ? "amount negative" : "amount positive"}>{selectionStats.change_cents >= 0 ? "+" : ""}{formatMoney(selectionStats.change_cents)}{selectionStats.change_pct === null ? "" : ` (${selectionStats.change_pct}%)`}</span>
          </div>
          <span>High {formatMoney(selectionStats.max_cents)} ({formatShortDate(selectionStats.max_date)})</span>
          <span>Low {formatMoney(selectionStats.min_cents)} ({formatShortDate(selectionStats.min_date)})</span>
          <button type="button" className="secondaryButton compactButton" onClick={() => onPeekTransactions(selectionStats.from, selectionStats.to)}>Peek transactions</button>
          <button type="button" className="secondaryButton compactButton" onClick={() => onViewTransactions(selectionStats.from, selectionStats.to)}>View transactions →</button>
          <button type="button" className="ghostButton compactButton" onClick={() => { setSelectionStats(null); setDragStart(null); setDragEnd(null); setIsDragging(false); }}>Clear</button>
        </div>
      ) : null}
    </section>
  );
}

function netWorthPeriodRange(period: NetWorthPeriod) {
  const today = new Date();
  const to = localIsoDate(today);
  const params = new URLSearchParams({ to, bucket: period === "1Y" ? "week" : period === "Max" ? "month" : "day" });
  if (period !== "Max") {
    const from = new Date(today.getFullYear(), today.getMonth() - (period === "1M" ? 1 : period === "6M" ? 6 : 12), today.getDate());
    params.set("from", localIsoDate(from));
  }
  return { params };
}

function localIsoDate(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function formatCompactMoney(cents: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 }).format(cents / 100);
}

function formatOperationValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatOperationDiffValue(operation: OperationSummary, field: string, value: unknown, side: "before" | "after") {
  if (field === "deleted_at") {
    if (value) {
      const parsed = new Date(String(value));
      return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
    }
    if (operation.kind === "delete") return side === "before" ? "Active" : `Moved to Trash ${new Date(operation.created_at).toLocaleString()}`;
    if (operation.kind === "restore") return side === "after" ? "Active" : `In Trash before ${new Date(operation.created_at).toLocaleString()}`;
  }
  return formatOperationValue(value);
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
  onViewTransactions,
  onPeekTransactions,
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
  onViewTransactions: (fromDate: string, toDate: string) => void;
  onPeekTransactions: (fromDate: string, toDate: string) => void;
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
      <NetWorthHistoryChart onViewTransactions={onViewTransactions} onPeekTransactions={onPeekTransactions} />
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
