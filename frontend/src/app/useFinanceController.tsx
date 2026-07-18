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
  Trash2,
  X,
} from "lucide-react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { bumpTransactionsVersion, getTransactionsVersion, parseApiJson, readableApiError, subscribeTransactionsVersion } from "../api/client";
import { useApiClient, useApiFetch } from "../api/hooks";
import { readAppRoute, routeUrl, type RouteView } from "./router";
import { BulkActionBar, CashFlowGraphic, DrillDownLink, MultiSelectFilter, PanelTitle, UndoToast } from "../components/AppPrimitives";
import { DateRangePicker } from "../components/DateRangePicker";
import { DeleteConfirmInline, type DeleteTarget } from "../components/DeleteConfirmInline";
import { FilterSummaryBar } from "../components/FilterSummaryBar";
import { PrimaryNav } from "../components/PrimaryNav";
import { AccountPage } from "../features/accounts/AccountPage";
import type { ReconciliationStatus } from "../features/accounts/ReconciliationBadge";
import { ImportReview, type InboxBatch, type ImportInboxScan, type ImportInboxState, type SignDecision } from "../features/imports/ImportReview";
import { SignConventionPrompt, type ImportSignConvention } from "../features/imports/SignConventionPrompt";
import { HoldingsPanel, type HoldingRow } from "../features/networth/HoldingsPanel";
import { ManualSnapshotEditor } from "../features/networth/ManualSnapshotEditor";
import { UnanchoredBanner } from "../features/networth/UnanchoredBanner";
import { RefundLinkPicker } from "../features/refunds/RefundLinkPicker";
import { RefundCategorizationNudge, RefundSuggestions, type RefundCandidate, type RefundLink, type RefundSelection, type RefundSuggestionGroup } from "../features/refunds/RefundSuggestions";
import type { RuleDraft, SavedRulePreview } from "../features/rules/PostCategorizationRulePrompt";
import { SavedRulesPanel } from "../features/rules/SavedRulesPanel";
import { LedgerDuplicateScan, type DuplicatePair } from "../features/review/LedgerDuplicateScan";
import { filterReviewQueue, isUncategorizedRefund, type ReviewQueueFilter } from "../features/review/reviewQueue";
import type { DuplicateTransaction } from "../features/review/TransactionCompareCard";
import { TransferReview, type TransferCandidate } from "../features/review/TransferReview";
import type { PaymentVerificationStatus, PaymentWarning } from "../features/transfers/PaymentVerification";
import { ManualTransactionForm } from "../features/transactions/ManualTransactionForm";
import { OverviewTabs } from "../features/overview/OverviewTabs";
import { ReportSurface } from "../features/overview/ReportSurface";
import { AccountNav } from "../features/sidebar/AccountNav";
import { DataSettings } from "../features/settings/DataSettings";
import { ImportMetadataPanel } from "../features/settings/ImportMetadataPanel";
import { SecuritySettings } from "../features/settings/SecuritySettings";
import { SettingsNavigation, type SettingsTab } from "../features/settings/SettingsNavigation";
import { encodeTxnFilter, freshAccountNavigationFilter, isMonthInReportPeriod, isTransactionInReportPeriod, type NetWorthPeriod, type ReportPeriod, type ReportTab, type TxnFilter } from "../lib/filters";
import { transactionTypeRequiresCategory, transactionTypeUsesCategory } from "../lib/transactionTypes";
import { useSelection } from "../lib/useSelection";
type BootstrapCategory = { id: number; key: string; label: string; parent_id: number | null };
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
  net_worth_inclusion: "auto" | "always" | "never";
  is_anchored: boolean;
  sidebar_balance_cents: number | null;
  sidebar_balance_kind: "running_balance" | "investment_snapshot" | "anchored_balance" | "recent_activity" | "unanchored" | "excluded";
  sidebar_balance_as_of: string | null;
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
  labels: string[];
  monthly_allocation_count: number;
  split_count: number;
  reporting_category_ids: Array<number | null>;
  reporting_dates: string[];
  refund_total_cents: number;
  refund_link_count: number;
  refund_expense_id: number | null;
};

type RefundPickerState = { expenseId: number; candidates: DuplicateTransaction[]; links: RefundLink[]; search: string; loading: boolean };

type SplitDraft = { category_id: number | ""; amount: string; note: string };
type MonthlyAllocationDraft = { transactionId: number; category_id: number | ""; start_month: string; end_month: string };

type ImportPreview = {
  preset_type: string;
  sign_convention?: "preset" | "reverse";
  sign_decision?: SignDecision | null;
  rows: Array<Record<string, any>>;
  warnings: string[];
};

type ImportAnalysis = {
  preset_type: string | null;
  suggested_account_id: number | null;
  replacement_candidate_id: number | null;
  match_confidence: number;
  reason: string;
  proposed_account: {
    institution_name: string | null;
    display_name: string;
    account_type: string;
    currency: string;
    last_four: string | null;
  } | null;
  warnings: string[];
  headers?: string[];
  sample_rows?: Array<Record<string, string>>;
};
type GenericCsvMapping = { date: string; description: string; amount: string };
type HistorySignConvention = "charges_positive" | "canonical";

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
  | { needs_review?: false; inserted: number; skipped: number; accounts_created: number; categories_created: number; warnings: string[]; operation_id?: string };

type HistoryCleanupPreview = {
  candidate_transactions: number;
  charges_to_normalize: number;
  refunds_to_normalize: number;
  income_sign_fixes: number;
  gross_cents: number;
  confirmation_text: string;
  accounts: Array<{
    account_id: number;
    account: string;
    last_four: string | null;
    current_account_type: string;
    next_account_type: string;
    transactions: number;
    gross_cents: number;
    history_rows: number;
    history_from: string | null;
    history_through: string | null;
    direct_rows: number;
    direct_from: string | null;
    direct_through: string | null;
    direct_rows_after_history: number;
    direct_rows_on_or_before_history: number;
    possible_direct_duplicate_rows: number;
  }>;
  possible_duplicate_account_pairs: Array<{
    left_account_id: number;
    left_account: string;
    left_last_four: string | null;
    right_account_id: number;
    right_account: string;
    right_last_four: string | null;
    matching_transactions: number;
    overlap_percent: number;
  }>;
  possible_direct_import_duplicates: Array<{
    account_id: number;
    account: string;
    last_four: string | null;
    possible_duplicate_rows: number;
  }>;
  source_boundary_warnings: Array<{
    account_id: number;
    account: string;
    last_four: string | null;
    direct_rows_on_or_before_history: number;
  }>;
};

type ToastState = {
  tone: "success" | "error" | "info";
  message: string;
  operationId?: string;
  unconflictedOnly?: boolean;
  action?: { label: string; ruleId: number; transactionId: number };
};

type SavedRuleAction = {
  id: number;
  matchText: string;
  transactionId: number;
};

type RuleSummary = {
  id: number;
  category_id: number | null;
  priority: number;
  field_name: string;
  match_text: string;
  suggested_transaction_type: string;
};

type CategoryTotal = { category_id: number | null; category: string; amount_cents: number; count: number };
type AggregateRow = { date: string; total_cents: number; count: number };
type CategoryAggregateRow = { category_id: number | null; category: string; total_cents: number; count: number };
type MonthlyCashFlow = { month: string; income_cents: number; expense_cents: number; net_cents: number };
type NetWorthAccount = { account_id: number; account: string; account_type: string; latest_date: string; market_value_cents: number };
type NetWorthPoint = { date: string; total_cents: number; by_account: Record<string, number> };
type NetWorthSeriesResponse = { from: string; to: string; bucket: "day" | "week" | "month"; series: NetWorthPoint[]; unanchored_accounts: Array<{ id: number; name: string }> };
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
  changes: Array<{ id: number; entity_type: string; entity_id: string; before: Record<string, unknown> | null; after: Record<string, unknown> | null }>;
};

type PeekDrawerState = {
  title: string;
  eyebrow: string;
  filter: TxnFilter;
  rows: TransactionRow[];
};
type NetWorthContributor = {
  account_id: number;
  account: string;
  account_type: string;
  last_four: string | null;
  start_cents: number;
  end_cents: number;
  change_cents: number;
  change_pct: number | null;
};
type NetWorthPeekState = {
  from: string;
  to: string;
  start_cents: number;
  end_cents: number;
  change_cents: number;
  accounts: NetWorthContributor[];
};
type AllocationRow = { asset_class: string; market_value_cents: number };
type TransactionSortKey = "date" | "amount";
type SortDirection = "asc" | "desc";
type BulkTransactionField = "institution" | "account" | "description" | "details" | "type" | "category" | "date" | "labels";
type FilterOption = { value: string; label: string };

type AppView = RouteView;
type AccountTaxonomyOverrides = Record<string, string>;
type TaxonomySection = { label: string; rows: AccountSummary[]; emptyText: string };
type TaxonomyGroup = { label: string; rows: AccountSummary[]; totalCents: number };
type CollapsedTaxonomyGroups = Record<string, boolean>;
type DashboardWidgetKey = "taxonomy" | "spending" | "cashflow";
type DashboardWidgetConfig = Record<DashboardWidgetKey, boolean>;

const primaryNavItems: Array<{ id: AppView; label: string; icon: typeof LayoutDashboard }> = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "all-accounts", label: "All Accounts", icon: Landmark },
  { id: "review", label: "Review", icon: ListChecks },
  { id: "history", label: "Activity", icon: History },
  { id: "settings", label: "Settings", icon: Settings },
];

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
const transactionTypeLabels: Record<string, string> = {
  expense: "Expenses",
  income: "Income",
  refund: "Refunds",
  transfer: "Transfers",
  credit_card_payment: "Card payments",
  investment_flow: "Investment flows",
  adjustment: "Adjustments",
};
const TRANSACTION_PAGE_SIZE = 100;
const taxonomyStorageKey = "privateFinance.accountTaxonomy.v1";
const collapsedTaxonomyStorageKey = "privateFinance.collapsedTaxonomy.v1";
const sidebarWidthStorageKey = "privateFinance.sidebarWidth.v1";
const minSidebarWidth = 190;
const maxSidebarWidth = 420;
const dashboardWidgetStorageKey = "privateFinance.dashboardWidgets.v1";
const defaultDashboardWidgets: DashboardWidgetConfig = {
  taxonomy: true,
  spending: true,
  cashflow: true,
};
const dashboardWidgetOptions: Array<{ key: DashboardWidgetKey; label: string; description: string }> = [
  { key: "taxonomy", label: "Account map", description: "Balances by account type and institution/custom group." },
  { key: "spending", label: "Top spending", description: "Largest expense categories for the selected period." },
  { key: "cashflow", label: "Cash-flow trend", description: "Recent income, expense, and net movement." },
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
  { value: "date", label: "Transaction date" },
  { value: "labels", label: "Labels" },
];

const formatMoney = (cents: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);

function parseCsvText(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (character === '"') {
      if (quoted && text[index + 1] === '"') { cell += '"'; index += 1; }
      else quoted = !quoted;
    } else if (character === "," && !quoted) {
      row.push(cell);
      cell = "";
    } else if ((character === "\n" || character === "\r") && !quoted) {
      if (character === "\r" && text[index + 1] === "\n") index += 1;
      row.push(cell);
      if (row.some((value) => value.trim())) rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += character;
    }
  }
  if (cell || row.length) {
    row.push(cell);
    if (row.some((value) => value.trim())) rows.push(row);
  }
  if (rows[0]?.[0]) rows[0][0] = rows[0][0].replace(/^\ufeff/, "");
  return rows;
}

