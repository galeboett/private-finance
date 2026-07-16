export type TransactionDirection = "inflow" | "outflow";
export type TransactionView = "live" | "trash";
export type TransactionSort = "date" | "amount";
export type SortDirection = "asc" | "desc";
export type NetWorthPeriod = "1M" | "6M" | "1Y" | "Max";
export type ReportPeriod = "this_month" | "this_year" | "last_12_months" | "all";

export interface TxnFilter {
  accounts?: string[];
  categories?: string[];
  tags?: string[];
  months?: string[];
  years?: string[];
  dateFrom?: string;
  dateTo?: string;
  dateBasis?: "transaction" | "reporting";
  amountMin?: number;
  amountMax?: number;
  direction?: TransactionDirection;
  types?: string[];
  search?: string;
  view?: TransactionView;
  sort?: TransactionSort;
  sortDirection?: SortDirection;
  netWorthPeriod?: NetWorthPeriod;
  hasRefund?: boolean;
}

export type RouteView = "overview" | "all-accounts" | "account" | "review" | "history" | "settings";

export type AppRoute = {
  view: RouteView;
  accountId: number | null;
  filters: TxnFilter;
};

const listKeys = ["accounts", "categories", "tags", "months", "years", "types"] as const;

export function readAppRoute(location: Pick<Location, "pathname" | "search">): AppRoute {
  const accountMatch = location.pathname.match(/^\/accounts\/(\d+)\/transactions\/?$/);
  const view: RouteView = accountMatch
    ? "account"
    : location.pathname.startsWith("/transactions")
      ? "all-accounts"
      : location.pathname.startsWith("/review")
        ? "review"
        : location.pathname.startsWith("/reports")
          ? "overview"
          : location.pathname.startsWith("/history")
            ? "history"
          : location.pathname.startsWith("/settings")
            ? "settings"
            : "overview";
  return {
    view,
    accountId: accountMatch ? Number(accountMatch[1]) : null,
    filters: decodeTxnFilter(new URLSearchParams(location.search)),
  };
}

export function routePath(view: RouteView, accountId: number | null = null): string {
  if (view === "account" && accountId) return `/accounts/${accountId}/transactions`;
  if (view === "all-accounts") return "/transactions";
  if (view === "overview") return "/";
  return `/${view}`;
}

export function decodeTxnFilter(params: URLSearchParams): TxnFilter {
  const filter: TxnFilter = {};
  for (const key of listKeys) {
    if (params.has(key)) filter[key] = decodeList(params.get(key));
  }
  setString(filter, "dateFrom", params.get("dateFrom"));
  setString(filter, "dateTo", params.get("dateTo"));
  if (params.get("dateBasis") === "reporting") filter.dateBasis = "reporting";
  setString(filter, "search", params.get("search"));
  setNumber(filter, "amountMin", params.get("amountMin"));
  setNumber(filter, "amountMax", params.get("amountMax"));
  const direction = params.get("direction");
  if (direction === "inflow" || direction === "outflow") filter.direction = direction;
  if (params.get("view") === "trash") filter.view = "trash";
  const sort = params.get("sort");
  if (sort === "date" || sort === "amount") filter.sort = sort;
  const sortDirection = params.get("sortDirection");
  if (sortDirection === "asc" || sortDirection === "desc") filter.sortDirection = sortDirection;
  const netWorthPeriod = params.get("period");
  if (netWorthPeriod === "1M" || netWorthPeriod === "6M" || netWorthPeriod === "1Y" || netWorthPeriod === "Max") filter.netWorthPeriod = netWorthPeriod;
  if (params.get("hasRefund") === "true") filter.hasRefund = true;
  return filter;
}

export function encodeTxnFilter(filter: TxnFilter): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of listKeys) {
    if (filter[key] !== undefined) params.set(key, filter[key]!.join(","));
  }
  setParam(params, "dateFrom", filter.dateFrom);
  setParam(params, "dateTo", filter.dateTo);
  if (filter.dateBasis === "reporting") params.set("dateBasis", "reporting");
  setParam(params, "amountMin", filter.amountMin);
  setParam(params, "amountMax", filter.amountMax);
  setParam(params, "direction", filter.direction);
  setParam(params, "search", filter.search?.trim() || undefined);
  if (filter.view === "trash") params.set("view", "trash");
  if (filter.sort && filter.sort !== "date") params.set("sort", filter.sort);
  if (filter.sortDirection && filter.sortDirection !== "desc") params.set("sortDirection", filter.sortDirection);
  if (filter.netWorthPeriod && filter.netWorthPeriod !== "6M") params.set("period", filter.netWorthPeriod);
  if (filter.hasRefund) params.set("hasRefund", "true");
  return params;
}

export function routeUrl(view: RouteView, accountId: number | null, filter: TxnFilter): string {
  const params = encodeTxnFilter(filter);
  const query = params.toString();
  return `${routePath(view, accountId)}${query ? `?${query}` : ""}`;
}

export function freshAccountNavigationFilter(accountId: number): TxnFilter {
  return { accounts: [String(accountId)] };
}

export function isTransactionInReportPeriod(transactionDate: string, period: ReportPeriod, now = new Date()): boolean {
  if (period === "all") return true;
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const thisMonth = `${year}-${month}`;
  if (period === "this_month") return transactionDate.slice(0, 7) === thisMonth;
  if (period === "this_year") return transactionDate.slice(0, 4) === String(year);
  const start = new Date(now.getFullYear(), now.getMonth() - 11, 1);
  const startKey = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, "0")}`;
  return transactionDate.slice(0, 7) >= startKey && transactionDate.slice(0, 7) <= thisMonth;
}

export function isMonthInReportPeriod(month: string, period: ReportPeriod, now = new Date()): boolean {
  if (period === "all") return true;
  const year = now.getFullYear();
  const currentMonth = `${year}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  if (period === "this_month") return month === currentMonth;
  if (period === "this_year") return month.startsWith(String(year));
  const start = new Date(now.getFullYear(), now.getMonth() - 11, 1);
  const startKey = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, "0")}`;
  return month >= startKey && month <= currentMonth;
}

function decodeList(value: string | null): string[] {
  if (!value) return [];
  return Array.from(new Set(value.split(",").map((item) => item.trim()).filter(Boolean)));
}

function setString<K extends "dateFrom" | "dateTo" | "search">(filter: TxnFilter, key: K, value: string | null) {
  if (value?.trim()) filter[key] = value.trim();
}

function setNumber<K extends "amountMin" | "amountMax">(filter: TxnFilter, key: K, value: string | null) {
  if (value === null || value.trim() === "") return;
  const parsed = Number(value);
  if (Number.isFinite(parsed) && parsed >= 0) filter[key] = parsed;
}

function setParam(params: URLSearchParams, key: string, value: string | number | undefined) {
  if (value !== undefined && value !== "") params.set(key, String(value));
}
