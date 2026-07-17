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
  RefreshCw,
  RotateCcw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { api as rawApi, apiUrl, bumpTransactionsVersion, getTransactionsVersion, parseApiJson, readableApiError, subscribeTransactionsVersion } from "../api/client";
import { useApiClient } from "../api/hooks";
import { readAppRoute, routeUrl, type RouteView } from "./router";
import { BulkActionBar, CashFlowGraphic, DrillDownLink, MultiSelectFilter, PanelTitle, UndoToast } from "../components/AppPrimitives";
import { DateRangePicker } from "../components/DateRangePicker";
import { DeleteConfirmInline, type DeleteTarget } from "../components/DeleteConfirmInline";
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
import { PostCategorizationRulePrompt } from "../features/rules/PostCategorizationRulePrompt";
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
  { id: "all-accounts", label: "All Transactions", icon: Landmark },
  { id: "review", label: "Review", icon: ListChecks },
  { id: "history", label: "Activity", icon: History },
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

async function loadCategoryAggregates(period: ReportPeriod): Promise<CategoryTotal[]> {
  const filter = { ...reportPeriodFilter(period), dateBasis: "reporting" as const, types: ["expense", "refund"] };
  const rows = await rawApi<CategoryAggregateRow[]>(aggregatePath("by-category", filter));
  return rows.map((row) => ({ ...row, amount_cents: Math.abs(row.total_cents) })).sort((left, right) => right.amount_cents - left.amount_cents || left.category.localeCompare(right.category));
}