function csvCell(value: string) {
  return /[",\r\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
}

const sameFilterValues = (left: Array<string | number>, right: Array<string | number>) =>
  left.length === right.length && new Set(left.map(String)).size === new Set([...left, ...right].map(String)).size;

const selectionSummary = (label: string, selected: string[], options: FilterOption[]) => {
  if (selected.length === 0) return `${label}: none`;
  if (selected.length === 1) return `${label}: ${options.find((option) => option.value === selected[0])?.label ?? selected[0]}`;
  return `${label}: ${selected.length} selected`;
};

const accountOptionLabel = (account: AccountSummary) => {
  const name = account.display_name.trim();
  const lastFour = account.last_four?.trim();
  if (!lastFour || name.endsWith(lastFour) || name.endsWith(`(${lastFour})`)) return name;
  return `${name} (${lastFour})`;
};

const sidebarBalanceLabel = (account: AccountSummary) => {
  if (account.sidebar_balance_kind === "unanchored") return "Excluded from net worth until a statement balance is added";
  if (account.sidebar_balance_kind === "excluded") return "Excluded from net worth";
  const source = account.sidebar_balance_kind === "running_balance"
    ? "Latest imported balance"
    : account.sidebar_balance_kind === "investment_snapshot"
      ? "Latest investment value"
      : account.sidebar_balance_kind === "anchored_balance"
        ? "Balance reconstructed from the latest anchor"
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
    external: "Untracked account",
  })[value] ?? value.replace(/_/g, " ");

const bankAccountTypes = new Set(["checking", "savings", "cash", "other", "loan"]);
const creditCardAccountTypes = new Set(["credit_card"]);
const brokerageAccountTypes = new Set(["brokerage", "retirement"]);
const externalAccountTypes = new Set(["external"]);

function isBrokerageAccountType(accountType: string): boolean {
  return brokerageAccountTypes.has(accountType);
}

function accountGroupLabel(accountType: string): string {
  if (creditCardAccountTypes.has(accountType)) return "Credit Cards";
  if (brokerageAccountTypes.has(accountType)) return "Brokerages";
  if (externalAccountTypes.has(accountType)) return "Untracked Accounts";
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
  { value: "external", label: "Untracked account (Transfers only)" },
];

const reviewStatusLabel = (value: string) =>
  ({
    needs_review: "Needs review",
    suggested: "Suggested",
    possible_duplicate: "Possible duplicate",
    confirmed: "Confirmed",
  })[value] ?? readableAccountType(value);

const reviewStatusClass = (value: string) => `statusBadge ${value.replace(/_/g, "-")}`;

function visibleIdsFilter(visibleIds: number[], selectedIds: number[]) {
  return visibleIds.filter((id) => selectedIds.includes(id));
}

function toggleValue<T>(current: T[], value: T) {
  return current.includes(value) ? current.filter((item) => item !== value) : [...current, value];
}

function reportPeriodFilter(period: ReportPeriod, now = new Date()): TxnFilter {
  if (period === "all") return {};
  const year = now.getFullYear();
  const month = now.getMonth();
  const start = period === "this_month" ? new Date(year, month, 1) : period === "this_year" ? new Date(year, 0, 1) : new Date(year, month - 11, 1);
  const formatDate = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
  return { dateFrom: formatDate(start), dateTo: formatDate(now) };
}

function aggregatePath(dimension: "by-category" | "by-account" | "timeseries", filter: TxnFilter, bucket?: "day" | "week" | "month"): string {
  const params = encodeTxnFilter(filter);
  if (bucket) params.set("bucket", bucket);
  return `/api/aggregate/${dimension}?${params.toString()}`;
}

type ApiRequester = <T>(path: string, init?: RequestInit) => Promise<T>;

async function loadCategoryAggregates(request: ApiRequester, period: ReportPeriod): Promise<CategoryTotal[]> {
  const filter = { ...reportPeriodFilter(period), dateBasis: "reporting" as const, types: ["expense", "refund"] };
  const rows = await request<CategoryAggregateRow[]>(aggregatePath("by-category", filter));
  return rows.map((row) => ({ ...row, amount_cents: Math.abs(row.total_cents) })).sort((left, right) => right.amount_cents - left.amount_cents || left.category.localeCompare(right.category));
}

