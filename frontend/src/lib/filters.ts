export type TransactionDirection = "inflow" | "outflow";
export type TransactionView = "live" | "trash";
export type TransactionSort = "date" | "amount";
export type SortDirection = "asc" | "desc";
export type NetWorthPeriod = "1M" | "6M" | "1Y" | "Max";

export interface TxnFilter {
  accounts?: string[];
  categories?: string[];
  months?: string[];
  years?: string[];
  dateFrom?: string;
  dateTo?: string;
  amountMin?: number;
  amountMax?: number;
  direction?: TransactionDirection;
  search?: string;
  view?: TransactionView;
  sort?: TransactionSort;
  sortDirection?: SortDirection;
  netWorthPeriod?: NetWorthPeriod;
}

export type RouteView = "overview" | "all-accounts" | "account" | "review" | "reports" | "history" | "settings";

export type AppRoute = {
  view: RouteView;
  accountId: number | null;
  filters: TxnFilter;
};

const listKeys = ["accounts", "categories", "months", "years"] as const;

export function readAppRoute(location: Pick<Location, "pathname" | "search">): AppRoute {
  const accountMatch = location.pathname.match(/^\/accounts\/(\d+)\/transactions\/?$/);
  const view: RouteView = accountMatch
    ? "account"
    : location.pathname.startsWith("/transactions")
      ? "all-accounts"
      : location.pathname.startsWith("/review")
        ? "review"
        : location.pathname.startsWith("/reports")
          ? "reports"
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
  return filter;
}

export function encodeTxnFilter(filter: TxnFilter): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of listKeys) {
    if (filter[key] !== undefined) params.set(key, filter[key]!.join(","));
  }
  setParam(params, "dateFrom", filter.dateFrom);
  setParam(params, "dateTo", filter.dateTo);
  setParam(params, "amountMin", filter.amountMin);
  setParam(params, "amountMax", filter.amountMax);
  setParam(params, "direction", filter.direction);
  setParam(params, "search", filter.search?.trim() || undefined);
  if (filter.view === "trash") params.set("view", "trash");
  if (filter.sort && filter.sort !== "date") params.set("sort", filter.sort);
  if (filter.sortDirection && filter.sortDirection !== "desc") params.set("sortDirection", filter.sortDirection);
  if (filter.netWorthPeriod && filter.netWorthPeriod !== "6M") params.set("period", filter.netWorthPeriod);
  return params;
}

export function routeUrl(view: RouteView, accountId: number | null, filter: TxnFilter): string {
  const params = encodeTxnFilter(filter);
  const query = params.toString();
  return `${routePath(view, accountId)}${query ? `?${query}` : ""}`;
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