async function loadCashFlowAggregates(): Promise<MonthlyCashFlow[]> {
  const [incomeRows, expenseRows] = await Promise.all([
    rawApi<AggregateRow[]>(aggregatePath("timeseries", { types: ["income"] }, "month")),
    rawApi<AggregateRow[]>(aggregatePath("timeseries", { types: ["expense", "refund"] }, "month")),
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

import type { FinanceController } from "./useFinanceController";

export function FinanceWorkspaceView({ controller }: { controller: FinanceController }) {
  if (!("accountForm" in controller)) return controller;
  const {
    accountForm, accountIds, accountNeedingTaxonomy, accountTransactionsVisible, accounts,
    activeAccounts, activeTab, activeView, allRepositoryTransactionsSelected, allocationRows, analyzeSelectedImport,
    analyzedAccount, appImportFile, applyHistorySignCleanup, applyRule, applyRuleToTransaction, applySavedRule,
    beginEditAccount, bulkConfirmSelectedReviewTransactions, bulkEditField, bulkEditValue, bulkEditorOpen, bulkReviewCategoryId,
    bulkReviewType, bulkSaveRulesForSelectedReviewTransactions, bulkUpdateSelectedTransactions, busyAction, cashFlowRows, categories,
    categorizedHistoryFile, categorizedHistoryMissingFields, categorizedHistoryRows, categorizedHistorySignConvention, categorizeTransaction, categoryEditor, categoryReassignId,
    categorySuggestions, chooseImportFile, cleanupImportedAccounts, clearAccountForm, clearTaxonomyOverride, collapsedTaxonomyGroups,
    commitReviewedCategorizedHistory, commitSelectedImport, confirmDelete, confirmInboxBatch, confirmRefundSelections, confirmRefundSuggestion,
    confirmStatementBalanceBatch, confirmTransaction, confirmTransactionEdit, confirmTransferCandidate, createAccountFromAnalysis, createCategory,
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
    refundSuggestions, rejectRefundSelections, rejectRefundSuggestion, rejectTransferCandidate, rememberImportSignConvention, removeMonthlyAllocation,
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
    setImportPreview, setImportSignConvention, setImportWorkspaceTab, setMonthlyAllocationEditor, setNetWorthPeek, setNewCategoryLabel,
    setNewCategoryParentId, setPeekDrawer, setRefundPicker, setReportPeriod, setReviewQueueFilter, setSelectedAccountId,
    setSelectedAccountIds, setSelectedHoldingIds, setSelectedTransactionAccountFilters, setSelectedTransactionCategoryFilters, setSelectedTransactionIds, setSelectedTransactionMonthFilters, setSelectedTransactionTypeFilters,
    setSelectedTransactionYearFilters, setSettingsTab, setShowAssetTransactions, setSplitEditor, setTaxonomyAccountId, setTaxonomyEditorOpen,
    setPendingRuleTransaction, setTaxonomyGroupDraft, setToast, setTransactionAmountMax, setTransactionAmountMin, setTransactionDateFrom, setTransactionDateTo,
    setTransactionDirection, setTransactionHasRefund, setTransactionPage, setTransactionSearch, setTransactionView, settingsTab,
    settleRefundsWithoutExpense, showAssetTransactions, showToast, sidebarTaxonomyTree, sidebarWidth, sortIndicator,
    splitEditor, startSidebarResize, taxonomyAccountId, taxonomyEditorOpen, taxonomyGroupDraft, taxonomyOverrides,
    taxonomyTree, toast, toggleAccountSelection, toggleDashboardWidget, toggleHoldingSelection, toggleOperationDetail,
    toggleTaxonomyGroup, toggleTransactionSelection, toggleTransactionSort, totalExpenseCents, totalIncomeCents,
    transactionCategoryOptions, transactionDateFrom, transactionDateTo, transactionFilterChips, transactionHasRefund,
    transactionPageCount, transactionSearch, transactionView, transactionYears, transactions,
    transferCandidates, uncategorizedRefunds, undoLoggedOperation, unlinkRefund, updateCategorizedHistoryRow, updateCategory,
    updateHoldingDescription, updateTransaction, visibleReviewIds, visibleReviewTransactions,
  } = controller;

  const focusedAccountTransactionsForSummary = focusedAccount
    ? transactions.filter((transaction) => transaction.account_id === focusedAccount.id)
    : [];
  const now = new Date();
  const currentMonthStart = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
  const previousMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const previousMonthStart = `${previousMonth.getFullYear()}-${String(previousMonth.getMonth() + 1).padStart(2, "0")}-01`;
  const focusedRefundsCents = focusedAccountTransactionsForSummary
    .filter((transaction) => transaction.transaction_type === "refund" && transaction.transaction_date >= previousMonthStart && transaction.transaction_date < currentMonthStart)
    .reduce((sum, transaction) => sum + Math.abs(transaction.amount_cents), 0);
  const focusedRefundSuggestions = focusedAccount
    ? refundSuggestions.filter((suggestion) => suggestion.refund_transaction.account_id === focusedAccount.id)
    : [];
  const focusedSpendByMonth = new Map<string, number>();
  focusedAccountTransactionsForSummary
    .filter((transaction) => transaction.transaction_type === "expense")
    .forEach((transaction) => {
      const month = transaction.transaction_date.slice(0, 7);
      focusedSpendByMonth.set(month, (focusedSpendByMonth.get(month) ?? 0) + Math.abs(transaction.amount_cents));
    });
  const focusedAverageMonthlySpendCents = focusedSpendByMonth.size > 0
    ? Math.round(Array.from(focusedSpendByMonth.values()).reduce((sum, amount) => sum + amount, 0) / focusedSpendByMonth.size)
    : 0;

  function clearTransactionFilters() {
    setSelectedTransactionAccountFilters(accounts.map((account) => account.id));
    setSelectedTransactionMonthFilters(monthOptions.map((month) => month.value));
    setSelectedTransactionYearFilters(transactionYears);
    setSelectedTransactionCategoryFilters(transactionCategoryOptions.map((option) => option.value));
    setSelectedTransactionTypeFilters([]);
    setTransactionDateFrom("");
    setTransactionDateTo("");
    setTransactionAmountMin(undefined);
    setTransactionAmountMax(undefined);
    setTransactionDirection(undefined);
    setTransactionHasRefund(false);
    setTransactionSearch("");
    setTransactionView("live");
  }

  function renderTransactionFilters(includeAccounts: boolean) {
    return <div className="transactionFilterRow compactTransactionFilters">
      {transactionFilterChips.length > 0 ? <div className="transactionFilterChips inlineFilterChips" aria-label="Active transaction filters">
        {transactionFilterChips.map((chip) => <button type="button" key={chip.key} onClick={chip.onRemove} title={`Remove ${chip.label} filter`}><span>{chip.label}</span><X size={12} /></button>)}
      </div> : null}
      {includeAccounts ? <MultiSelectFilter
        label="Accounts"
        options={accounts.map((account) => ({ value: String(account.id), label: account.display_name }))}
        selectedValues={selectedTransactionAccountFilters.map(String)}
        onToggle={(value) => setSelectedTransactionAccountFilters((current) => toggleValue(current, Number(value)))}
        onSelectAll={() => setSelectedTransactionAccountFilters(accounts.map((account) => account.id))}
        onDeselectAll={() => setSelectedTransactionAccountFilters([])}
      /> : null}
      {includeAccounts ? <MultiSelectFilter
        label="Months"
        options={monthOptions}
        selectedValues={selectedTransactionMonthFilters}
        onToggle={(value) => setSelectedTransactionMonthFilters((current) => toggleValue(current, value))}
        onSelectAll={() => setSelectedTransactionMonthFilters(monthOptions.map((month) => month.value))}
        onDeselectAll={() => setSelectedTransactionMonthFilters([])}
      /> : null}
      {includeAccounts ? <MultiSelectFilter
        label="Years"
        options={transactionYears.map((year) => ({ value: year, label: year }))}
        selectedValues={selectedTransactionYearFilters}
        onToggle={(value) => setSelectedTransactionYearFilters((current) => toggleValue(current, value))}
        onSelectAll={() => setSelectedTransactionYearFilters(transactionYears)}
        onDeselectAll={() => setSelectedTransactionYearFilters([])}
      /> : null}
      <MultiSelectFilter
        label="Categories"
        options={transactionCategoryOptions}
        selectedValues={selectedTransactionCategoryFilters}
        onToggle={(value) => setSelectedTransactionCategoryFilters((current) => toggleValue(current, value))}
        onSelectAll={() => setSelectedTransactionCategoryFilters(transactionCategoryOptions.map((category) => category.value))}
        onDeselectAll={() => setSelectedTransactionCategoryFilters([])}
      />
      <DateRangePicker dateFrom={transactionDateFrom} dateTo={transactionDateTo} onApply={(range) => { setTransactionDateFrom(range.dateFrom); setTransactionDateTo(range.dateTo); }} />
      <button type="button" className={transactionHasRefund ? "filterToggle active" : "filterToggle"} onClick={() => setTransactionHasRefund((current) => !current)}>↩ Has refund</button>
      <button type="button" className="filterToggle clearFiltersButton" onClick={clearTransactionFilters}><RotateCcw size={14} />Clear filters</button>
      <button type="button" className={transactionView === "trash" ? "filterToggle trashFilterToggle active" : "filterToggle trashFilterToggle"} aria-pressed={transactionView === "trash"} onClick={() => setTransactionView((current) => current === "trash" ? "live" : "trash")}>{transactionView === "trash" ? <X size={13} /> : <Trash2 size={13} />}Trash</button>
    </div>;
  }

  function renderPostCategorizationPrompt() {
    if (!pendingRuleTransaction) return null;
    return <PostCategorizationRulePrompt
      transaction={pendingRuleTransaction}
      categories={categories}
      transactionTypes={transactionTypes}
      onSave={(draft) => saveRuleFromTransaction(pendingRuleTransaction, draft)}
      onApplyExisting={(ruleId) => applyRule(ruleId, "all")}
      onDismiss={() => setPendingRuleTransaction(null)}
    />;
  }

  return (
    <div className="appFrame" style={{ "--sidebar-width": `${sidebarWidth}px` } as CSSProperties}>
      <aside className="sidebar">
        <div className="brandBlock">
          <span className="brandMark"><Landmark size={16} /></span>
          <strong>Private Finance</strong>
        </div>
        <PrimaryNav items={primaryNavItems} activeView={activeView} reviewCount={reviewCount} onNavigate={navigateToView} />
        <AccountNav sections={sidebarTaxonomyTree} collapsed={collapsedTaxonomyGroups} activeAccountId={activeView === "account" ? focusedAccountId : null} missingCategoryCountByAccount={missingCategoryCountByAccount} formatMoney={formatMoney} balanceLabel={sidebarBalanceLabel} onToggle={toggleTaxonomyGroup} onOpenAccount={openAccountView} />
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
                    {accountOptionLabel(account)}
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
          <button className={activeView === "settings" ? "navItem sidebarUtilityNav active" : "navItem sidebarUtilityNav"} onClick={() => navigateToView("settings")}>
            <Settings size={16} />
            <span>Settings</span>
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

      <main className={activeView === "settings" ? "workspace settingsWorkspaceView" : "workspace"}>
        {toast ? (
          <UndoToast toast={toast} busy={busyAction === `undo-${toast.operationId}`} onUndo={(operationId, unconflictedOnly) => void undoLoggedOperation(operationId, unconflictedOnly)} onAction={toast.action ? () => void applyRuleToTransaction(toast.action!.ruleId, toast.action!.transactionId) : undefined} onDismiss={() => setToast(null)} />
        ) : null}

        {activeView === "settings" ? (
          <SettingsNavigation
            active={settingsTab}
            onSelect={(tab) => {
              setSettingsTab(tab);
              if (tab === "imports") setImportWorkspaceTab("smart");
              if (tab === "accounts") setImportWorkspaceTab("manual");
            }}
          />
        ) : null}

        {activeView === "overview" && (
          <>
            <OverviewTabs activeTab={activeTab} reportPeriod={reportPeriod} periodOptions={reportPeriodOptions} onSelectTab={setActiveTab} onSelectPeriod={setReportPeriod} onRefresh={() => void loadData()} onImport={openImportModal} />

            <section className="metricsGrid overviewMetrics" aria-label="Financial summary">
              <DrillDownLink filter={{ ...reportPeriodFilter(reportPeriod), types: ["income"] }} title="Income" onPeek={openTransactionPeek}><MetricTile label="Income" value={formatMoney(cashFlowRows.length > 0 ? reportIncomeCents : totalIncomeCents)} tone="green" /></DrillDownLink>
              <DrillDownLink filter={{ ...reportPeriodFilter(reportPeriod), types: ["expense", "refund"] }} title="Expenses" onPeek={openTransactionPeek}><MetricTile label="Expenses" value={formatMoney(cashFlowRows.length > 0 ? reportExpenseCents : totalExpenseCents)} tone="red" /></DrillDownLink>
              <DrillDownLink filter={{ ...reportPeriodFilter(reportPeriod), types: ["income", "expense", "refund"] }} title="Net cash flow" onPeek={openTransactionPeek}><MetricTile label="Net" value={formatMoney(cashFlowRows.length > 0 ? reportNetCents : netIncomeCents)} tone="neutral" /></DrillDownLink>
              <DrillDownLink filter={{ ...reportPeriodFilter(reportPeriod), types: ["income", "expense", "refund"] }} title="Savings-rate transactions" onPeek={openTransactionPeek}><MetricTile label="Savings rate" value={`${savingsRate}%`} tone="neutral" /></DrillDownLink>
            </section>

            {activeTab === "Overview" ? (
              <>
                <section className="dashboardControls overviewTools">
                  <div>
                    <span className="eyebrow">At a glance</span>
                    <h2>Your finance cockpit</h2>
                    <p>Keep the high-level cards that help you understand your overall financial position.</p>
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

                <section className="dashboardWidgetGrid overviewTools" aria-label="Overview cards">
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

              {dashboardWidgets.spending ? (
                <article className="dashboardWidget">
                  <div className="widgetHeader">
                    <span className="eyebrow">Top spending</span>
                    <strong>{periodCategoryTotals.length}</strong>
                  </div>
                  <div className="miniRankList">
                    {periodCategoryTotals.slice(0, 4).map((row) => (
                      <DrillDownLink key={row.category} filter={{ ...reportPeriodFilter(reportPeriod), dateBasis: "reporting", categories: [row.category_id === null ? uncategorizedFilterValue : String(row.category_id)], types: ["expense", "refund"], sort: "amount", sortDirection: "desc" }} title={`${row.category} spending`} count={row.count} onPeek={openTransactionPeek}>
                        <span>{row.category}</span>
                        <strong>{formatMoney(row.amount_cents)}</strong>
                      </DrillDownLink>
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
                      <DrillDownLink key={row.month} filter={{ months: [row.month.slice(5, 7)], years: [row.month.slice(0, 4)], types: ["income", "expense", "refund"] }} title={`${row.month} cash flow`} onPeek={openTransactionPeek}>
                        <span>{row.month}</span>
                        <strong className={row.net_cents < 0 ? "amount negative" : "amount positive"}>{formatMoney(row.net_cents)}</strong>
                      </DrillDownLink>
                    ))}
                    {latestCashFlowRows.length === 0 ? <p className="emptyText">Import transactions to build a monthly trend.</p> : null}
                  </div>
                </article>
              ) : null}

                </section>
              </>
            ) : null}

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
                  allAccounts={activeAccounts}
                  allocationRows={allocationRows}
                  holdingRows={holdingRows}
                  csrf={csrf}
                  categories={categories}
                  selectedHoldingIds={selectedHoldingIds}
                  deleteTarget={deleteTarget}
                  deleteConfirmText={deleteConfirmText}
                  onToggleHoldingSelection={toggleHoldingSelection}
                  onRequestBulkHoldingDelete={requestBulkHoldingDelete}
                  onClearHoldingSelection={() => {
                    setSelectedHoldingIds([]);
                    resetHoldingSelectionAnchor();
                  }}
                  onUpdateHoldingDescription={updateHoldingDescription}
                  onSaveManualNetWorthSnapshot={saveManualNetWorthSnapshot}
                  onFinanceMutation={async (operationId, message) => { await loadData(); showToast({ tone: "success", message, operationId }); }}
                  onFinanceError={(message) => showToast({ tone: "error", message })}
                  reportFilter={reportPeriodFilter(reportPeriod)}
                  onOpenTransactionView={openTransactionView}
                  onOpenTransactionPeek={openTransactionPeek}
                  onOpenNetWorthPeek={openNetWorthPeek}
                  onOpenAccount={openAccountView}
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
                            <strong>{readableAccountType(change.entity_type)} row {change.entity_id}</strong>
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
          <AccountPage
            account={focusedAccount}
            balanceCents={focusedAccountBalanceCents}
            refundsCents={focusedRefundsCents}
            averageMonthlySpendCents={focusedAverageMonthlySpendCents}
            missingCategoryCount={focusedMissingCategoryCount}
            suggestedRefundCount={focusedRefundSuggestions.length}
            uncategorizedActive={selectedTransactionCategoryFilters.length === 1 && selectedTransactionCategoryFilters[0] === uncategorizedFilterValue}
            reconciliation={focusedReconciliation}
            paymentVerification={focusedPaymentVerification}
            csrf={csrf}
            transactionAccounts={importableAccounts}
            transactionCategories={categories}
            externalAccounts={externalAccounts}
            formatMoney={formatMoney}
            readableAccountType={readableAccountType}
            onImport={() => openImportModal(focusedAccount.id)}
            onRefresh={() => void loadData()}
            onViewUncategorized={scrollToUncategorized}
            onCheckpointSaved={async (operationId) => { await loadData(); showToast({ tone: "success", message: "Statement balance saved and checked against the ledger.", operationId }); }}
            onManualTransactionSaved={async (operationId) => { await loadData(); showToast({ tone: "success", message: "Manual transaction added.", operationId }); }}
            onCheckpointError={(message) => showToast({ tone: "error", message })}
            onInvestigateReconciliation={investigateReconciliation}
            onInvestigatePayment={investigatePayment}
            onPaymentDismissed={async (operationId) => { await loadData(); showToast({ tone: "success", message: "Payment warning dismissed.", operationId }); }}
            onAccountChanged={async (operationId, message) => { await loadData(); showToast({ tone: "success", message, operationId }); }}
            transactionsCollapsed={focusedAccountIsAsset && !showAssetTransactions}
            onToggleTransactions={focusedAccountIsAsset ? () => setShowAssetTransactions((current) => !current) : undefined}
            holdings={focusedAccountIsAsset ? <>
              {deleteTarget?.kind === "holding" || deleteTarget?.kind === "holding_bulk" ? <DeleteConfirmInline target={deleteTarget} confirmText={deleteConfirmText} onConfirmTextChange={setDeleteConfirmText} onConfirm={confirmDelete} onCancel={() => { setDeleteTarget(null); setDeleteConfirmText(""); }} /> : null}
              <HoldingsPanel rows={focusedHoldingRows} accounts={[focusedAccount]} csrf={csrf} selectedIds={selectedHoldingIds} formatMoney={formatMoney} formatDate={formatShortDate} onToggleSelection={toggleHoldingSelection} onRequestBulkDelete={requestBulkHoldingDelete} onClearSelection={() => { const ids = new Set(focusedHoldingRows.map((row) => row.id)); setSelectedHoldingIds((current) => current.filter((id) => !ids.has(id))); resetHoldingSelectionAnchor(); }} onUpdateDescription={updateHoldingDescription} onRequestDelete={(row) => requestDelete({ kind: "holding", id: row.id, label: `${row.symbol || row.description || "Holding"} in ${row.account}` })} onLotSaved={async (operationId) => { await loadData(); showToast({ tone: "success", message: "Tax lot updated; basis and gain/loss refreshed.", operationId }); }} onError={(message) => showToast({ tone: "error", message })} />
            </> : undefined}
            suggestedRefunds={<RefundSuggestions
              suggestions={focusedRefundSuggestions}
              busy={busyAction}
              onDetect={() => void detectRefunds()}
              onConfirm={(suggestion, candidate) => void confirmRefundSuggestion(suggestion, candidate)}
              onReject={(suggestion, candidate) => void rejectRefundSuggestion(suggestion, candidate)}
              onBulkConfirm={(selections) => void confirmRefundSelections(selections)}
              onBulkReject={(selections) => void rejectRefundSelections(selections)}
              onNoExpense={(refundIds) => void settleRefundsWithoutExpense(refundIds)}
            />}
          />
        ) : null}

        {activeView === "all-accounts" ? (
          <div className="stickyAccountChrome">
            <header className="accountLedgerHeader">
              <div>
                <h1>All Transactions</h1>
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
          </div>
        ) : null}

        {(activeView === "review" || (activeView === "settings" && (settingsTab === "imports" || settingsTab === "accounts" || settingsTab === "categories"))) && (
        <section className={activeView === "review" ? "workGrid viewSection reviewWorkspace" : "workGrid viewSection settingsWorkspace"}>
          {activeView === "settings" && (settingsTab === "imports" || settingsTab === "accounts") ? (
          <section className="toolPanel importWorkspace">
            <PanelTitle icon={FileUp} title="Import & Accounts" subtitle="Start with a CSV. The app will match an account or prefill one for your review." />
            <div className="workspaceTabs">
              <button className={importWorkspaceTab === "smart" ? "workspaceTab active" : "workspaceTab"} onClick={() => { setImportWorkspaceTab("smart"); setSettingsTab("imports"); }}>
                Smart import
              </button>
              <button className={importWorkspaceTab === "manual" ? "workspaceTab active" : "workspaceTab"} onClick={() => { setImportWorkspaceTab("manual"); setSettingsTab("accounts"); }}>
                Manual accounts
              </button>
            </div>

            {importWorkspaceTab === "smart" ? (
              <>
                <ImportReview
                  inbox={importInbox}
                  lastScan={lastInboxScan}
                  busyAction={busyAction}
                  onScan={() => void scanImportInbox()}
                  onConfirm={(batch) => void confirmInboxBatch(batch)}
                  onConfirmStatement={confirmStatementBalanceBatch}
                  onDiscard={(batch) => void discardInboxBatch(batch)}
                />
                <ImportMetadataPanel />
                <div className="historyImportPanel">
                  <div>
                    <strong>Categorized history import</strong>
                    <span>Upload an older categorized spreadsheet. Expected columns: Account, Posted Date, Payee, Amount, and Expense Category. Choose the spreadsheet's original sign convention before importing.</span>
                  </div>
                  <label>Historical amount convention
                    <select value={categorizedHistorySignConvention} onChange={(event) => setCategorizedHistorySignConvention(event.target.value as HistorySignConvention)}>
                      <option value="charges_positive">Charges are positive; refunds are negative (your cleaned history)</option>
                      <option value="canonical">Charges are already negative; refunds are positive</option>
                    </select>
                  </label>
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
                <div className="cleanupPanel historySignCleanup">
                  <div>
                    <strong>Normalize previously imported categorized history</strong>
                    <span>Preview a one-time cleanup that makes charges negative, refunds positive, and corrects Venmo to a cash account. The result is recorded as one undoable Activity operation.</span>
                  </div>
                  <button className="secondaryButton" onClick={() => void previewHistorySignCleanup()} disabled={busyAction !== null}>
                    <Sparkles size={16} />
                    Preview cleanup
                  </button>
                </div>
                {historyCleanupPreview ? (
                  <div className="historyCleanupPreview">
                    <div className="previewMeta">
                      <strong>{historyCleanupPreview.candidate_transactions} transactions</strong>
                      <span>{historyCleanupPreview.charges_to_normalize} charges · {historyCleanupPreview.refunds_to_normalize} refunds · {historyCleanupPreview.income_sign_fixes} income sign fixes</span>
                    </div>
                    {historyCleanupPreview.possible_duplicate_account_pairs.length > 0 ? (
                      <div className="historyCleanupWarnings" role="status">
                        <AlertCircle size={18} />
                        <div>
                          <strong>Possible duplicate account names found</strong>
                          {historyCleanupPreview.possible_duplicate_account_pairs.map((pair) => (
                            <span key={`${pair.left_account_id}-${pair.right_account_id}`}>
                              {pair.left_account}{pair.left_last_four ? ` (${pair.left_last_four})` : ""} and {pair.right_account}{pair.right_last_four ? ` (${pair.right_last_four})` : ""} share {pair.matching_transactions} historical transactions ({pair.overlap_percent}% overlap). Normalizing signs is safe, but these accounts should be merged separately so totals are not counted twice.
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {historyCleanupPreview.source_boundary_warnings.length > 0 ? (
                      <div className="historyCleanupWarnings" role="status">
                        <AlertCircle size={18} />
                        <div>
                          <strong>Direct CSV dates overlap historical dates</strong>
                          {historyCleanupPreview.source_boundary_warnings.map((warning) => (
                            <span key={warning.account_id}>{warning.account}{warning.last_four ? ` (${warning.last_four})` : ""} has {warning.direct_rows_on_or_before_history} direct-import rows on or before its historical cutoff. They will not be changed, but should be reviewed for duplicates.</span>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {historyCleanupPreview.possible_direct_import_duplicates.length > 0 ? (
                      <div className="historyCleanupWarnings" role="status">
                        <AlertCircle size={18} />
                        <div>
                          <strong>Possible duplicate direct CSV rows found</strong>
                          {historyCleanupPreview.possible_direct_import_duplicates.map((warning) => (
                            <span key={warning.account_id}>{warning.account}{warning.last_four ? ` (${warning.last_four})` : ""} has {warning.possible_duplicate_rows} repeated bank reference {warning.possible_duplicate_rows === 1 ? "number" : "numbers"}. These rows will not be changed by sign normalization and should be deduplicated separately.</span>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {historyCleanupPreview.accounts.map((account) => (
                      <div className="matchedAccountCard" key={account.account_id}>
                        <Landmark size={16} />
                        <div>
                          <strong>{account.account}{account.last_four ? ` (${account.last_four})` : ""}</strong>
                          <span>{account.transactions} transactions · {formatMoney(account.gross_cents)} reviewed{account.current_account_type !== account.next_account_type ? ` · account type ${account.current_account_type.replaceAll("_", " ")} → ${account.next_account_type}` : ""}</span>
                          <span>Historical file: {formatShortDate(account.history_from)}–{formatShortDate(account.history_through)} · Direct CSV: {account.direct_rows ? `${formatShortDate(account.direct_from)}–${formatShortDate(account.direct_through)} (${account.direct_rows_after_history} after cutoff)` : "none"}</span>
                        </div>
                      </div>
                    ))}
                    {historyCleanupPreview.candidate_transactions > 0 ? (
                      <div className="cleanupConfirmRow">
                        <input value={historyCleanupConfirm} onChange={(event) => setHistoryCleanupConfirm(event.target.value)} placeholder='Type NORMALIZE' />
                        <button className="primaryButton" onClick={() => void applyHistorySignCleanup()} disabled={historyCleanupConfirm.trim().toUpperCase() !== historyCleanupPreview.confirmation_text}>Apply undoable cleanup</button>
                      </div>
                    ) : <p className="emptyText">No legacy transactions need this cleanup.</p>}
                  </div>
                ) : null}
                <div className="compactForm">
                  <input type="file" accept=".csv,.ofx,.qfx,.pdf,text/csv,application/pdf" onChange={(event) => chooseImportFile(event.target.files?.[0] ?? null)} />
                  <div className="buttonRow">
                    <button className="secondaryButton" onClick={() => void analyzeSelectedImport()}>
                      <Sparkles size={16} />
                      Analyze file
                    </button>
                    <button className="secondaryButton" onClick={() => void previewSelectedImport()} disabled={!selectedAccountId || !selectedFile || busyAction !== null}>
                      <Search size={16} />
                      Preview
                    </button>
                    <button className="primaryButton" onClick={() => void commitSelectedImport()} disabled={!selectedAccountId || !selectedFile || !importPreview || busyAction !== null}>
                      <ArrowDownToLine size={16} />
                      Stage for review
                    </button>
                  </div>
                </div>

                {importAnalysis ? (
                  <div className="analysisPanel">
                    <div className="analysisHeader">
                      <div>
                        <strong>{importAnalysis.preset_type ?? "Custom CSV mapping"}</strong>
                        <span>{importAnalysis.reason}</span>
                      </div>
                      <span className="statusBadge suggested">{importAnalysis.suggested_account_id ? `${importAnalysis.match_confidence}% match` : "Needs review"}</span>
                    </div>
                    {importAnalysis.preset_type === null ? (
                      <div className="genericMappingPanel">
                        <span className="eyebrow">Map columns</span>
                        <p>Tell the app which columns contain the transaction date, description, and amount. Matching headers are remembered on this browser.</p>
                        <div className="genericMappingGrid">
                          {(["date", "description", "amount"] as const).map((field) => (
                            <label key={field}>{field[0].toUpperCase() + field.slice(1)}
                              <select value={genericCsvMapping[field]} onChange={(event) => setGenericCsvMapping((current) => ({ ...current, [field]: event.target.value }))}>
                                <option value="">Choose column</option>
                                {(importAnalysis.headers ?? []).map((header) => <option key={header} value={header}>{header}</option>)}
                              </select>
                            </label>
                          ))}
                        </div>
                        <small>Review the preview before staging. Use the Amount signs control below if this CSV's convention needs to be reversed.</small>
                      </div>
                    ) : analyzedAccount ? (
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
                    ) : importAnalysis.proposed_account ? (
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
                    ) : null}
                  </div>
                ) : (
                  <p className="emptyText">Choose a CSV and click Analyze. If confidence is high, the app selects the existing account; otherwise it drafts a new account you can edit.</p>
                )}

                <div className="manualOverride">
                  <label>Override account if the match is wrong</label>
                  <select value={selectedAccountId} onChange={(event) => setSelectedAccountId(event.target.value ? Number(event.target.value) : "")}>
                    <option value="">Choose existing account</option>
                    {importableAccounts.map((account) => (
                      <option key={account.id} value={account.id}>
                        {accountOptionLabel(account)}
                      </option>
                    ))}
                  </select>
                </div>

                <SignConventionPrompt
                  value={importSignConvention}
                  decision={importPreview?.sign_decision}
                  disabled={busyAction !== null}
                  onChange={(value) => { setImportSignConvention(value); setImportPreview(null); }}
                  onRemember={(value) => void rememberImportSignConvention(value)}
                />

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
                            <strong>{String(row.amount ?? row.market_value ?? "")}{row.interpreted_transaction_type ? ` · ${String(row.interpreted_transaction_type).replaceAll("_", " ")}` : ""}</strong>
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
                        resetAccountSelectionAnchor();
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
            <a href="#duplicate-review">Duplicates <span>{duplicatePairs.length}</span></a>
            <a href="#transfer-review">Transfers <span>{transferCandidates.length}</span></a>
            <a href="#refund-review">Refunds <span>{refundSuggestions.length}</span></a>
            <a href="#review-inbox">Inbox <span>{reviewTransactions.length}</span></a>
            <a href="#saved-rules">Rules <span>{rules.length}</span></a>
          </nav>
          <LedgerDuplicateScan pairs={duplicatePairs} csrf={csrf} onChanged={async (message, operationId) => { await loadData(); showToast({ tone: "success", message, operationId }); }} onError={(message) => showToast({ tone: "error", message })} onRerunTransfers={detectTransfers} />
          <TransferReview
            candidates={transferCandidates}
            accountName={(accountId) => accounts.find((account) => account.id === accountId)?.display_name ?? `Account ${accountId}`}
            formatDate={formatShortDate}
            formatMoney={formatMoney}
            typeLabel={readableAccountType}
            onDetect={() => void detectTransfers()}
            onConfirm={(candidateId) => void confirmTransferCandidate(candidateId)}
            onReject={(candidateId) => void rejectTransferCandidate(candidateId)}
          />
          <RefundSuggestions
            suggestions={refundSuggestions}
            busy={busyAction}
            onDetect={() => void detectRefunds()}
            onConfirm={(suggestion, candidate) => void confirmRefundSuggestion(suggestion, candidate)}
            onReject={(suggestion, candidate) => void rejectRefundSuggestion(suggestion, candidate)}
            onBulkConfirm={(selections) => void confirmRefundSelections(selections)}
            onBulkReject={(selections) => void rejectRefundSelections(selections)}
            onNoExpense={(refundIds) => void settleRefundsWithoutExpense(refundIds)}
          />

          <section className="toolPanel reviewInboxPanel" id="review-inbox">
            <PanelTitle icon={ListChecks} title="Review Inbox" subtitle={`${reviewTransactions.length} items need a human decision.`} />
            <div className="reviewQueueFilters" role="group" aria-label="Review inbox filters">
              <button type="button" className={reviewQueueFilter === "all" ? "filterToggle active" : "filterToggle"} onClick={() => setReviewQueueFilter("all")}>All review items <span>{reviewQueueTransactions.length}</span></button>
              <button type="button" className={reviewQueueFilter === "uncategorized_refunds" ? "filterToggle active" : "filterToggle"} onClick={() => setReviewQueueFilter("uncategorized_refunds")} disabled={uncategorizedRefunds.length === 0}>Uncategorized refunds <span>{uncategorizedRefunds.length}</span></button>
            </div>
            <label className="transactionSearchBox reviewSearch"><Search size={14} /><input value={transactionSearch} onChange={(event) => setTransactionSearch(event.target.value)} placeholder="Search review transactions" /></label>
            {visibleReviewTransactions.length > 0 ? (
              <div className="selectionToolbar reviewBulkToolbar">
                <span>{selectedVisibleReviewIds.length} selected</span>
                <select value={bulkReviewType} onChange={(event) => { const nextType = event.target.value; setBulkReviewType(nextType); if (!transactionTypeUsesCategory(nextType)) setBulkReviewCategoryId(""); }}>
                  {transactionTypes.map((type) => (
                    <option key={type.value} value={type.value}>
                      {type.label}
                    </option>
                  ))}
                </select>
                <select value={bulkReviewCategoryId} onChange={(event) => setBulkReviewCategoryId(event.target.value ? Number(event.target.value) : "")} disabled={!transactionTypeUsesCategory(bulkReviewType)}>
                  <option value="">{transactionTypeUsesCategory(bulkReviewType) ? "Choose category" : "No category needed"}</option>
                  {categories.map((category) => (
                    <option key={category.id} value={category.id}>
                      {category.label}
                    </option>
                  ))}
                </select>
                <button className="primaryButton" onClick={() => void bulkConfirmSelectedReviewTransactions()} disabled={selectedVisibleReviewIds.length === 0 || (transactionTypeUsesCategory(bulkReviewType) && !bulkReviewCategoryId)}>
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
            {renderPostCategorizationPrompt()}
            <div className="reviewEditor">
              {visibleReviewTransactions.map((transaction) => {
                const refundSuggestion = refundSuggestionByTransactionId.get(transaction.id);
                return (
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
                          <option key={account.id} value={account.id}>{accountOptionLabel(account)}</option>
                        ))}
                      </select>
                      <select
                        value={transaction.transaction_type}
                        onChange={(event) => { const nextType = event.target.value; void categorizeTransaction(transaction, { transaction_type: nextType, ...(transactionTypeUsesCategory(nextType) ? {} : { category_id: null }) }); }}
                      >
                        {transactionTypes.map((type) => (
                          <option key={type.value} value={type.value}>
                            {type.label}
                          </option>
                        ))}
                      </select>
                      <select
                        value={transaction.category_id ?? ""}
                        onChange={(event) => { const categoryId = event.target.value ? Number(event.target.value) : null; if (categoryId === null) { void updateTransaction(transaction.id, { category_id: null }); } else { void categorizeTransaction(transaction, { category_id: categoryId }); } }}
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
                    {transaction.transaction_type === "refund" && refundSuggestion ? <RefundCategorizationNudge suggestion={refundSuggestion} busy={busyAction} formatMoney={formatMoney} onConfirm={(suggestion, candidate) => void confirmRefundSuggestion(suggestion, candidate)} onReject={(suggestion, candidate) => void rejectRefundSuggestion(suggestion, candidate)} /> : null}
                    <div className="reviewActions">
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
              );})}
              {reviewTransactions.length === 0 ? <p className="emptyText">{reviewQueueFilter === "uncategorized_refunds" ? "No uncategorized refunds are waiting." : "No items waiting for review. New imports will appear here before reports rely on them."}</p> : null}
            </div>
          </section>

          <SavedRulesPanel rules={rules} categories={categories} transactionTypes={transactionTypes} lastSavedRule={lastSavedRule} editingRule={editingRule} feedback={ruleFeedback} focusedTransaction={transactions.find((transaction) => transaction.id === focusedTransactionId) ?? null} readableType={readableAccountType} onApplyOne={(ruleId, transactionId) => void applyRuleToTransaction(ruleId, transactionId)} onApplySaved={(scope) => void applySavedRule(scope)} onApply={(ruleId, scope) => void applyRule(ruleId, scope)} onPreview={(ruleId) => void previewRule(ruleId)} onEdit={setEditingRule} onSaveEdit={() => void saveRuleEdit()} onDelete={(rule) => void deleteRule(rule)} />
          </>
          ) : null}

          {activeView === "settings" && settingsTab === "categories" ? (
          <section className="toolPanel categoriesWorkspace">
            <PanelTitle icon={PiggyBank} title="Categories" subtitle="Spending buckets for expense reporting. Add or rename them as your life changes." />
            <div className="compactForm">
              <div className="buttonRow">
                <input value={newCategoryLabel} onChange={(event) => setNewCategoryLabel(event.target.value)} placeholder="New category name" />
                <select value={newCategoryParentId} onChange={(event) => setNewCategoryParentId(event.target.value ? Number(event.target.value) : "")} title="Optional parent category">
                  <option value="">Top-level category</option>
                  {categories.filter((category) => category.parent_id === null).map((category) => <option key={category.id} value={category.id}>Under {category.label}</option>)}
                </select>
                <button className="primaryButton" onClick={() => void createCategory()}>
                  <Plus size={16} />
                  Add
                </button>
              </div>
              {editingCategoryId ? (
                <div className="categoryManagementEditor">
                  <div className="inlineEdit">
                    <input value={editingCategoryLabel} onChange={(event) => setEditingCategoryLabel(event.target.value)} placeholder="Rename category" />
                    <select value={editingCategoryParentId} onChange={(event) => setEditingCategoryParentId(event.target.value ? Number(event.target.value) : "")}>
                      <option value="">Top-level category</option>
                      {categories.filter((category) => category.id !== editingCategoryId && category.parent_id === null).map((category) => <option key={category.id} value={category.id}>Under {category.label}</option>)}
                    </select>
                    <button className="secondaryButton" onClick={() => void updateCategory()}>Save rename</button>
                  </div>
                  <div className="categoryMergeRow">
                    <select value={categoryReassignId} onChange={(event) => setCategoryReassignId(event.target.value ? Number(event.target.value) : "")}>
                      <option value="">No replacement (delete only if unused)</option>
                      {categories.filter((category) => category.id !== editingCategoryId).map((category) => <option key={category.id} value={category.id}>Merge into {category.label}</option>)}
                    </select>
                    <button className="dangerButton" onClick={() => void deleteOrMergeCategory()}>{categoryReassignId ? "Merge and delete" : "Delete unused"}</button>
                    <button className="ghostButton" onClick={() => { setEditingCategoryId(null); setEditingCategoryLabel(""); setEditingCategoryParentId(""); setCategoryReassignId(""); }}>Cancel</button>
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
                    setEditingCategoryParentId(category.parent_id ?? "");
                    setCategoryReassignId("");
                  }}
                >
                  {category.label}
                </button>
              ))}
            </div>
          </section>
          ) : null}
          {activeView === "settings" && settingsTab === "categories" ? (
            <SavedRulesPanel rules={rules} categories={categories} transactionTypes={transactionTypes} lastSavedRule={lastSavedRule} editingRule={editingRule} feedback={ruleFeedback} focusedTransaction={null} readableType={readableAccountType} onApplyOne={(ruleId, transactionId) => void applyRuleToTransaction(ruleId, transactionId)} onApplySaved={(scope) => void applySavedRule(scope)} onApply={(ruleId, scope) => void applyRule(ruleId, scope)} onPreview={(ruleId) => void previewRule(ruleId)} onEdit={setEditingRule} onSaveEdit={() => void saveRuleEdit()} onDelete={(rule) => void deleteRule(rule)} />
          ) : null}
        </section>
        )}

        {(activeView === "all-accounts" || (activeView === "account" && accountTransactionsVisible)) && (
        <section className="ledgerPanel ledgerWorkspace" id={activeView === "account" ? "account-transactions" : "all-transactions"}>
          {activeView === "all-accounts" ? <div className="transactionControlTop">
            {transactionView === "live" ? <div className="transactionModeTabs" role="tablist" aria-label="Transaction views">
            <button type="button" role="tab" aria-selected={!selectedTransactionCategoryFilters.includes(uncategorizedFilterValue)} className={!selectedTransactionCategoryFilters.includes(uncategorizedFilterValue) ? "active" : ""} onClick={() => setSelectedTransactionCategoryFilters(transactionCategoryOptions.map((option) => option.value))}>All transactions</button>
            <button type="button" role="tab" aria-selected="false" onClick={() => navigateToView("review")}>Needs review <span>{reviewCount}</span></button>
            <button type="button" role="tab" aria-selected={selectedTransactionCategoryFilters.length === 1 && selectedTransactionCategoryFilters[0] === uncategorizedFilterValue} className={selectedTransactionCategoryFilters.length === 1 && selectedTransactionCategoryFilters[0] === uncategorizedFilterValue ? "active" : ""} onClick={() => setSelectedTransactionCategoryFilters([uncategorizedFilterValue])}>Uncategorized <span>{missingCategoryTransactions.length}</span></button>
            </div> : <span className="trashResultsLabel">Trash</span>}
            <label className="transactionSearchBox"><Search size={15} /><input value={transactionSearch} onChange={(event) => setTransactionSearch(event.target.value)} placeholder="Search transactions…" /></label>
          </div> : null}
          {renderTransactionFilters(activeView === "all-accounts")}
          {activeView === "account" ? <div className="accountTransactionSearchRow">
            <label className="transactionSearchBox"><Search size={15} /><input value={transactionSearch} onChange={(event) => setTransactionSearch(event.target.value)} placeholder="Search this account’s transactions…" /></label>
          </div> : null}
          <div className="ledgerListToolbar">
            <div className="ledgerSummaryGroup">
              <div className="ledgerSummaryText">
                <strong>{filteredTransactions.length} transaction{filteredTransactions.length === 1 ? "" : "s"}</strong>
                <span>Showing {pagedTransactions.length}{filteredTransactions.length > pagedTransactions.length ? ` of ${filteredTransactions.length}` : ""}</span>
              </div>
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
            <BulkActionBar count={selectedRepositoryTransactionIds.length} detail={`${pagedTransactions.length} shown${filteredTransactions.length > pagedTransactions.length ? ` of ${filteredTransactions.length}` : ""}`} onClear={() => { setSelectedTransactionIds((current) => current.filter((id) => !repositoryTransactionIds.includes(id))); resetTransactionSelectionAnchor(); setBulkEditorOpen(false); }}>
              {transactionView === "live" ? <button className="secondaryButton compactButton" onClick={() => setBulkEditorOpen((current) => !current)}>{bulkEditorOpen ? "Close bulk edit" : "Bulk edit"}</button> : null}
              {transactionView === "live" ? (
                <button className="dangerTextButton" onClick={() => requestBulkTransactionDelete(selectedRepositoryTransactionIds)}>Delete selected</button>
              ) : (
                <>
                  <button className="secondaryButton compactButton" onClick={() => void restoreSelectedTransactions(selectedRepositoryTransactionIds)}>Restore selected</button>
                  <button className="dangerTextButton" onClick={() => requestDelete({ kind: "transaction_bulk_permanent", ids: selectedRepositoryTransactionIds, label: `${selectedRepositoryTransactionIds.length} deleted transactions` })}>Delete forever</button>
                </>
              )}
            </BulkActionBar>
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
                ) : bulkEditField === "date" ? (
                  <input type="date" value={bulkEditValue} onChange={(event) => setBulkEditValue(event.target.value)} />
                ) : (
                  <input value={bulkEditValue} onChange={(event) => setBulkEditValue(event.target.value)} placeholder={`New ${bulkTransactionFields.find((field) => field.value === bulkEditField)?.label.toLowerCase()}`} />
                )}
              </label>
              <div className="bulkEditActions">
                <button className="primaryButton" onClick={() => void bulkUpdateSelectedTransactions()} disabled={!bulkEditValue.trim()}>Apply change</button>
                <button className="ghostButton" onClick={() => { setBulkEditorOpen(false); setBulkEditValue(""); }}>Cancel</button>
              </div>
              {bulkEditField === "institution" ? <small>Institution changes apply to the account records associated with the selected transactions.</small> : null}
              {bulkEditField === "labels" ? <small>Separate labels with commas. Applying the change replaces the selected transactions' existing labels.</small> : null}
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
          {renderPostCategorizationPrompt()}
          <div className="ledgerTable">
            <div className="ledgerHeader">
              <span className="selectAllHeader">
                <input
                  type="checkbox"
                  aria-label={allRepositoryTransactionsSelected ? "Clear transaction selection" : `Select all ${filteredTransactions.length} transactions`}
                  checked={allRepositoryTransactionsSelected}
                  disabled={repositoryTransactionIds.length === 0 || busyAction === "select-all-transactions"}
                  onChange={() => {
                    if (allRepositoryTransactionsSelected) {
                      const repositoryIds = new Set(repositoryTransactionIds);
                      setSelectedTransactionIds((current) => current.filter((id) => !repositoryIds.has(id)));
                    } else {
                      void selectAllMatchingTransactions();
                    }
                  }}
                />
                <small>{busyAction === "select-all-transactions" ? "Selecting…" : "All"}</small>
              </span>
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
              const needsCategory = transactionTypeRequiresCategory(transaction.transaction_type) && !transaction.category_id;
              const categoryLabel = categories.find((category) => category.id === transaction.category_id)?.label;
              const refundSuggestion = refundSuggestionByTransactionId.get(transaction.id);
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
                    {transaction.labels.length > 0 || transaction.split_count > 0 || transaction.monthly_allocation_count > 0 || transaction.refund_total_cents > 0 || transaction.refund_expense_id !== null ? (
                      <div className="transactionLabels">
                        {transaction.labels.map((label) => <span key={label}>#{label}</span>)}
                        {transaction.split_count > 0 ? <span>Split into {transaction.split_count} categories</span> : null}
                        {transaction.monthly_allocation_count > 0 ? <span>Spread across {transaction.monthly_allocation_count} months</span> : null}
                        {transaction.refund_total_cents > 0 ? <span className="refundBadge">↩ refunded {formatMoney(transaction.refund_total_cents)}</span> : null}
                        {transaction.refund_expense_id !== null ? <span className="refundBadge">↩ linked refund</span> : null}
                      </div>
                    ) : null}
                  </div>
                  {isEditing ? (
                    <select
                      className="editableCell"
                      value={transaction.transaction_type}
                      onClick={(event) => event.stopPropagation()}
                      onChange={(event) => { const nextType = event.target.value; void categorizeTransaction(transaction, { transaction_type: nextType, ...(!transactionTypeUsesCategory(nextType) ? { category_id: null } : {}) }); }}
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
                                  void categorizeTransaction(transaction, { category_id: categorySuggestions[0].id });
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
                                    void categorizeTransaction(transaction, { category_id: categoryOption.id });
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
                                  void categorizeTransaction(transaction, { transaction_type: "transfer", category_id: null });
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
                {isEditing && transaction.transaction_type === "refund" && refundSuggestion ? <RefundCategorizationNudge suggestion={refundSuggestion} busy={busyAction} formatMoney={formatMoney} onConfirm={(suggestion, candidate) => void confirmRefundSuggestion(suggestion, candidate)} onReject={(suggestion, candidate) => void rejectRefundSuggestion(suggestion, candidate)} /> : null}
                {isEditing && transaction.transaction_type === "expense" ? (
                  <RefundLinkPicker
                    open={refundPicker?.expenseId === transaction.id}
                    links={refundPicker?.expenseId === transaction.id ? refundPicker.links : []}
                    candidates={refundPicker?.expenseId === transaction.id ? refundPicker.candidates : []}
                    loading={refundPicker?.expenseId === transaction.id ? refundPicker.loading : false}
                    expenseAmountCents={transaction.amount_cents}
                    search={refundPicker?.expenseId === transaction.id ? refundPicker.search : ""}
                    formatMoney={formatMoney}
                    formatDate={formatShortDate}
                    onOpen={() => void loadRefundPicker(transaction.id)}
                    onClose={() => { if (refundSearchTimer.current !== null) window.clearTimeout(refundSearchTimer.current); setRefundPicker(null); }}
                    onSearch={(value) => searchRefundPicker(transaction.id, value)}
                    onLink={(candidate) => void linkManualRefund(transaction, candidate)}
                    onUnlink={(linkId) => void unlinkRefund(transaction.id, linkId)}
                  />
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

        {activeView === "settings" && settingsTab === "data" ? (
          <DataSettings
            csrf={csrf}
            busy={busyAction !== null}
            appImportFile={appImportFile}
            onChooseImport={setAppImportFile}
            onExport={() => void downloadAppExport()}
            onRestoreExport={() => void restoreAppExport()}
            onOpenTrash={() => {
              setTransactionView("trash");
              navigateToView("all-accounts");
            }}
            onChanged={(message) => showToast({ tone: "success", message })}
            onError={(message) => showToast({ tone: "error", message })}
          />
        ) : null}

        {activeView === "settings" && settingsTab === "security" ? (
          <SecuritySettings csrf={csrf} onChanged={(message) => showToast({ tone: "success", message })} onError={(message) => showToast({ tone: "error", message })} />
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
                      {importableAccounts.map((account) => (
                        <option key={account.id} value={account.id}>
                          {accountOptionLabel(account)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <SignConventionPrompt
                    value={importSignConvention}
                    decision={importPreview?.sign_decision}
                    disabled={busyAction !== null}
                    onChange={(value) => { setImportSignConvention(value); setImportPreview(null); }}
                    onRemember={(value) => void rememberImportSignConvention(value)}
                  />
                  <input type="file" accept=".csv,.ofx,.qfx,.pdf,text/csv,application/pdf" onChange={(event) => chooseImportFile(event.target.files?.[0] ?? null)} />
                  <div className="buttonRow">
                    <button className="secondaryButton" onClick={() => void analyzeSelectedImport()} disabled={!selectedFile}>
                      Analyze
                    </button>
                    <button className="secondaryButton" onClick={() => void previewSelectedImport()} disabled={!selectedAccountId || !selectedFile || busyAction !== null}>
                      Preview
                    </button>
                    <button className="primaryButton" onClick={() => void commitSelectedImport()} disabled={!selectedAccountId || !selectedFile || !importPreview || busyAction !== null}>
                      Stage for review
                    </button>
                  </div>
                  {importAnalysis ? (
                    <div className="importSummary">
                      <span>
                        Detected <strong>{importAnalysis.preset_type ?? "custom CSV"}</strong> · {importAnalysis.reason}
                      </span>
                      {analyzedAccount ? <span>Matched account: {analyzedAccount.display_name}</span> : null}
                      {importAnalysis.preset_type === null ? (
                        <div className="genericMappingGrid">
                          {(["date", "description", "amount"] as const).map((field) => (
                            <label key={field}>{field[0].toUpperCase() + field.slice(1)}
                              <select value={genericCsvMapping[field]} onChange={(event) => setGenericCsvMapping((current) => ({ ...current, [field]: event.target.value }))}>
                                <option value="">Choose column</option>
                                {(importAnalysis.headers ?? []).map((header) => <option key={header} value={header}>{header}</option>)}
                              </select>
                            </label>
                          ))}
                        </div>
                      ) : null}
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
                          <span>{String(row.amount ?? "")}{row.interpreted_transaction_type ? ` · ${String(row.interpreted_transaction_type).replaceAll("_", " ")}` : ""}</span>
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
                  <span className="eyebrow">{peekDrawer.eyebrow}</span>
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
                {peekDrawer.rows.length === 0 ? <p className="emptyText">No transactions match this selection.</p> : null}
              </div>
              <footer>
                <button className="primaryButton" onClick={() => {
                  openTransactionView(peekDrawer.filter);
                  setPeekDrawer(null);
                }}>Open full view →</button>
              </footer>
            </aside>
          </div>
        ) : null}
        {netWorthPeek ? (
          <div className="peekBackdrop" onClick={() => setNetWorthPeek(null)}>
            <aside className="peekDrawer assetPeekDrawer" aria-label="Net worth account changes" onClick={(event) => event.stopPropagation()}>
              <header>
                <div>
                  <span className="eyebrow">Asset change peek</span>
                  <h2>{formatShortDate(netWorthPeek.from)} – {formatShortDate(netWorthPeek.to)}</h2>
                  <p>How checking, savings, brokerage, and other account values changed in this range.</p>
                </div>
                <button className="ghostButton compactButton" onClick={() => setNetWorthPeek(null)} aria-label="Close asset change preview"><X size={16} /></button>
              </header>
              <section className="assetPeekSummary">
                <span>Total net-worth change</span>
                <strong className={netWorthPeek.change_cents < 0 ? "amount negative" : "amount positive"}>{netWorthPeek.change_cents >= 0 ? "+" : ""}{formatMoney(netWorthPeek.change_cents)}</strong>
                <small>{formatMoney(netWorthPeek.start_cents)} → {formatMoney(netWorthPeek.end_cents)}</small>
              </section>
              <div className="assetPeekRows">
                {netWorthPeek.accounts.map((account) => (
                  <button type="button" className="assetPeekRow" key={account.account_id} onClick={() => {
                    openTransactionView({ accounts: [String(account.account_id)], dateFrom: netWorthPeek.from, dateTo: netWorthPeek.to });
                    setNetWorthPeek(null);
                  }}>
                    <div>
                      <strong>{account.account}{account.last_four ? ` (${account.last_four})` : ""}</strong>
                      <small>{account.account_type.replaceAll("_", " ")} · {formatMoney(account.start_cents)} → {formatMoney(account.end_cents)}</small>
                    </div>
                    <span className={account.change_cents < 0 ? "amount negative" : "amount positive"}>{account.change_cents >= 0 ? "+" : ""}{formatMoney(account.change_cents)}{account.change_pct === null ? "" : ` (${account.change_pct}%)`}</span>
                  </button>
                ))}
                {netWorthPeek.accounts.length === 0 ? <p className="emptyText">No account values changed in this range.</p> : null}
              </div>
              <footer><span>Choose an account to open its activity for this date range.</span></footer>
            </aside>
          </div>
        ) : null}
      </main>
    </div>
  );
}


function reportTitle(activeTab: ReportTab) {
  if (activeTab === "Spending") return "Where your money is going";
  if (activeTab === "Net Worth") return "Investment-backed net worth";
  if (activeTab === "Cash Flow") return "Cash flow by month";
  return "Financial overview";
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

function MetricTile({ label, value, tone }: { label: string; value: string; tone: "green" | "red" | "neutral" }) {
  return (
    <div className={`metricTile ${tone}`}>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}