async function loadCashFlowAggregates(request: ApiRequester): Promise<MonthlyCashFlow[]> {
  const [incomeRows, expenseRows] = await Promise.all([
    request<AggregateRow[]>(aggregatePath("timeseries", { types: ["income"] }, "month")),
    request<AggregateRow[]>(aggregatePath("timeseries", { types: ["expense", "refund"] }, "month")),
  ]);
  const months = new Map<string, MonthlyCashFlow>();
  for (const row of incomeRows) {
    months.set(row.date.slice(0, 7), { month: row.date.slice(0, 7), income_cents: row.total_cents, expense_cents: 0, net_cents: row.total_cents });
  }
  for (const row of expenseRows) {
    const month = row.date.slice(0, 7);
    const current = months.get(month) ?? { month, income_cents: 0, expense_cents: 0, net_cents: 0 };
    current.expense_cents = -row.total_cents;
    current.net_cents += row.total_cents;
    months.set(month, current);
  }
  return Array.from(months.values()).sort((left, right) => left.month.localeCompare(right.month));
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

export function useFinanceController() {
  const api = useApiClient();
  const apiFetch = useApiFetch();
  const initialRoute = useRef(readAppRoute(window.location));
  const [configured, setConfigured] = useState(false);
  const [csrf, setCsrf] = useState("");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [toast, setToast] = useState<ToastState | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const transactionsVersion = useSyncExternalStore(subscribeTransactionsVersion, getTransactionsVersion, getTransactionsVersion);
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null);
  const [categories, setCategories] = useState<BootstrapCategory[]>([]);
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [transactions, setTransactions] = useState<TransactionRow[]>([]);
  const [operations, setOperations] = useState<OperationSummary[]>([]);
  const [expandedOperationId, setExpandedOperationId] = useState<string | null>(null);
  const [expandedOperation, setExpandedOperation] = useState<OperationDetail | null>(null);
  const [peekDrawer, setPeekDrawer] = useState<PeekDrawerState | null>(null);
  const [netWorthPeek, setNetWorthPeek] = useState<NetWorthPeekState | null>(null);
  const [rules, setRules] = useState<RuleSummary[]>([]);
  const [categoryTotals, setCategoryTotals] = useState<CategoryTotal[]>([]);
  const [cashFlowRows, setCashFlowRows] = useState<MonthlyCashFlow[]>([]);
  const [netWorthAccounts, setNetWorthAccounts] = useState<NetWorthAccount[]>([]);
  const [allocationRows, setAllocationRows] = useState<AllocationRow[]>([]);
  const [holdingRows, setHoldingRows] = useState<HoldingRow[]>([]);
  const [transferCandidates, setTransferCandidates] = useState<TransferCandidate[]>([]);
  const [refundSuggestions, setRefundSuggestions] = useState<RefundSuggestionGroup[]>([]);
  const [refundPicker, setRefundPicker] = useState<RefundPickerState | null>(null);
  const refundSearchTimer = useRef<number | null>(null);
  const [duplicatePairs, setDuplicatePairs] = useState<DuplicatePair[]>([]);
  const [reconciliationStatuses, setReconciliationStatuses] = useState<ReconciliationStatus[]>([]);
  const [paymentVerification, setPaymentVerification] = useState<PaymentVerificationStatus[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<number | "">("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null);
  const [importAnalysis, setImportAnalysis] = useState<ImportAnalysis | null>(null);
  const [createSeparateReplacement, setCreateSeparateReplacement] = useState(false);
  const [genericCsvMapping, setGenericCsvMapping] = useState<GenericCsvMapping>({ date: "", description: "", amount: "" });
  const [importSignConvention, setImportSignConvention] = useState<ImportSignConvention>("auto");
  const [importInbox, setImportInbox] = useState<ImportInboxState>({ folder: "", pending: [] });
  const [lastInboxScan, setLastInboxScan] = useState<ImportInboxScan | null>(null);
  const [importWorkspaceTab, setImportWorkspaceTab] = useState<"smart" | "manual">("smart");
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("imports");
  const [activeTab, setActiveTab] = useState<ReportTab>(initialRoute.current.filters.reportTab ?? "Overview");
  const [activeView, setActiveView] = useState<AppView>(initialRoute.current.view);
  const [focusedAccountId, setFocusedAccountId] = useState<number | null>(initialRoute.current.accountId);
  const [showAssetTransactions, setShowAssetTransactions] = useState(false);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [categoryEditor, setCategoryEditor] = useState<{ transactionId: number; query: string } | null>(null);
  const [editingAccountId, setEditingAccountId] = useState<number | null>(null);
  const [newCategoryLabel, setNewCategoryLabel] = useState("");
  const [newCategoryParentId, setNewCategoryParentId] = useState<number | "">("");
  const [editingCategoryId, setEditingCategoryId] = useState<number | null>(null);
  const [editingCategoryLabel, setEditingCategoryLabel] = useState("");
  const [editingCategoryParentId, setEditingCategoryParentId] = useState<number | "">("");
  const [categoryReassignId, setCategoryReassignId] = useState<number | "">("");
  const [editingRule, setEditingRule] = useState<RuleSummary | null>(null);
  const [ruleFeedback, setRuleFeedback] = useState<{ ruleId: number; message: string } | null>(null);
  const [lastSavedRule, setLastSavedRule] = useState<SavedRuleAction | null>(null);
  const [pendingRuleTransaction, setPendingRuleTransaction] = useState<TransactionRow | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const { selectedIds: selectedTransactionIds, setSelectedIds: setSelectedTransactionIds, toggle: toggleTransactionSelection, resetAnchor: resetTransactionSelectionAnchor } = useSelection();
  const { selectedIds: selectedAccountIds, setSelectedIds: setSelectedAccountIds, toggle: toggleAccountSelection, resetAnchor: resetAccountSelectionAnchor } = useSelection();
  const { selectedIds: selectedHoldingIds, setSelectedIds: setSelectedHoldingIds, toggle: toggleHoldingSelection, resetAnchor: resetHoldingSelectionAnchor } = useSelection();
  const [appImportFile, setAppImportFile] = useState<File | null>(null);
  const [categorizedHistoryFile, setCategorizedHistoryFile] = useState<File | null>(null);
  const [categorizedHistoryFilename, setCategorizedHistoryFilename] = useState("");
  const [categorizedHistoryRows, setCategorizedHistoryRows] = useState<CategorizedHistoryRow[]>([]);
  const [categorizedHistorySignConvention, setCategorizedHistorySignConvention] = useState<HistorySignConvention>("charges_positive");
  const [historyCleanupPreview, setHistoryCleanupPreview] = useState<HistoryCleanupPreview | null>(null);
  const [historyCleanupConfirm, setHistoryCleanupConfirm] = useState("");
  const [bulkReviewCategoryId, setBulkReviewCategoryId] = useState<number | "">("");
  const [bulkReviewType, setBulkReviewType] = useState("expense");
  const [reviewQueueFilter, setReviewQueueFilter] = useState<ReviewQueueFilter>("all");
  const [selectedTransactionAccountFilters, setSelectedTransactionAccountFilters] = useState<number[]>(() => (initialRoute.current.filters.accounts ?? []).map(Number).filter(Number.isFinite));
  const [selectedTransactionMonthFilters, setSelectedTransactionMonthFilters] = useState<string[]>(() => initialRoute.current.filters.months ?? []);
  const [selectedTransactionYearFilters, setSelectedTransactionYearFilters] = useState<string[]>(() => initialRoute.current.filters.years ?? []);
  const [selectedTransactionCategoryFilters, setSelectedTransactionCategoryFilters] = useState<string[]>(() => initialRoute.current.filters.categories ?? []);
  const [selectedTransactionTypeFilters, setSelectedTransactionTypeFilters] = useState<string[]>(() => initialRoute.current.filters.types ?? []);
  const [transactionDateFrom, setTransactionDateFrom] = useState(initialRoute.current.filters.dateFrom ?? "");
  const [transactionDateTo, setTransactionDateTo] = useState(initialRoute.current.filters.dateTo ?? "");
  const [transactionDateBasis, setTransactionDateBasis] = useState<TxnFilter["dateBasis"]>(initialRoute.current.filters.dateBasis);
  const [transactionAmountMin, setTransactionAmountMin] = useState<number | undefined>(initialRoute.current.filters.amountMin);
  const [transactionAmountMax, setTransactionAmountMax] = useState<number | undefined>(initialRoute.current.filters.amountMax);
  const [transactionDirection, setTransactionDirection] = useState<TxnFilter["direction"]>(initialRoute.current.filters.direction);
  const [transactionHasRefund, setTransactionHasRefund] = useState(Boolean(initialRoute.current.filters.hasRefund));
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
    loadCategoryAggregates(api, reportPeriod)
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
    setSelectedTransactionTypeFilters(routeFilters.types ?? []);
    setTransactionDateBasis(routeFilters.dateBasis);
    setTransactionHasRefund(Boolean(routeFilters.hasRefund));
    setTransactionFiltersInitialized(true);
  }, [accounts, categories, transactions, transactionFiltersInitialized]);

  useEffect(() => {
    function onPopState() {
      const route = readAppRoute(window.location);
      setActiveView(route.view);
      setFocusedAccountId(route.accountId);
      setActiveTab(route.filters.reportTab ?? "Overview");
      setShowAssetTransactions(false);
      setSelectedTransactionAccountFilters(route.filters.accounts === undefined ? accounts.map((account) => account.id) : route.filters.accounts.map(Number).filter(Number.isFinite));
      setSelectedTransactionMonthFilters(route.filters.months === undefined ? monthOptions.map((month) => month.value) : route.filters.months);
      setSelectedTransactionYearFilters(route.filters.years === undefined ? Array.from(new Set(transactions.map((transaction) => transaction.transaction_date.slice(0, 4)).filter(Boolean))) : route.filters.years);
      setSelectedTransactionCategoryFilters(route.filters.categories === undefined ? [...categories.map((category) => String(category.id)), uncategorizedFilterValue] : route.filters.categories);
      setSelectedTransactionTypeFilters(route.filters.types ?? []);
      setTransactionDateFrom(route.filters.dateFrom ?? "");
      setTransactionDateTo(route.filters.dateTo ?? "");
      setTransactionDateBasis(route.filters.dateBasis);
      setTransactionAmountMin(route.filters.amountMin);
      setTransactionAmountMax(route.filters.amountMax);
      setTransactionDirection(route.filters.direction);
      setTransactionHasRefund(Boolean(route.filters.hasRefund));
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
      types: selectedTransactionTypeFilters.length > 0 ? selectedTransactionTypeFilters : undefined,
      dateFrom: transactionDateFrom || undefined,
      dateTo: transactionDateTo || undefined,
      dateBasis: transactionDateBasis,
      amountMin: transactionAmountMin,
      amountMax: transactionAmountMax,
      direction: transactionDirection,
      view: transactionView,
      search: transactionSearch || undefined,
      sort: transactionSortKey,
      sortDirection: transactionSortDirection,
      netWorthPeriod: readAppRoute(window.location).filters.netWorthPeriod,
      hasRefund: transactionHasRefund || undefined,
      holdingSort: readAppRoute(window.location).filters.holdingSort,
      holdingSortDirection: readAppRoute(window.location).filters.holdingSortDirection,
      reportTab: activeView === "overview" ? activeTab : readAppRoute(window.location).filters.reportTab,
    };
    const nextUrl = routeUrl(activeView, focusedAccountId, filters);
    const currentUrl = `${window.location.pathname}${window.location.search}`;
    if (nextUrl !== currentUrl) window.history.replaceState({}, "", nextUrl);
  }, [
    accounts,
    activeTab,
    activeView,
    categories,
    focusedAccountId,
    selectedTransactionAccountFilters,
    selectedTransactionCategoryFilters,
    selectedTransactionTypeFilters,
    selectedTransactionMonthFilters,
    selectedTransactionYearFilters,
    transactionAmountMax,
    transactionAmountMin,
    transactionDateFrom,
    transactionDateTo,
    transactionDateBasis,
    transactionDirection,
    transactionHasRefund,
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
    selectedTransactionTypeFilters,
    transactionAmountMax,
    transactionAmountMin,
    transactionDateFrom,
    transactionDateTo,
    transactionDateBasis,
    transactionDirection,
    transactionHasRefund,
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
  }, [csrf, transactionView, transactionsVersion]);

  useEffect(() => {
    function onVisibilityChange() {
      if (document.visibilityState === "visible") bumpTransactionsVersion();
    }
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => document.removeEventListener("visibilitychange", onVisibilityChange);
  }, []);

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
    const data = await api<{ configured: boolean; categories: BootstrapCategory[]; net_worth_notice: Array<{ id: number; name: string }> }>("/api/bootstrap");
    setConfigured(data.configured);
    setCategories(data.categories);
    if (data.configured) {
      try {
        const me = await api<{ csrf_token: string }>("/api/me");
        setCsrf(me.csrf_token);
        await loadCoreData();
        void loadSecondaryData();
        const noticeKey = `privateFinance.netWorthAnchoringNotice.${data.net_worth_notice.map((account) => account.id).join("-")}`;
        if (data.net_worth_notice.length && !window.localStorage.getItem(noticeKey)) {
          window.localStorage.setItem(noticeKey, "seen");
          showToast({ tone: "info", message: `${data.net_worth_notice.length} unanchored account${data.net_worth_notice.length === 1 ? " is" : "s are"} now excluded from net worth. Add a statement balance or change the account override to include it.` });
        }
      } catch {
        setCsrf("");
      }
    }
  }

  async function loadCoreData() {
    await Promise.all([
      api<DashboardSummary>("/api/dashboard/summary").then(setDashboard),
      api<AccountSummary[]>("/api/accounts").then(setAccounts),
      api<TransactionRow[]>(`/api/transactions?view=${transactionView}`).then(setTransactions),
    ]);
  }

  async function loadSecondaryData() {
    await Promise.allSettled([
      api<RuleSummary[]>("/api/rules").then(setRules),
      loadCategoryAggregates(api, reportPeriod).then(setCategoryTotals),
      loadCashFlowAggregates(api).then(setCashFlowRows),
      api<NetWorthAccount[]>("/api/net-worth/accounts").then(setNetWorthAccounts),
      api<AllocationRow[]>("/api/investments/allocation").then(setAllocationRows),
      api<HoldingRow[]>("/api/investments/holdings").then(setHoldingRows),
      api<TransferCandidate[]>("/api/transfers/unconfirmed").then(setTransferCandidates),
      api<RefundSuggestionGroup[]>("/api/refunds/suggestions").then(setRefundSuggestions),
      api<DuplicatePair[]>("/api/duplicates/pending").then(setDuplicatePairs),
      api<ReconciliationStatus[]>("/api/reconciliation").then(setReconciliationStatuses),
      api<PaymentVerificationStatus[]>("/api/transfers/payments").then(setPaymentVerification),
      api<ImportInboxState>("/api/imports/inbox").then(setImportInbox),
      api<OperationSummary[]>("/api/operations?limit=100").then(setOperations),
    ]);
  }

  async function loadData() {
    await Promise.all([loadCoreData(), loadSecondaryData()]);
  }

  function showToast(nextToast: ToastState) {
    setToast(nextToast);
  }

  async function undoLoggedOperation(operationId: string, unconflictedOnly = false) {
    setBusyAction(`undo-${operationId}`);
    try {
      const response = await apiFetch(`/api/operations/${operationId}/undo`, {
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

  async function openTransactionPeek(filter: TxnFilter, title: string) {
    try {
      const normalizedFilter = { ...filter, view: "live" as const };
      const rows = await api<TransactionRow[]>(`/api/transactions?${encodeTxnFilter(normalizedFilter).toString()}`);
      const sortedRows = normalizedFilter.sort === "amount" ? [...rows].sort((left, right) => Math.abs(right.amount_cents) - Math.abs(left.amount_cents) || right.transaction_date.localeCompare(left.transaction_date)) : rows;
      const types = new Set(normalizedFilter.types ?? []);
      const eyebrow = types.has("expense") || types.has("refund") ? "Spending deep dive" : types.has("income") ? "Income deep dive" : "Transaction peek";
      setPeekDrawer({ title, eyebrow, filter: normalizedFilter, rows: sortedRows.slice(0, 20) });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Transaction preview could not be loaded." });
    }
  }

  async function openNetWorthPeek(from: string, to: string) {
    try {
      const result = await api<NetWorthPeekState>(`/api/snapshots/networth/contributors?from=${from}&to=${to}`);
      setNetWorthPeek(result);
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Asset changes could not be loaded." });
    }
  }

  function openTransactionView(filter: TxnFilter) {
    const nextFilter = { ...filter, view: filter.view ?? "live" as const };
    setSelectedTransactionAccountFilters(nextFilter.accounts?.map(Number).filter(Number.isFinite) ?? accounts.map((account) => account.id));
    setSelectedTransactionMonthFilters(nextFilter.months ?? monthOptions.map((month) => month.value));
    setSelectedTransactionYearFilters(nextFilter.years ?? transactionYears);
    setSelectedTransactionCategoryFilters(nextFilter.categories ?? transactionCategoryOptions.map((option) => option.value));
    setSelectedTransactionTypeFilters(nextFilter.types ?? []);
    setTransactionDateFrom(nextFilter.dateFrom ?? "");
    setTransactionDateTo(nextFilter.dateTo ?? "");
    setTransactionDateBasis(nextFilter.dateBasis);
    setTransactionAmountMin(nextFilter.amountMin);
    setTransactionAmountMax(nextFilter.amountMax);
    setTransactionDirection(nextFilter.direction);
    setTransactionSearch(nextFilter.search ?? "");
    setTransactionView(nextFilter.view ?? "live");
    setTransactionSortKey(nextFilter.sort ?? "date");
    setTransactionSortDirection(nextFilter.sortDirection ?? "desc");
    setActiveView("all-accounts");
    setFocusedAccountId(null);
    setCategoryEditor(null);
    window.history.pushState({}, "", routeUrl("all-accounts", null, nextFilter));
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
    setCreateSeparateReplacement(false);
    setGenericCsvMapping({ date: "", description: "", amount: "" });
  }

  async function importFileForUpload(): Promise<File | null> {
    if (!selectedFile) return null;
    if (importAnalysis?.preset_type !== null) return selectedFile;
    const headers = importAnalysis.headers ?? [];
    if (!genericCsvMapping.date || !genericCsvMapping.description || !genericCsvMapping.amount) {
      throw new Error("Map the date, description, and amount columns before previewing.");
    }
    const rows = parseCsvText(await selectedFile.text());
    const indexes = [genericCsvMapping.date, genericCsvMapping.description, genericCsvMapping.amount].map((header) => headers.indexOf(header));
    if (indexes.some((index) => index < 0)) throw new Error("One of the saved column mappings no longer exists in this file.");
    const mappedRows = [["PF Date", "PF Description", "PF Amount"], ...rows.slice(1).map((row) => indexes.map((index) => row[index] ?? ""))];
    const content = mappedRows.map((row) => row.map(csvCell).join(",")).join("\r\n");
    const signature = headers.join("\u001f");
    window.localStorage.setItem(`privateFinance.csvMapping.${signature}`, JSON.stringify({ ...genericCsvMapping, signConvention: importSignConvention }));
    return new File([content], `mapped-${selectedFile.name}`, { type: "text/csv" });
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
      await loadCoreData();
      void loadSecondaryData();
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
      const result = await api<{ id?: number; operation_id?: string }>(isEditing ? `/api/accounts/${editingAccountId}` : "/api/accounts", {
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
        operationId: result.operation_id,
      });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Account could not be saved." });
    }
  }

  async function setAccountStatus(account: AccountSummary, status: "active" | "archived") {
    try {
      const result = await api<{ operation_id: string }>(`/api/accounts/${account.id}`, {
        method: "PATCH",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ status }),
      });
      if (status === "archived" && focusedAccountId === account.id) {
        navigateToView("all-accounts");
      }
      await loadData();
      showToast({ tone: "success", message: status === "archived" ? `${account.display_name} moved to Archived Accounts.` : `${account.display_name} restored.`, operationId: result.operation_id });
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
      const category = await api<BootstrapCategory & { operation_id?: string }>("/api/categories", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ label, parent_id: newCategoryParentId || null }),
      });
      setCategories((current) => [...current, category].sort((left, right) => left.label.localeCompare(right.label)));
      setNewCategoryLabel("");
      setNewCategoryParentId("");
      showToast({ tone: "success", message: "Category added. You can use it during review now.", operationId: category.operation_id });
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
      const result = await api<{ operation_id: string }>(`/api/categories/${editingCategoryId}`, {
        method: "PATCH",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ label, parent_id: editingCategoryParentId || null }),
      });
      setCategories((current) =>
        current.map((category) => (category.id === editingCategoryId ? { ...category, label, parent_id: editingCategoryParentId || null } : category)).sort((left, right) => left.label.localeCompare(right.label)),
      );
      setEditingCategoryId(null);
      setEditingCategoryLabel("");
      setEditingCategoryParentId("");
      showToast({ tone: "success", message: "Category renamed.", operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Category could not be updated." });
    }
  }

  async function previewSelectedImport(signOverride: ImportSignConvention = importSignConvention, showReadyToast = true) {
    if (busyAction) {
      return;
    }
    setToast(null);
    setImportPreview(null);
    if (!selectedAccountId) {
      showToast({ tone: "error", message: "Choose or add the account this file belongs to first." });
      return;
    }
    if (!selectedFile) {
      showToast({ tone: "error", message: "Choose a CSV, OFX/QFX, or PDF file before previewing." });
      return;
    }
    setBusyAction("import");
    try {
      const uploadFile = await importFileForUpload();
      if (!uploadFile) throw new Error("Choose a supported import file before previewing.");
      const form = new FormData();
      form.append("file", uploadFile);
      const response = await apiFetch(`/api/imports/preview?account_id=${selectedAccountId}&sign_convention=${signOverride}`, {
        method: "POST",
        credentials: "include",
        body: form,
      });
      if (!response.ok) {
        throw new Error(await readableApiError(response, `/api/imports/preview?account_id=${selectedAccountId}`));
      }
      const preview = (await response.json()) as ImportPreview;
      setImportPreview(preview);
      if (showReadyToast) showToast({ tone: "success", message: `Preview ready: ${preview.rows.length} sample rows detected.` });
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
    setBusyAction("import");
    try {
      const uploadFile = await importFileForUpload();
      if (!uploadFile) throw new Error("Choose a supported import file before staging.");
      const form = new FormData();
      form.append("file", uploadFile);
      const response = await apiFetch(`/api/imports/stage?account_id=${selectedAccountId}&sign_convention=${importSignConvention}`, {
        method: "POST",
        credentials: "include",
        headers: { "x-csrf-token": csrf },
        body: form,
      });
      if (!response.ok) {
        throw new Error(await readableApiError(response, `/api/imports/stage?account_id=${selectedAccountId}`));
      }
      const result = (await response.json()) as { batch_id: number; filename: string; row_count: number; pending: InboxBatch[] };
      setImportInbox((current) => ({ ...current, pending: result.pending }));
      setImportPreview(null);
      setSelectedFile(null);
      setImportModalOpen(false);
      setImportWorkspaceTab("smart");
      navigateToView("settings");
      showToast({ tone: "success", message: `${result.filename} is staged with ${result.row_count} rows. Review and confirm it in the Import Inbox.` });
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

  async function categorizeTransaction(
    transaction: TransactionRow,
    patch: Partial<Pick<TransactionRow, "category_id" | "transaction_type">>,
  ) {
    const nextTransaction = { ...transaction, ...patch };
    const operationId = await updateTransaction(transaction.id, patch, false);
    if (!operationId) return false;
    const categorizationIsComplete = !transactionTypeUsesCategory(nextTransaction.transaction_type) || nextTransaction.category_id !== null;
    if (categorizationIsComplete) {
      setPendingRuleTransaction(nextTransaction);
      if (editingTransactionId === transaction.id) exitTransactionEdit();
    }
    return true;
  }

  async function deleteOrMergeCategory() {
    if (!editingCategoryId) return;
    const category = categories.find((item) => item.id === editingCategoryId);
    const replacement = categories.find((item) => item.id === categoryReassignId);
    try {
      const suffix = replacement ? `?reassign_to=${replacement.id}` : "";
      const result = await api<{ operation_id: string }>(`/api/categories/${editingCategoryId}${suffix}`, { method: "DELETE", headers: { "x-csrf-token": csrf } });
      setCategories((current) => current.filter((item) => item.id !== editingCategoryId));
      setEditingCategoryId(null);
      setEditingCategoryLabel("");
      setEditingCategoryParentId("");
      setCategoryReassignId("");
      await loadData();
      showToast({ tone: "success", message: replacement ? `${category?.label ?? "Category"} merged into ${replacement.label}.` : "Unused category deleted.", operationId: result.operation_id });
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
      const result = await api<{ operation_id: string }>(`/api/transactions/${transaction.id}/splits`, { method: "POST", headers: { "x-csrf-token": csrf }, body: JSON.stringify({ splits }) });
      setSplitEditor(null);
      await loadData();
      showToast({ tone: "success", message: "Transaction split saved.", operationId: result.operation_id });
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
      const result = await api<{ operation_id: string }>(`/api/transactions/${transaction.id}/monthly-allocation`, {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ category_id: monthlyAllocationEditor.category_id, months, allocation_start: `${monthlyAllocationEditor.start_month}-01` }),
      });
      setMonthlyAllocationEditor(null);
      await loadData();
      showToast({ tone: "success", message: `Expense spread evenly from ${monthlyAllocationEditor.start_month} through ${monthlyAllocationEditor.end_month}.`, operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Monthly allocation could not be saved." });
    } finally {
      setBusyAction(null);
    }
  }

  async function removeMonthlyAllocation(transaction: TransactionRow) {
    setBusyAction(`allocation-${transaction.id}`);
    try {
      const result = await api<{ operation_id: string }>(`/api/transactions/${transaction.id}/monthly-allocation`, { method: "DELETE", headers: { "x-csrf-token": csrf } });
      await loadData();
      showToast({ tone: "success", message: "Monthly spread removed; the expense is again counted on its charge date.", operationId: result.operation_id });
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

  async function rememberImportSignConvention(signConvention: "preset" | "reverse") {
    if (!selectedAccountId || !importPreview?.preset_type) return;
    setBusyAction("sign-profile");
    try {
      const result = await api<{ operation_id: string }>(`/api/import-sign-profiles/${selectedAccountId}`, {
        method: "PUT",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({
          preset_type: importPreview.preset_type,
          sign_convention: signConvention === "reverse" ? "reverse_detected" : "canonical_as_detected",
          sample_note: selectedFile ? `Confirmed from ${selectedFile.name}` : null,
        }),
      });
      setImportSignConvention(signConvention);
      setBusyAction(null);
      await previewSelectedImport(signConvention, false);
      showToast({ tone: "success", message: "Saved this sign convention for future imports from this source.", operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "The sign convention could not be saved." });
    } finally {
      setBusyAction(null);
    }
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
      const result = await api<{ updated: number; merged: number; moved_transactions: number; operation_id?: string }>("/api/accounts/cleanup-imported", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
      });
      await loadData();
      showToast({
        tone: "success",
        message: `Cleaned imported accounts: ${result.updated} updated, ${result.merged} merged, ${result.moved_transactions} transactions moved.`,
        operationId: result.operation_id,
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
      const response = await apiFetch("/api/imports/analyze", {
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
      setCreateSeparateReplacement(false);
      if (analysis.preset_type === null) {
        const signature = (analysis.headers ?? []).join("\u001f");
        const saved = window.localStorage.getItem(`privateFinance.csvMapping.${signature}`);
        if (saved) {
          try {
            const parsed = JSON.parse(saved) as GenericCsvMapping & { signConvention?: ImportSignConvention };
            setGenericCsvMapping({ date: parsed.date, description: parsed.description, amount: parsed.amount });
            setImportSignConvention(parsed.signConvention ?? "auto");
          } catch {
            setGenericCsvMapping({ date: "", description: "", amount: "" });
            setImportSignConvention("auto");
          }
        } else {
          setGenericCsvMapping({ date: "", description: "", amount: "" });
        }
        showToast({ tone: "info", message: saved ? "Loaded the saved column mapping for this CSV format." : "Choose the three columns once, then preview the mapped CSV." });
      } else if (analysis.suggested_account_id) {
        setSelectedAccountId(analysis.suggested_account_id);
        showToast({ tone: "success", message: `Matched this CSV to an existing account with ${analysis.match_confidence}% confidence.` });
      } else if (analysis.proposed_account) {
        setSelectedAccountId("");
        setAccountForm({
          institution_name: analysis.proposed_account.institution_name ?? "",
          display_name: analysis.proposed_account.display_name,
          account_type: analysis.proposed_account.account_type,
          last_four: analysis.proposed_account.last_four ?? "",
        });
        showToast({ tone: "info", message: analysis.replacement_candidate_id ? "Confirm whether this is a replacement card before importing." : "No obvious account match found. I prefilled a new account for you to review." });
      }
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "CSV analysis failed." });
    }
  }

  async function confirmReplacementCard() {
    const candidateId = importAnalysis?.replacement_candidate_id;
    const lastFour = importAnalysis?.proposed_account?.last_four;
    if (!candidateId || !lastFour) {
      showToast({ tone: "error", message: "Analyze the replacement-card file again before confirming it." });
      return;
    }
    setBusyAction("card-replacement");
    try {
      const result = await api<{ operation_id: string }>(`/api/accounts/${candidateId}/identifiers`, {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ last_four: lastFour, make_current: true, source: "import_confirmation" }),
      });
      setSelectedAccountId(candidateId);
      setImportAnalysis((current) => current ? { ...current, suggested_account_id: candidateId, replacement_candidate_id: null, match_confidence: 100, reason: "Replacement card confirmed; prior and current card numbers now map to one account." } : current);
      await loadCoreData();
      showToast({ tone: "success", message: "Replacement card confirmed. Existing history stays together and both card suffixes will match future imports.", operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "The replacement card could not be confirmed." });
    } finally {
      setBusyAction(null);
    }
  }

  async function createAccountFromAnalysis() {
    setToast(null);
      if (!importAnalysis?.proposed_account) {
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
      const response = await apiFetch("/api/exports/app-data.json");
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
      const response = await apiFetch("/api/imports/app-data", {
        method: "POST",
        credentials: "include",
        headers: { "x-csrf-token": csrf },
        body: form,
      });
      if (!response.ok) {
        throw new Error(await readableApiError(response, "/api/imports/app-data"));
      }
      const result = await parseApiJson<{ operation_id: string }>(response, "/api/imports/app-data");
      setAppImportFile(null);
      await loadData();
      showToast({ tone: "success", message: "App data restored from export.", operationId: result.operation_id });
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
      const result = await api<{ inserted: number; skipped: number; accounts_created: number; categories_created: number; warnings: string[]; operation_id?: string }>("/api/imports/categorized-history/reviewed", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ filename: categorizedHistoryFilename || "categorized-history", rows: categorizedHistoryRows, sign_convention: categorizedHistorySignConvention }),
      });
      setCategorizedHistoryFile(null);
      setCategorizedHistoryFilename("");
      setCategorizedHistoryRows([]);
      await loadData();
      showToast({
        tone: "success",
        message: `Imported ${result.inserted} categorized transactions, created ${result.accounts_created} accounts and ${result.categories_created} categories. Skipped ${result.skipped} duplicates.`,
        operationId: result.operation_id,
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
      const response = await apiFetch(`/api/imports/categorized-history?sign_convention=${categorizedHistorySignConvention}`, {
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
        operationId: result.operation_id,
      });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Categorized history import failed." });
    } finally {
      setBusyAction(null);
    }
  }

  async function previewHistorySignCleanup() {
    setToast(null);
    try {
      const result = await api<HistoryCleanupPreview>("/api/maintenance/categorized-history-signs");
      setHistoryCleanupPreview(result);
      setHistoryCleanupConfirm("");
      showToast({ tone: "info", message: result.candidate_transactions > 0 ? `Found ${result.candidate_transactions} legacy transactions to normalize.` : "No legacy categorized-history sign cleanup remains." });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Historical sign cleanup preview failed." });
    }
  }

  async function applyHistorySignCleanup() {
    setToast(null);
    try {
      const result = await api<HistoryCleanupPreview & { updated: number; operation_id?: string; backup_name?: string }>("/api/maintenance/categorized-history-signs", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ confirm_text: historyCleanupConfirm }),
      });
      await loadData();
      setHistoryCleanupPreview({ ...result, candidate_transactions: 0, accounts: [] });
      setHistoryCleanupConfirm("");
      showToast({ tone: "success", message: `Normalized ${result.updated} categorized-history transactions.${result.backup_name ? ` Safety backup: ${result.backup_name}.` : ""}`, operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Historical sign cleanup failed." });
    }
  }

  async function detectTransfers() {
    setToast(null);
    try {
      const result = await api<{ created: number; operation_id?: string }>("/api/transfers/detect", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
      });
      await loadData();
      showToast({
        tone: "success",
        message: result.created > 0 ? `Found ${result.created} possible transfer/payment matches.` : "No new transfer/payment matches found.",
        operationId: result.operation_id,
      });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Transfer scan failed." });
    }
  }

  async function confirmTransferCandidate(candidateId: number) {
    setToast(null);
    try {
      const result = await api<{ operation_id: string }>(`/api/transfers/${candidateId}/confirm`, {
        method: "POST",
        headers: { "x-csrf-token": csrf },
      });
      await loadData();
      showToast({ tone: "success", message: "Transfer/payment confirmed and excluded from spending totals.", operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Transfer candidate could not be confirmed." });
    }
  }

  async function rejectTransferCandidate(candidateId: number) {
    setToast(null);
    try {
      const result = await api<{ operation_id: string }>(`/api/transfers/${candidateId}/reject`, {
        method: "POST",
        headers: { "x-csrf-token": csrf },
      });
      await loadData();
      showToast({ tone: "success", message: "Transfer/payment suggestion rejected.", operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Transfer candidate could not be rejected." });
    }
  }

  async function detectRefunds() {
    setBusyAction("refund-detect");
    try {
      const result = await api<{ created: number; removed: number; limit: number; limited: boolean; operation_id?: string }>("/api/refunds/detect", { method: "POST", headers: { "x-csrf-token": csrf } });
      await loadData();
      showToast({ tone: "success", message: result.created ? result.limited ? `Showing ${result.limit} refunds with the strongest ranked expense recommendations.` : `Found ${result.created} refund${result.created === 1 ? "" : "s"} with ranked expense recommendations.` : "No likely refund matches found.", operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Refund scan failed." });
    } finally {
      setBusyAction(null);
    }
  }

  function refundCandidateForSelection(selection: RefundSelection) {
    const group = refundSuggestions.find((item) => item.refund_transaction.id === selection.refund_transaction_id);
    return group?.candidates.find((candidate) => candidate.expense_transaction.id === selection.expense_transaction_id);
  }

  async function confirmRefundSelections(selections: RefundSelection[]) {
    if (selections.length === 0) return;
    const overRefund = selections.map(refundCandidateForSelection).find((candidate) => candidate?.would_exceed_expense);
    const allowOverRefund = Boolean(overRefund) && window.confirm(
      overRefund
        ? `This expense already has ${formatMoney(overRefund.existing_linked_refund_cents)} in linked refunds. The selected refund would bring the total to ${formatMoney(overRefund.linked_refund_cents)} against a ${formatMoney(overRefund.expense_amount_cents)} expense. Link it anyway?`
        : "Link the selected matches?",
    );
    if (overRefund && !allowOverRefund) return;
    setBusyAction("refund-confirm-selection");
    try {
      const result = await api<{ confirmed: number; operation_id: string }>("/api/refunds/confirm-selection", { method: "POST", headers: { "x-csrf-token": csrf }, body: JSON.stringify({ selections, allow_over_refund: allowOverRefund }) });
      await loadData();
      showToast({ tone: "success", message: `${result.confirmed} refund${result.confirmed === 1 ? "" : "s"} linked to the selected expense${result.confirmed === 1 ? "" : "s"}.`, operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "The selected refunds could not be confirmed." });
    } finally {
      setBusyAction(null);
    }
  }

  async function rejectRefundSelections(selections: RefundSelection[], bulk = true) {
    if (selections.length === 0) return;
    if (bulk && !window.confirm(`Reject the currently selected expense option for ${selections.length} refund${selections.length === 1 ? "" : "s"}? Other recommendations will remain available.`)) return;
    setBusyAction("refund-reject-selection");
    try {
      const result = await api<{ rejected: number; operation_id?: string }>("/api/refunds/reject-candidates", { method: "POST", headers: { "x-csrf-token": csrf }, body: JSON.stringify({ selections }) });
      await loadData();
      showToast({ tone: "info", message: `${result.rejected} refund candidate${result.rejected === 1 ? "" : "s"} dismissed.`, operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "The refund candidates could not be dismissed." });
    } finally {
      setBusyAction(null);
    }
  }

  async function settleRefundsWithoutExpense(refundIds: number[]) {
    if (refundIds.length === 0 || !window.confirm(`Keep ${refundIds.length} selected transaction${refundIds.length === 1 ? "" : "s"} as categorized refunds without linking an expense?`)) return;
    setBusyAction("refund-no-expense");
    try {
      const result = await api<{ resolved: number; operation_id?: string }>("/api/refunds/no-expense", { method: "POST", headers: { "x-csrf-token": csrf }, body: JSON.stringify({ refund_transaction_ids: refundIds }) });
      await loadData();
      showToast({ tone: "success", message: `${result.resolved} refund${result.resolved === 1 ? "" : "s"} marked reviewed without an expense link.`, operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "The refunds could not be settled." });
    } finally {
      setBusyAction(null);
    }
  }

  function confirmRefundSuggestion(suggestion: RefundSuggestionGroup, candidate: RefundCandidate) {
    return confirmRefundSelections([{ refund_transaction_id: suggestion.refund_transaction.id, expense_transaction_id: candidate.expense_transaction.id }]);
  }

  function rejectRefundSuggestion(suggestion: RefundSuggestionGroup, candidate: RefundCandidate) {
    return rejectRefundSelections([{ refund_transaction_id: suggestion.refund_transaction.id, expense_transaction_id: candidate.expense_transaction.id }], false);
  }

  async function loadRefundPicker(expenseId: number, search = "") {
    setRefundPicker((current) => ({ expenseId, candidates: current?.expenseId === expenseId ? current.candidates : [], links: current?.expenseId === expenseId ? current.links : [], search, loading: true }));
    try {
      const query = new URLSearchParams({ expense_transaction_id: String(expenseId) });
      if (search.trim()) query.set("search", search.trim());
      const [links, candidates] = await Promise.all([
        api<RefundLink[]>(`/api/refunds/expenses/${expenseId}`),
        api<DuplicateTransaction[]>(`/api/refunds/candidates?${query.toString()}`),
      ]);
      setRefundPicker((current) => current?.expenseId === expenseId && current.search === search ? { expenseId, candidates, links, search, loading: false } : current);
    } catch (error) {
      setRefundPicker((current) => current?.expenseId === expenseId && current.search === search ? { ...current, loading: false } : current);
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Possible refunds could not be loaded." });
    }
  }

  function searchRefundPicker(expenseId: number, search: string) {
    setRefundPicker((current) => current?.expenseId === expenseId ? { ...current, search } : current);
    if (refundSearchTimer.current !== null) window.clearTimeout(refundSearchTimer.current);
    refundSearchTimer.current = window.setTimeout(() => void loadRefundPicker(expenseId, search), 250);
  }

  async function linkManualRefund(expense: TransactionRow, candidate: DuplicateTransaction) {
    const linkedTotal = refundPicker?.expenseId === expense.id ? refundPicker.links.reduce((sum, link) => sum + link.refund_transaction.amount_cents, 0) : expense.refund_total_cents;
    const wouldExceed = linkedTotal + candidate.amount_cents > Math.abs(expense.amount_cents);
    const allowOverRefund = wouldExceed && window.confirm(`This would link ${formatMoney(linkedTotal + candidate.amount_cents)} of refunds to a ${formatMoney(Math.abs(expense.amount_cents))} expense. Link it anyway?`);
    if (wouldExceed && !allowOverRefund) return;
    try {
      const result = await api<{ operation_id: string }>("/api/refund-links", { method: "POST", headers: { "x-csrf-token": csrf }, body: JSON.stringify({ expense_transaction_id: expense.id, refund_transaction_id: candidate.id, confirmed: true, allow_over_refund: allowOverRefund }) });
      await loadData();
      await loadRefundPicker(expense.id, refundPicker?.search ?? "");
      showToast({ tone: "success", message: "Refund linked to this expense.", operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Refund could not be linked." });
    }
  }

  async function unlinkRefund(expenseId: number, linkId: number) {
    try {
      const result = await api<{ operation_id: string }>(`/api/refunds/${linkId}`, { method: "DELETE", headers: { "x-csrf-token": csrf } });
      await loadData();
      await loadRefundPicker(expenseId, refundPicker?.search ?? "");
      showToast({ tone: "info", message: "Refund unlinked from this expense.", operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Refund could not be unlinked." });
    }
  }

  async function confirmTransaction(transaction: TransactionRow) {
    if (!accounts.some((account) => account.id === transaction.account_id)) {
      showToast({ tone: "error", message: "Choose an account before confirming this transaction." });
      return;
    }
    if (transactionTypeRequiresCategory(transaction.transaction_type) && !transaction.category_id) {
      showToast({ tone: "error", message: `Choose a category before confirming this ${transaction.transaction_type}.` });
      return;
    }
    const operationId = await updateTransaction(transaction.id, { review_status: "confirmed" });
    if (operationId) showToast({ tone: "success", message: "Transaction confirmed.", operationId });
  }

  async function saveRuleFromTransaction(transaction: TransactionRow, draft?: RuleDraft): Promise<SavedRulePreview | null> {
    setToast(null);
    const transactionType = draft?.transactionType ?? transaction.transaction_type;
    const categoryId = draft?.categoryId ?? transaction.category_id;
    if (transactionTypeUsesCategory(transactionType) && !categoryId) {
      showToast({ tone: "error", message: "Choose a category before saving a rule." });
      return null;
    }
    const matchText = draft?.matchText.trim() || suggestedRuleText(transaction.raw_description);
    try {
      const rule = await api<{ id: number; operation_id: string }>("/api/rules", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({
          category_id: transactionTypeUsesCategory(transactionType) ? categoryId : null,
          field_name: "raw_description",
          match_text: matchText,
          suggested_transaction_type: transactionType,
          priority: 100,
        }),
      });
      let existingMatches = 0;
      try {
        const preview = await api<{ matched: number }>(`/api/rules/${rule.id}/preview?scope=all`);
        const includesCurrentTransaction = transaction.raw_description.toUpperCase().includes(matchText.toUpperCase());
        existingMatches = Math.max(0, preview.matched - (includesCurrentTransaction ? 1 : 0));
      } catch {
        // The rule is already saved; a failed preview should not misreport the save as a failure.
      }
      setLastSavedRule({ id: rule.id, matchText, transactionId: transaction.id });
      await loadData();
      showToast({ tone: "success", message: `Rule saved for "${matchText}".`, operationId: rule.operation_id });
      return { ruleId: rule.id, existingMatches };
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Rule could not be saved." });
      return null;
    }
  }

  async function bulkConfirmSelectedReviewTransactions() {
    setToast(null);
    if (selectedVisibleReviewTransactions.length === 0) {
      showToast({ tone: "error", message: "Select at least one review item first." });
      return;
    }
    if (transactionTypeUsesCategory(bulkReviewType) && !bulkReviewCategoryId) {
      showToast({ tone: "error", message: "Choose a category before confirming selected review items." });
      return;
    }
    try {
      const result = await api<{ operation_id: string }>("/api/operations/bulk-update", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ entity_type: "transaction", ids: selectedVisibleReviewTransactions.map((transaction) => transaction.id), patch: { category_id: transactionTypeUsesCategory(bulkReviewType) ? bulkReviewCategoryId : null, transaction_type: bulkReviewType, review_status: "confirmed" } }),
      });
      setSelectedTransactionIds((current) => current.filter((id) => !selectedVisibleReviewIds.includes(id)));
      resetTransactionSelectionAnchor();
      await loadData();
      showToast({ tone: "success", message: `Confirmed ${selectedVisibleReviewTransactions.length} selected review items.`, operationId: result.operation_id });
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
      const rules = selectedVisibleReviewTransactions.map((transaction) => {
        const categoryId = transactionTypeUsesCategory(bulkReviewType) ? transaction.category_id ?? (bulkReviewCategoryId || null) : null;
        return {
            category_id: categoryId,
            field_name: "raw_description",
            match_text: suggestedRuleText(transaction.raw_description),
            suggested_transaction_type: bulkReviewType,
            priority: 100,
          };
      });
      if (transactionTypeUsesCategory(bulkReviewType) && rules.some((rule) => !rule.category_id)) {
        showToast({ tone: "error", message: "Choose a category or select rows that already have categories before saving bulk rules." });
        return;
      }
      const result = await api<{ created: number; operation_id: string }>("/api/operations/bulk-create-rules", { method: "POST", headers: { "x-csrf-token": csrf }, body: JSON.stringify({ rules }) });
      await loadData();
      showToast({ tone: "success", message: `Saved ${result.created} rules from selected review items.`, operationId: result.operation_id });
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
      const result = await api<{ matched: number; updated: number; operation_id?: string }>(`/api/rules/${ruleId}/apply`, {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ scope }),
      });
      await loadData();
      const scopeLabel = scope === "unreviewed" ? "unreviewed transactions" : "previous transactions";
      showToast({ tone: "success", message: `Rule confirmed ${result.updated} of ${result.matched} matching ${scopeLabel}.`, operationId: result.operation_id });
      return true;
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Rule could not be applied." });
      return false;
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
      const result = await api<{ operation_id: string }>(`/api/rules/${editingRule.id}`, {
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
      showToast({ tone: "success", message: "Rule updated.", operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Rule could not be updated." });
    }
  }

  async function deleteRule(rule: RuleSummary) {
    try {
      const result = await api<{ operation_id: string }>(`/api/rules/${rule.id}`, { method: "DELETE", headers: { "x-csrf-token": csrf } });
      if (editingRule?.id === rule.id) setEditingRule(null);
      await loadData();
      showToast({ tone: "success", message: `Rule “${rule.match_text}” deleted.`, operationId: result.operation_id });
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
      const result = await api<{ operation_id: string }>("/api/investments/holding-metadata", {
        method: "PATCH",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ symbol, user_description: userDescription }),
      });
      await loadData();
      showToast({ tone: "success", message: `Description saved for ${symbol}. Future uploads will use it in Holding details.`, operationId: result.operation_id });
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
        const result = await api<{ operation_id: string }>("/api/accounts/bulk-delete", {
          method: "DELETE",
          headers: { "x-csrf-token": csrf },
          body: JSON.stringify({ ids: deleteTarget.ids, confirm_text: deleteConfirmText }),
        });
        operationId = result.operation_id;
      } else if (deleteTarget.kind === "holding_bulk") {
        const result = await api<{ operation_id: string }>("/api/investments/holdings/bulk-delete", {
          method: "DELETE",
          headers: { "x-csrf-token": csrf },
          body: JSON.stringify({ ids: deleteTarget.ids, confirm_text: deleteConfirmText }),
        });
        operationId = result.operation_id;
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
        operationId = result.operation_id;
      }
      const deletedKind = deleteTarget.kind;
      setDeleteTarget(null);
      setDeleteConfirmText("");
      setSelectedTransactionIds([]);
      resetTransactionSelectionAnchor();
      setSelectedAccountIds([]);
      resetAccountSelectionAnchor();
      setSelectedHoldingIds([]);
      resetHoldingSelectionAnchor();
      await loadData();
      const permanent = deletedKind.includes("permanent");
      const isTransactionDelete = deletedKind.startsWith("transaction");
      showToast({ tone: "success", message: permanent ? "Transaction data permanently deleted." : isTransactionDelete ? deletedKind.includes("bulk") ? "Selected rows moved to Trash." : "Row moved to Trash." : deletedKind.includes("bulk") ? "Selected rows deleted. Undo is available." : "Row deleted. Undo is available.", operationId });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Rows could not be deleted." });
    }
  }

  const missingCategoryTransactions = transactions.filter((transaction) => transactionTypeRequiresCategory(transaction.transaction_type) && !transaction.category_id);
  const refundSuggestionByTransactionId = useMemo(() => new Map(refundSuggestions.map((suggestion) => [suggestion.refund_transaction.id, suggestion])), [refundSuggestions]);
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
      balances.set(account.id, account.sidebar_balance_cents ?? 0);
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
  const replacementCandidate = accounts.find((account) => account.id === importAnalysis?.replacement_candidate_id);
  const previewRows = importPreview?.rows.slice(0, 6) ?? [];
  const normalizedTransactionSearch = transactionSearch.trim().toLowerCase();
  const transactionMatchesSearch = (transaction: TransactionRow) => {
    if (!normalizedTransactionSearch) return true;
    const category = categories.find((item) => item.id === transaction.category_id)?.label ?? "";
    const splitLabel = transaction.split_count > 0 ? `split split categories split into ${transaction.split_count} categories` : "";
    const allocationLabel = transaction.monthly_allocation_count > 0 ? `spread spread across months spread across ${transaction.monthly_allocation_count} months monthly allocation` : "";
    return [transaction.raw_description, transaction.user_note, transaction.labels.join(" "), transaction.account_name, transaction.institution_name, transaction.transaction_type, category, splitLabel, allocationLabel, formatMoney(transaction.amount_cents), transaction.transaction_date]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(normalizedTransactionSearch));
  };
  const duplicateCandidateIds = new Set(duplicatePairs.map((pair) => pair.candidate.id));
  const reviewQueueTransactions = filterReviewQueue(transactions, duplicateCandidateIds, "all");
  const uncategorizedRefunds = reviewQueueTransactions.filter(isUncategorizedRefund);
  const reviewTransactions = filterReviewQueue(transactions, duplicateCandidateIds, reviewQueueFilter).filter(transactionMatchesSearch);
  const visibleReviewTransactions = reviewTransactions.slice(0, 5);
  const activeAccounts = accounts.filter((account) => account.status === "active");
  const importableAccounts = activeAccounts.filter((account) => account.account_type !== "external");
  const externalAccounts = activeAccounts.filter((account) => account.account_type === "external");
  const archivedAccounts = accounts.filter((account) => account.status === "archived");
  const bankAccounts = activeAccounts.filter((account) => bankAccountTypes.has(account.account_type));
  const creditCardAccounts = activeAccounts.filter((account) => creditCardAccountTypes.has(account.account_type));
  const brokerageAccounts = activeAccounts.filter((account) => brokerageAccountTypes.has(account.account_type));
  const focusedMissingCategoryCount = focusedAccountId ? missingCategoryCountByAccount.get(focusedAccountId) ?? 0 : 0;
  const focusedAccountBalanceCents = focusedAccountId ? accountBalances.get(focusedAccountId) ?? 0 : 0;
  const focusedReconciliation = reconciliationStatuses.find((status) => status.account_id === focusedAccountId) ?? null;
  const focusedPaymentVerification = paymentVerification.find((status) => status.account_id === focusedAccountId) ?? null;
  const focusedHoldingRows = focusedAccountId ? holdingRows.filter((row) => row.account_id === focusedAccountId) : [];
  const focusedAccountIsAsset = Boolean(focusedAccount && isBrokerageAccountType(focusedAccount.account_type));
  const accountTransactionsVisible = !focusedAccountIsAsset || showAssetTransactions;
  const transactionYears = Array.from(new Set(transactions.map((transaction) => transaction.transaction_date.slice(0, 4)).filter(Boolean))).sort((left, right) => right.localeCompare(left));
  const transactionCategoryOptions: FilterOption[] = [...categories.map((category) => ({ value: String(category.id), label: category.label })), { value: uncategorizedFilterValue, label: "Uncategorized" }];
  const effectiveTransactionCategoryFilters = new Set(selectedTransactionCategoryFilters);
  for (const category of categories) {
    if (category.parent_id !== null && effectiveTransactionCategoryFilters.has(String(category.parent_id))) effectiveTransactionCategoryFilters.add(String(category.id));
  }

  async function applyRuleToTransaction(ruleId: number, transactionId: number) {
    try {
      const result = await api<{ updated: number; operation_id?: string }>(`/api/rules/${ruleId}/apply-to/${transactionId}`, {
        method: "POST",
        headers: { "x-csrf-token": csrf },
      });
      await loadData();
      showToast({ tone: "success", message: result.updated ? "Rule applied and transaction confirmed." : "Transaction already matched this rule.", operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Rule could not be applied to this transaction." });
    }
  }

  async function selectAllMatchingTransactions() {
    const allAccountIds = accounts.map((account) => account.id);
    const allCategories = transactionCategoryOptions.map((option) => option.value);
    const filter: TxnFilter = {
      accounts: activeView === "account" && focusedAccountId ? [String(focusedAccountId)] : sameFilterValues(selectedTransactionAccountFilters, allAccountIds) ? undefined : selectedTransactionAccountFilters.map(String),
      categories: sameFilterValues(selectedTransactionCategoryFilters, allCategories) ? undefined : selectedTransactionCategoryFilters,
      months: sameFilterValues(selectedTransactionMonthFilters, monthOptions.map((month) => month.value)) ? undefined : selectedTransactionMonthFilters,
      years: sameFilterValues(selectedTransactionYearFilters, transactionYears) ? undefined : selectedTransactionYearFilters,
      types: selectedTransactionTypeFilters.length > 0 ? selectedTransactionTypeFilters : undefined,
      dateFrom: transactionDateFrom || undefined,
      dateTo: transactionDateTo || undefined,
      dateBasis: transactionDateBasis,
      amountMin: transactionAmountMin,
      amountMax: transactionAmountMax,
      direction: transactionDirection,
      hasRefund: transactionHasRefund || undefined,
      search: transactionSearch.trim() || undefined,
      view: transactionView,
    };
    setBusyAction("select-all-transactions");
    try {
      const ids = await api<number[]>(`/api/transactions/ids?${encodeTxnFilter(filter).toString()}`);
      setSelectedTransactionIds((current) => Array.from(new Set([...current, ...ids])));
      showToast({ tone: "info", message: `Selected all ${ids.length} transactions matching the current filters.` });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Matching transactions could not be selected." });
    } finally {
      setBusyAction(null);
    }
  }
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
      .filter((transaction) => transaction.reporting_category_ids.some((categoryId) => effectiveTransactionCategoryFilters.has(categoryId === null ? uncategorizedFilterValue : String(categoryId))))
      .filter((transaction) => selectedTransactionTypeFilters.length === 0 || selectedTransactionTypeFilters.includes(transaction.transaction_type))
      .filter((transaction) => {
        const dates = transactionDateBasis === "reporting" ? transaction.reporting_dates : [transaction.transaction_date];
        return dates.some((value) => (!transactionDateFrom || value >= transactionDateFrom) && (!transactionDateTo || value <= transactionDateTo));
      })
      .filter((transaction) => transactionAmountMin === undefined || Math.abs(transaction.amount_cents) >= transactionAmountMin)
      .filter((transaction) => transactionAmountMax === undefined || Math.abs(transaction.amount_cents) <= transactionAmountMax)
      .filter((transaction) => !transactionHasRefund || transaction.refund_link_count > 0 || transaction.refund_expense_id !== null)
      .filter((transaction) => transactionDirection === undefined || (transactionDirection === "inflow" ? transaction.amount_cents > 0 : transaction.amount_cents < 0));
    return [...rows].sort((left, right) => {
      const direction = transactionSortDirection === "asc" ? 1 : -1;
      if (transactionSortKey === "amount") {
        return (Math.abs(left.amount_cents) - Math.abs(right.amount_cents)) * direction;
      }
      const dateCompare = left.transaction_date.localeCompare(right.transaction_date);
      return dateCompare === 0 ? (left.id - right.id) * direction : dateCompare * direction;
    });
  })();
  const transactionSummaryFilter: TxnFilter = {
    accounts: activeView === "account" && focusedAccountId ? [String(focusedAccountId)] : sameFilterValues(selectedTransactionAccountFilters, accounts.map((account) => account.id)) ? undefined : selectedTransactionAccountFilters.map(String),
    categories: sameFilterValues(selectedTransactionCategoryFilters, transactionCategoryOptions.map((option) => option.value)) ? undefined : selectedTransactionCategoryFilters,
    months: sameFilterValues(selectedTransactionMonthFilters, monthOptions.map((month) => month.value)) ? undefined : selectedTransactionMonthFilters,
    years: sameFilterValues(selectedTransactionYearFilters, transactionYears) ? undefined : selectedTransactionYearFilters,
    types: selectedTransactionTypeFilters.length > 0 ? selectedTransactionTypeFilters : undefined,
    dateFrom: transactionDateFrom || undefined,
    dateTo: transactionDateTo || undefined,
    dateBasis: transactionDateBasis,
    amountMin: transactionAmountMin,
    amountMax: transactionAmountMax,
    direction: transactionDirection,
    hasRefund: transactionHasRefund || undefined,
    search: transactionSearch.trim() || undefined,
    view: transactionView,
  };
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
    { label: "Untracked Accounts", rows: externalAccounts, emptyText: "No untracked accounts yet." },
  ];
  const taxonomyTree = taxonomySections.map((section) => ({
    ...section,
    totalCents: section.rows.reduce((sum, account) => sum + (accountBalances.get(account.id) ?? 0), 0),
    groups: buildTaxonomyGroups(section.rows, accountBalances, taxonomyOverrides),
  }));
  const sidebarAccountSection = {
    label: "Accounts",
    rows: activeAccounts,
    emptyText: "No accounts yet.",
    totalCents: activeAccounts.reduce((sum, account) => sum + (accountBalances.get(account.id) ?? 0), 0),
    groups: buildTaxonomyGroups(activeAccounts, accountBalances, taxonomyOverrides),
  };
  const sidebarTaxonomyTree = archivedAccounts.length > 0
    ? [sidebarAccountSection, {
        label: "Archived Accounts",
        rows: archivedAccounts,
        emptyText: "",
        totalCents: archivedAccounts.reduce((sum, account) => sum + (accountBalances.get(account.id) ?? 0), 0),
        groups: buildTaxonomyGroups(archivedAccounts, accountBalances, taxonomyOverrides),
      }]
    : [sidebarAccountSection];
  const latestCashFlowRows = periodCashFlowRows.slice(-4).reverse();
  const reviewCount = reviewQueueTransactions.length;
  const accountNeedingTaxonomy = accounts.find((account) => !taxonomyOverrides[String(account.id)] && !account.institution_name);
  const transactionFilterChips: Array<{ key: string; label: string; onRemove: () => void }> = [];
  if (activeView === "account" && focusedAccount) {
    transactionFilterChips.push({ key: "account-route", label: `Account: ${accountOptionLabel(focusedAccount)}`, onRemove: () => navigateToView("all-accounts") });
  } else if (activeView === "all-accounts" && !sameFilterValues(selectedTransactionAccountFilters, accounts.map((account) => account.id))) {
    transactionFilterChips.push({ key: "accounts", label: selectionSummary("Accounts", selectedTransactionAccountFilters.map(String), accounts.map((account) => ({ value: String(account.id), label: accountOptionLabel(account) }))), onRemove: () => setSelectedTransactionAccountFilters(accounts.map((account) => account.id)) });
  }

  async function saveManualNetWorthSnapshot(accountId: number, snapshotDate: string, balance: string) {
    const balanceCents = moneyInputToCents(balance);
    if (!accountId || !snapshotDate || balanceCents === null) {
      showToast({ tone: "error", message: "Choose an account, date, and valid balance." });
      return false;
    }
    try {
      const result = await api<{ operation_id: string }>("/api/snapshots/networth/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-csrf-token": csrf },
        body: JSON.stringify({ account_id: accountId, snapshot_date: snapshotDate, balance_cents: balanceCents }),
      });
      await loadData();
      showToast({ tone: "success", message: "Manual balance added to net worth history.", operationId: result.operation_id });
      return true;
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Manual balance could not be saved." });
      return false;
    }
  }

  function investigateReconciliation(status: ReconciliationStatus) {
    if (!status.latest) return;
    setTransactionDateFrom(status.latest.investigate_from);
    setTransactionDateTo(status.latest.investigate_to);
    setTransactionSearch("");
    document.querySelector(".ledgerWorkspace")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function investigatePayment(warning: PaymentWarning) {
    setTransactionDateFrom(warning.transaction_date);
    setTransactionDateTo(warning.transaction_date);
    setTransactionSearch(warning.description);
    document.querySelector(".ledgerWorkspace")?.scrollIntoView({ behavior: "smooth", block: "start" });
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

  async function confirmStatementBalanceBatch(
    batch: InboxBatch,
    selection: { statement_date: string; balance_cents: number; candidate_index: number | null },
  ) {
    setBusyAction(`inbox-confirm-${batch.id}`);
    try {
      await api(`/api/imports/${batch.id}/statement-preview`, {
        method: "PATCH",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify(selection),
      });
      const result = await api<{ inserted: number; operation_id?: string }>(`/api/imports/${batch.id}/confirm`, {
        method: "POST",
        headers: { "x-csrf-token": csrf },
      });
      await loadData();
      showToast({ tone: "success", message: `Statement balance from ${batch.filename} now anchors ${batch.account_name}.`, operationId: result.operation_id });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Statement balance could not be confirmed." });
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
  if (selectedTransactionTypeFilters.length > 0) transactionFilterChips.push({ key: "types", label: selectedTransactionTypeFilters.map((value) => transactionTypeLabels[value] ?? value).join(" + "), onRemove: () => setSelectedTransactionTypeFilters([]) });
  if (transactionDateFrom) transactionFilterChips.push({ key: "date-from", label: `From: ${formatShortDate(transactionDateFrom)}`, onRemove: () => setTransactionDateFrom("") });
  if (transactionDateTo) transactionFilterChips.push({ key: "date-to", label: `Through: ${formatShortDate(transactionDateTo)}`, onRemove: () => setTransactionDateTo("") });
  if (transactionDateBasis === "reporting") transactionFilterChips.push({ key: "date-basis", label: "Dates: spending allocation", onRemove: () => setTransactionDateBasis(undefined) });
  if (transactionAmountMin !== undefined) transactionFilterChips.push({ key: "amount-min", label: `Minimum: ${formatMoney(transactionAmountMin)}`, onRemove: () => setTransactionAmountMin(undefined) });
  if (transactionAmountMax !== undefined) transactionFilterChips.push({ key: "amount-max", label: `Maximum: ${formatMoney(transactionAmountMax)}`, onRemove: () => setTransactionAmountMax(undefined) });
  if (transactionDirection) transactionFilterChips.push({ key: "direction", label: transactionDirection === "inflow" ? "Inflows" : "Outflows", onRemove: () => setTransactionDirection(undefined) });
  if (transactionHasRefund) transactionFilterChips.push({ key: "has-refund", label: "Has a linked refund", onRemove: () => setTransactionHasRefund(false) });

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
    const nextFilter = freshAccountNavigationFilter(accountId);
    setSelectedAccountId(accountId); setSelectedTransactionAccountFilters([accountId]);
    setSelectedTransactionMonthFilters(monthOptions.map((month) => month.value)); setSelectedTransactionYearFilters(transactionYears);
    setSelectedTransactionCategoryFilters(transactionCategoryOptions.map((option) => option.value)); setSelectedTransactionTypeFilters([]);
    setTransactionDateFrom(""); setTransactionDateTo(""); setTransactionDateBasis(undefined);
    setTransactionAmountMin(undefined); setTransactionAmountMax(undefined); setTransactionDirection(undefined);
    setTransactionHasRefund(false); setTransactionSearch(""); setTransactionView("live");
    setTransactionSortKey("date"); setTransactionSortDirection("desc");
    window.history.pushState({}, "", routeUrl("account", accountId, nextFilter));
    setActiveView("account");
    setFocusedAccountId(accountId);
    setCategoryEditor(null);
    setFocusedTransactionId(null);
    setEditingTransactionId(null);
    setShowAssetTransactions(false);
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
    if (!focusedAccountId) return;
    const firstMissing = missingCategoryTransactions.find((transaction) => transaction.account_id === focusedAccountId);
    setTransactionView("live");
    setSelectedTransactionMonthFilters(monthOptions.map((month) => month.value));
    setSelectedTransactionYearFilters(transactionYears);
    setSelectedTransactionCategoryFilters([uncategorizedFilterValue]);
    setSelectedTransactionTypeFilters(["expense", "refund"]);
    setTransactionDateFrom("");
    setTransactionDateTo("");
    setTransactionAmountMin(undefined);
    setTransactionAmountMax(undefined);
    setTransactionDirection(undefined);
    setTransactionHasRefund(false);
    setTransactionSearch("");
    setShowAssetTransactions(true);
    setFocusedTransactionId(firstMissing?.id ?? null);
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      const target = firstMissing ? document.getElementById(`transaction-row-${firstMissing.id}`) : document.getElementById("account-transactions");
      target?.scrollIntoView({ behavior: "smooth", block: firstMissing ? "center" : "start" });
    }));
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

  return {
    accountForm, accountIds, accountNeedingTaxonomy, accountTransactionsVisible, accounts,
    activeAccounts, activeTab, activeView, allRepositoryTransactionsSelected, allocationRows, analyzeSelectedImport,
    analyzedAccount, appImportFile, applyHistorySignCleanup, applyRule, applyRuleToTransaction, applySavedRule,
    beginEditAccount, bulkConfirmSelectedReviewTransactions, bulkEditField, bulkEditValue, bulkEditorOpen, bulkReviewCategoryId,
    bulkReviewType, bulkSaveRulesForSelectedReviewTransactions, bulkUpdateSelectedTransactions, busyAction, cashFlowRows, categories,
    categorizedHistoryFile, categorizedHistoryMissingFields, categorizedHistoryRows, categorizedHistorySignConvention, categorizeTransaction, categoryEditor, categoryReassignId,
    categorySuggestions, chooseImportFile, cleanupImportedAccounts, clearAccountForm, clearTaxonomyOverride, collapsedTaxonomyGroups,
    commitReviewedCategorizedHistory, commitSelectedImport, confirmDelete, confirmInboxBatch, confirmRefundSelections, confirmRefundSuggestion,
    confirmReplacementCard, confirmStatementBalanceBatch, confirmTransaction, confirmTransactionEdit, confirmTransferCandidate, createAccountFromAnalysis, createCategory,
    csrf, dashboardCustomizeOpen, dashboardWidgets, deleteCategorizedHistoryRow, deleteConfirmText, deleteOrMergeCategory,
    deleteRule, deleteTarget, detectRefunds, detectTransfers, discardInboxBatch,
    downloadAppExport, duplicatePairs, editingAccountId, editingCategoryId, editingCategoryLabel, editingCategoryParentId,
    editingRule, editingTransactionId, exitTransactionEdit, expandedOperation, expandedOperationId, externalAccounts,
    filteredTransactions, focusedAccount, focusedAccountBalanceCents, focusedAccountId, focusedAccountIsAsset, focusedHoldingRows,
    focusedMissingCategoryCount, focusedPaymentVerification, focusedReconciliation, focusedTransactionId, genericCsvMapping,
    handleLogout, handleTransactionRowClick, historyCleanupConfirm, historyCleanupPreview, holdingRows, importAnalysis,
    importCategorizedHistory, importInbox, importModalOpen, importPreview, importSignConvention, importWorkspaceTab,
    importableAccounts, investigatePayment, investigateReconciliation,
    lastInboxScan, lastSavedRule, latestCashFlowRows, linkManualRefund, loadData,
    loadRefundPicker, missingCategoryCountByAccount, missingCategoryTransactions, monthlyAllocationEditor, navigateToView, netIncomeCents,
    netWorthAccounts, netWorthPeek, newCategoryLabel, newCategoryParentId, openAccountView,
    openImportModal, openNetWorthPeek, openSplitEditor, openTransactionEditor, openTransactionPeek, openTransactionView, operations,
    pagedTransactions, peekDrawer, pendingRuleTransaction, periodCashFlowRows, periodCategoryTotals, previewHistorySignCleanup, previewRows,
    previewRule, previewSelectedImport, refundPicker, refundSearchTimer, refundSuggestionByTransactionId,
    refundSuggestions, rejectRefundSelections, rejectRefundSuggestion, rejectTransferCandidate, rememberImportSignConvention, removeMonthlyAllocation, replacementCandidate,
    reportExpenseCents, reportIncomeCents, reportNetCents, reportPeriod, repositoryTransactionIds, requestBulkAccountDelete,
    requestBulkHoldingDelete, requestBulkTransactionDelete, requestDelete, resetAccountSelectionAnchor, resetHoldingSelectionAnchor, resetTransactionSelectionAnchor,
    restoreAppExport, restoreDeletedTransaction, restoreSelectedTransactions, reviewCount, reviewQueueFilter, reviewQueueTransactions,
    reviewTransactions, ruleFeedback, rules, saveAccount, saveManualNetWorthSnapshot,
    saveMonthlyAllocation, saveRuleEdit, saveRuleFromTransaction, saveSplits, saveTaxonomyOverride, savingsRate,
    scanImportInbox, scrollToUncategorized, searchRefundPicker, selectAllMatchingTransactions, selectedAccount, selectedAccountId,
    selectedAccountIds, selectedFile, selectedHoldingIds, selectedRepositoryTransactionIds, selectedTransactionAccountFilters, selectedTransactionCategoryFilters,
    selectedTransactionIds, selectedTransactionMonthFilters, selectedTransactionYearFilters, selectedVisibleAccountIds, selectedVisibleReviewIds, setAccountForm,
    setAccountStatus, setActiveTab, setAppImportFile, setBulkEditField, setBulkEditValue, setBulkEditorOpen,
    setBulkReviewCategoryId, setBulkReviewType, setCategorizedHistoryFile, setCategorizedHistoryFilename, setCategorizedHistoryRows, setCategorizedHistorySignConvention,
    setCategoryEditor, setCategoryReassignId, setDashboardCustomizeOpen, setDeleteConfirmText, setDeleteTarget, setEditingCategoryId,
    setEditingCategoryLabel, setEditingCategoryParentId, setEditingRule, setGenericCsvMapping, setHistoryCleanupConfirm, setImportModalOpen,
    setCreateSeparateReplacement, setImportPreview, setImportSignConvention, setImportWorkspaceTab, setMonthlyAllocationEditor, setNetWorthPeek, setNewCategoryLabel,
    setNewCategoryParentId, setPeekDrawer, setRefundPicker, setReportPeriod, setReviewQueueFilter, setSelectedAccountId,
    setSelectedAccountIds, setSelectedHoldingIds, setSelectedTransactionAccountFilters, setSelectedTransactionCategoryFilters, setSelectedTransactionIds, setSelectedTransactionMonthFilters, setSelectedTransactionTypeFilters,
    setSelectedTransactionYearFilters, setSettingsTab, setShowAssetTransactions, setSplitEditor, setTaxonomyAccountId, setTaxonomyEditorOpen,
    setPendingRuleTransaction, setTaxonomyGroupDraft, setToast, setTransactionAmountMax, setTransactionAmountMin, setTransactionDateFrom, setTransactionDateTo,
    setTransactionDirection, setTransactionHasRefund, setTransactionPage, setTransactionSearch, setTransactionView, settingsTab,
    settleRefundsWithoutExpense, showAssetTransactions, showToast, sidebarTaxonomyTree, sidebarWidth, sortIndicator,
    splitEditor, startSidebarResize, taxonomyAccountId, taxonomyEditorOpen, taxonomyGroupDraft, taxonomyOverrides, createSeparateReplacement,
    taxonomyTree, toast, toggleAccountSelection, toggleDashboardWidget, toggleHoldingSelection, toggleOperationDetail,
    toggleTaxonomyGroup, toggleTransactionSelection, toggleTransactionSort, totalExpenseCents, totalIncomeCents,
    transactionCategoryOptions, transactionDateFrom, transactionDateTo, transactionFilterChips, transactionHasRefund,
    transactionPageCount, transactionSearch, transactionSummaryFilter, transactionView, transactionYears, transactions,
    transferCandidates, uncategorizedRefunds, undoLoggedOperation, unlinkRefund, updateCategorizedHistoryRow, updateCategory,
    updateHoldingDescription, updateTransaction, visibleReviewIds, visibleReviewTransactions,
  };
}

export type FinanceController = ReturnType<typeof useFinanceController>;

function suggestedRuleText(description: string) {
  const cleaned = description.replace(/[^a-zA-Z0-9\s*&]/g, " ").replace(/\s+/g, " ").trim();
  return cleaned.split(" ").slice(0, 3).join(" ").toUpperCase() || description.slice(0, 40).toUpperCase();
}
