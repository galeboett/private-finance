import { X } from "lucide-react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { useApiClient } from "../../api/hooks";
import { readAppRoute, routeUrl } from "../../app/router";
import { CashFlowGraphic, DrillDownLink } from "../../components/AppPrimitives";
import { DeleteConfirmInline, type DeleteTarget } from "../../components/DeleteConfirmInline";
import { encodeTxnFilter, type NetWorthPeriod, type ReportTab, type TxnFilter } from "../../lib/filters";
import { HoldingsPanel, type HoldingRow } from "../networth/HoldingsPanel";
import { ManualSnapshotEditor } from "../networth/ManualSnapshotEditor";
import { UnanchoredBanner } from "../networth/UnanchoredBanner";
import { ManualTransactionForm } from "../transactions/ManualTransactionForm";

type BootstrapCategory = { id: number; key: string; label: string; parent_id: number | null };
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
  sidebar_balance_kind: string;
  sidebar_balance_as_of: string | null;
};
type CategoryTotal = { category_id: number | null; category: string; amount_cents: number; count: number };
type AggregateRow = { date: string; total_cents: number; count: number };
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
  max_cents: number;
  max_date: string;
  min_cents: number;
  min_date: string;
};
type AllocationRow = { asset_class: string; market_value_cents: number };

const uncategorizedFilterValue = "__uncategorized__";
const formatMoney = (cents: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);

const formatShortDate = (value: string | null | undefined) => {
  if (!value) return "—";
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat("en-US", { month: "2-digit", day: "2-digit", year: "2-digit" }).format(parsed);
};

function aggregatePath(dimension: "by-category" | "by-account" | "timeseries", filter: TxnFilter, bucket?: "day" | "week" | "month"): string {
  const params = encodeTxnFilter(filter);
  if (bucket) params.set("bucket", bucket);
  return `/api/aggregate/${dimension}?${params.toString()}`;
}

export function ReportSurface({
  activeTab,
  income,
  expenses,
  net,
  categoryTotals,
  cashFlowRows,
  netWorthAccounts,
  allAccounts,
  allocationRows,
  holdingRows,
  csrf,
  categories,
  selectedHoldingIds,
  deleteTarget,
  deleteConfirmText,
  onToggleHoldingSelection,
  onRequestBulkHoldingDelete,
  onClearHoldingSelection,
  onUpdateHoldingDescription,
  onSaveManualNetWorthSnapshot,
  onFinanceMutation,
  onFinanceError,
  reportFilter,
  onOpenTransactionView,
  onOpenTransactionPeek,
  onOpenNetWorthPeek,
  onOpenAccount,
  onRequestDelete,
  onConfirmDelete,
  onDeleteConfirmTextChange,
  onCancelDelete,
}: {
  activeTab: ReportTab;
  income: number;
  expenses: number;
  net: number;
  categoryTotals: CategoryTotal[];
  cashFlowRows: MonthlyCashFlow[];
  netWorthAccounts: NetWorthAccount[];
  allAccounts: AccountSummary[];
  allocationRows: AllocationRow[];
  holdingRows: HoldingRow[];
  csrf: string;
  categories: BootstrapCategory[];
  selectedHoldingIds: number[];
  deleteTarget: DeleteTarget | null;
  deleteConfirmText: string;
  onToggleHoldingSelection: (holdingId: number, visibleIds: number[], shiftKey: boolean) => void;
  onRequestBulkHoldingDelete: (ids: number[]) => void;
  onClearHoldingSelection: () => void;
  onUpdateHoldingDescription: (symbol: string | null, userDescription: string) => Promise<void>;
  onSaveManualNetWorthSnapshot: (accountId: number, snapshotDate: string, balance: string) => Promise<boolean>;
  onFinanceMutation: (operationId: string, message: string) => Promise<void>;
  onFinanceError: (message: string) => void;
  reportFilter: TxnFilter;
  onOpenTransactionView: (filter: TxnFilter) => void;
  onOpenTransactionPeek: (filter: TxnFilter, title: string) => void;
  onOpenNetWorthPeek: (fromDate: string, toDate: string) => void;
  onOpenAccount: (accountId: number) => void;
  onRequestDelete: (target: DeleteTarget) => void;
  onConfirmDelete: () => Promise<void>;
  onDeleteConfirmTextChange: (value: string) => void;
  onCancelDelete: () => void;
}) {
  if (activeTab === "Spending") {
    return <SpendingReport rows={categoryTotals} reportFilter={reportFilter} onPeek={onOpenTransactionPeek} />;
  }
  if (activeTab === "Net Worth") {
    return <NetWorthReport accounts={netWorthAccounts} allAccounts={allAccounts} allocationRows={allocationRows} holdingRows={holdingRows} csrf={csrf} categories={categories} selectedHoldingIds={selectedHoldingIds} deleteTarget={deleteTarget} deleteConfirmText={deleteConfirmText} onToggleHoldingSelection={onToggleHoldingSelection} onRequestBulkHoldingDelete={onRequestBulkHoldingDelete} onClearHoldingSelection={onClearHoldingSelection} onUpdateHoldingDescription={onUpdateHoldingDescription} onSaveManualNetWorthSnapshot={onSaveManualNetWorthSnapshot} onFinanceMutation={onFinanceMutation} onFinanceError={onFinanceError} onViewTransactions={(fromDate, toDate) => onOpenTransactionView({ dateFrom: fromDate, dateTo: toDate })} onPeekNetWorth={onOpenNetWorthPeek} onOpenAccount={onOpenAccount} onRequestDelete={onRequestDelete} onConfirmDelete={onConfirmDelete} onDeleteConfirmTextChange={onDeleteConfirmTextChange} onCancelDelete={onCancelDelete} />;
  }
  if (activeTab === "Cash Flow") {
    return <MonthlyCashFlowReport rows={cashFlowRows} income={income} expenses={expenses} net={net} reportFilter={reportFilter} onPeek={onOpenTransactionPeek} />;
  }
  return (
    <div className="reportStack">
      <CashFlowGraphic income={income} expenses={expenses} net={net} />
      <div className="reportMiniGrid">
        <DrillDownLink filter={{ ...reportFilter, types: ["income"] }} title="Tracked income" onPeek={onOpenTransactionPeek}><ReportStat label="Tracked income" value={formatMoney(income)} /></DrillDownLink>
        <DrillDownLink filter={{ ...reportFilter, types: ["expense", "refund"] }} title="Tracked expenses" onPeek={onOpenTransactionPeek}><ReportStat label="Tracked expenses" value={formatMoney(expenses)} /></DrillDownLink>
        <DrillDownLink filter={{ ...reportFilter, types: ["income", "expense", "refund"] }} title="Tracked cash flow" onPeek={onOpenTransactionPeek}><ReportStat label="Tracked net" value={formatMoney(net)} /></DrillDownLink>
      </div>
    </div>
  );
}

function SpendingReport({ rows, reportFilter, onPeek }: { rows: CategoryTotal[]; reportFilter: TxnFilter; onPeek: (filter: TxnFilter, title: string) => void }) {
  const api = useApiClient();
  const max = Math.max(...rows.map((row) => row.amount_cents), 1);
  const total = rows.reduce((sum, row) => sum + row.amount_cents, 0);
  const chartCategories = useMemo(() => rows.filter((row) => row.category_id !== null).slice(0, 6), [rows]);
  const [monthlySeries, setMonthlySeries] = useState<Record<string, AggregateRow[]>>({});
  const [hiddenCategories, setHiddenCategories] = useState<string[]>([]);
  const [dragStart, setDragStart] = useState<number | null>(null);
  const [dragEnd, setDragEnd] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all(
      chartCategories.map(async (category) => [
        String(category.category_id),
        await api<AggregateRow[]>(aggregatePath("timeseries", { ...reportFilter, dateBasis: "reporting", categories: [String(category.category_id)], types: ["expense", "refund"] }, "month")),
      ] as const),
    )
      .then((entries) => {
        if (!cancelled) setMonthlySeries(Object.fromEntries(entries));
      })
      .catch(() => {
        if (!cancelled) setMonthlySeries({});
      });
    return () => { cancelled = true; };
  }, [chartCategories, reportFilter.dateFrom, reportFilter.dateTo, reportFilter.months?.join(","), reportFilter.years?.join(",")]);

  const months = useMemo(
    () => Array.from(new Set(Object.values(monthlySeries).flatMap((series) => series.map((point) => point.date.slice(0, 7))))).sort(),
    [monthlySeries],
  );
  const visibleCategories = chartCategories.filter((category) => !hiddenCategories.includes(String(category.category_id)));
  const monthlyValues = months.map((month) => ({
    month,
    values: visibleCategories.map((category) => ({
      category,
      amount: Math.abs(monthlySeries[String(category.category_id)]?.find((point) => point.date.startsWith(month))?.total_cents ?? 0),
    })),
  }));
  const maxMonth = Math.max(...monthlyValues.map((month) => month.values.reduce((sum, value) => sum + value.amount, 0)), 1);
  const selectedStart = dragStart === null || dragEnd === null ? null : Math.min(dragStart, dragEnd);
  const selectedEnd = dragStart === null || dragEnd === null ? null : Math.max(dragStart, dragEnd);
  const selectedMonths = selectedStart === null || selectedEnd === null ? [] : monthlyValues.slice(selectedStart, selectedEnd + 1);
  const selectedTotal = selectedMonths.reduce((sum, month) => sum + month.values.reduce((monthSum, value) => monthSum + value.amount, 0), 0);

  function monthEnd(month: string) {
    const [year, monthNumber] = month.split("-").map(Number);
    return new Date(Date.UTC(year, monthNumber, 0)).toISOString().slice(0, 10);
  }

  function pointerMonth(event: ReactPointerEvent<SVGSVGElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(0.9999, (event.clientX - bounds.left) / bounds.width));
    return Math.min(months.length - 1, Math.floor(ratio * months.length));
  }

  const selectedFilter: TxnFilter | null = selectedMonths.length > 0 ? {
    ...reportFilter,
    months: undefined,
    years: undefined,
    dateBasis: "reporting",
    dateFrom: `${selectedMonths[0].month}-01`,
    dateTo: monthEnd(selectedMonths[selectedMonths.length - 1].month),
    categories: visibleCategories.map((category) => String(category.category_id)),
    types: ["expense", "refund"],
    sort: "amount",
    sortDirection: "desc",
  } : null;

  return (
    <div className="reportStack">
      {months.length > 0 ? (
        <section className="spendingTrendPanel">
          <div className="spendingTrendHeader">
            <div>
              <span className="eyebrow">Monthly comparison</span>
              <h3>Spending by category over time</h3>
              <p>Drag across months to total a period. Toggle categories to focus the comparison.</p>
            </div>
            {selectedFilter ? (
              <button className="ghostButton compactButton" onClick={() => { setDragStart(null); setDragEnd(null); }}>Clear range</button>
            ) : null}
          </div>
          {selectedFilter ? (
            <div className="spendingRangeSummary">
              <div><span>Selected period</span><strong>{formatShortDate(selectedFilter.dateFrom)} – {formatShortDate(selectedFilter.dateTo)}</strong></div>
              <div><span>Visible-category spending</span><strong>{formatMoney(selectedTotal)}</strong></div>
              <button className="secondaryButton compactButton" onClick={() => onPeek(selectedFilter, "Selected spending period")}>View transactions</button>
            </div>
          ) : null}
          <div className="spendingLegend" aria-label="Spending categories">
            {chartCategories.map((category, index) => {
              const id = String(category.category_id);
              const hidden = hiddenCategories.includes(id);
              return (
                <button key={id} className={hidden ? "spendingLegendItem muted" : "spendingLegendItem"} onClick={() => setHiddenCategories((current) => hidden ? current.filter((value) => value !== id) : [...current, id])}>
                  <span style={{ backgroundColor: `hsl(222 68% ${Math.min(68, 44 + index * 4)}%)` }} />
                  {category.category}
                </button>
              );
            })}
          </div>
          <svg
            className="spendingTrendChart"
            viewBox="0 0 900 300"
            role="img"
            aria-label="Monthly stacked spending chart. Drag across months to select a range."
            onPointerDown={(event) => {
              if (months.length === 0) return;
              const index = pointerMonth(event);
              setDragStart(index);
              setDragEnd(index);
              setDragging(true);
              event.currentTarget.setPointerCapture(event.pointerId);
            }}
            onPointerMove={(event) => { if (dragging) setDragEnd(pointerMonth(event)); }}
            onPointerUp={(event) => { setDragging(false); if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }}
          >
            {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
              const y = 250 - ratio * 220;
              return <g key={ratio}><line x1="58" x2="890" y1={y} y2={y} className="spendingGridLine" /><text x="52" y={y + 4} textAnchor="end" className="spendingAxisLabel">{formatMoney(Math.round(maxMonth * ratio))}</text></g>;
            })}
            {monthlyValues.map((month, monthIndex) => {
              const slot = 832 / Math.max(monthlyValues.length, 1);
              const width = Math.max(8, Math.min(46, slot * 0.66));
              const x = 58 + monthIndex * slot + (slot - width) / 2;
              let stackedHeight = 0;
              const selected = selectedStart !== null && selectedEnd !== null && monthIndex >= selectedStart && monthIndex <= selectedEnd;
              return (
                <g key={month.month}>
                  {selected ? <rect x={58 + monthIndex * slot} y="30" width={slot} height="220" className="spendingSelection" /> : null}
                  {month.values.map((value) => {
                    const height = (value.amount / maxMonth) * 220;
                    const y = 250 - stackedHeight - height;
                    stackedHeight += height;
                    const categoryIndex = chartCategories.findIndex((category) => category.category_id === value.category.category_id);
                    return <rect key={String(value.category.category_id)} x={x} y={y} width={width} height={height} rx="2" fill={`hsl(222 68% ${Math.min(68, 44 + categoryIndex * 4)}%)`}><title>{value.category.category}: {formatMoney(value.amount)}</title></rect>;
                  })}
                  <text x={x + width / 2} y="272" textAnchor="middle" className="spendingMonthLabel">{new Date(`${month.month}-01T00:00:00`).toLocaleDateString(undefined, { month: "short", year: monthlyValues.length <= 8 ? "2-digit" : undefined })}</text>
                </g>
              );
            })}
          </svg>
        </section>
      ) : null}
      <div className="barList">
        {rows.map((row, index) => (
          <DrillDownLink className="barRow spendingBarRow" key={row.category} filter={{ ...reportFilter, dateBasis: "reporting", categories: [row.category_id === null ? uncategorizedFilterValue : String(row.category_id)], types: ["expense", "refund"], sort: "amount", sortDirection: "desc" }} title={`${row.category} spending`} count={row.count} onPeek={onPeek}>
            <div>
              <strong>#{index + 1} {row.category}</strong>
              <span>{formatMoney(row.amount_cents)}</span>
            </div>
            <small className="spendingComparison">{total > 0 ? Math.round((row.amount_cents / total) * 100) : 0}% of categorized spending · {Math.round((row.amount_cents / max) * 100)}% of the largest category</small>
            <div className="barTrack blue">
              <div style={{ width: `${Math.max(4, Math.round((row.amount_cents / max) * 100))}%`, backgroundColor: `hsl(222 68% ${Math.min(68, 46 + index * 3)}%)` }} />
            </div>
          </DrillDownLink>
        ))}
        {rows.length === 0 ? <p className="emptyText">No categorized expenses yet. Categorize and confirm transactions to populate this report.</p> : null}
      </div>
    </div>
  );
}

function MonthlyCashFlowReport({ rows, income, expenses, net, reportFilter, onPeek }: { rows: MonthlyCashFlow[]; income: number; expenses: number; net: number; reportFilter: TxnFilter; onPeek: (filter: TxnFilter, title: string) => void }) {
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
        <DrillDownLink filter={{ ...reportFilter, types: ["income"] }} title="Period income" onPeek={onPeek}><ReportStat label="Period income" value={formatMoney(income)} /></DrillDownLink>
        <DrillDownLink filter={{ ...reportFilter, types: ["expense", "refund"] }} title="Period expenses" onPeek={onPeek}><ReportStat label="Period expenses" value={formatMoney(expenses)} /></DrillDownLink>
        <DrillDownLink filter={{ ...reportFilter, types: ["income", "expense", "refund"] }} title="Period cash flow" onPeek={onPeek}><ReportStat label="Period net" value={formatMoney(net)} /></DrillDownLink>
      </div>
      <div className="reportTable">
        <div className="reportTableHeader">
          <span>Month</span>
          <span>Income</span>
          <span>Expenses</span>
          <span>Net</span>
        </div>
        {rows.slice(-12).map((row) => (
          <DrillDownLink className="reportTableRow" key={row.month} filter={{ months: [row.month.slice(5, 7)], years: [row.month.slice(0, 4)], types: ["income", "expense", "refund"] }} title={`${row.month} cash flow`} onPeek={onPeek}>
            <strong>{row.month}</strong>
            <span>{formatMoney(row.income_cents)}</span>
            <span>{formatMoney(row.expense_cents)}</span>
            <span className={row.net_cents < 0 ? "amount negative" : "amount positive"}>{formatMoney(row.net_cents)}</span>
          </DrillDownLink>
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
            <DrillDownLink className="reportTableRow" key={row.year} filter={{ years: [row.year], types: ["income", "expense", "refund"] }} title={`${row.year} cash flow`} onPeek={onPeek}>
              <strong>{row.year}</strong>
              <span>{formatMoney(row.income_cents)}</span>
              <span>{formatMoney(row.expense_cents)}</span>
              <span className={row.net_cents < 0 ? "amount negative" : "amount positive"}>{formatMoney(row.net_cents)}</span>
            </DrillDownLink>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function NetWorthHistoryChart({ onViewTransactions, onPeekNetWorth }: { onViewTransactions: (fromDate: string, toDate: string) => void; onPeekNetWorth: (fromDate: string, toDate: string) => void }) {
  const api = useApiClient();
  const [period, setPeriod] = useState<NetWorthPeriod>(() => readAppRoute(window.location).filters.netWorthPeriod ?? "6M");
  const [data, setData] = useState<NetWorthSeriesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [dragStart, setDragStart] = useState<number | null>(null);
  const [dragEnd, setDragEnd] = useState<number | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [dragMode, setDragMode] = useState<"new" | "start" | "end" | null>(null);
  const [selectionStats, setSelectionStats] = useState<NetWorthStats | null>(null);

  useEffect(() => {
    let cancelled = false;
    const range = netWorthPeriodRange(period);
    setLoading(true);
    setSelectionStats(null);
    setDragStart(null);
    setDragEnd(null);
    setIsDragging(false);
    setDragMode(null);
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
      setDragMode(null);
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
  const height = 300;
  const left = 72;
  const right = 18;
  const top = 24;
  const bottom = 44;
  const chartWidth = width - left - right;
  const chartHeight = height - top - bottom;
  const values = rows.map((row) => row.total_cents);
  const rawMaximum = values.length > 0 ? Math.max(...values) : 0;
  const minimum = 0;
  const axisStep = niceAxisStep(Math.max(rawMaximum, 100), 4);
  const maximum = Math.max(axisStep, Math.ceil(Math.max(rawMaximum, 0) / axisStep) * axisStep);
  const span = Math.max(maximum - minimum, 1);
  const xFor = (index: number) => left + (rows.length <= 1 ? chartWidth / 2 : (index / (rows.length - 1)) * chartWidth);
  const yFor = (value: number) => top + ((maximum - Math.max(0, value)) / span) * chartHeight;
  const linePath = rows.map((row, index) => `${index === 0 ? "M" : "L"} ${xFor(index)} ${yFor(row.total_cents)}`).join(" ");
  const areaPath = rows.length > 0 ? `${linePath} L ${xFor(rows.length - 1)} ${top + chartHeight} L ${xFor(0)} ${top + chartHeight} Z` : "";
  const latest = rows.at(-1)?.total_cents ?? 0;
  const first = rows[0]?.total_cents ?? 0;
  const periodChange = latest - first;
  const activeIndex = hoverIndex ?? dragEnd;
  const selectedStart = dragStart === null || dragEnd === null ? null : Math.min(dragStart, dragEnd);
  const selectedEnd = dragStart === null || dragEnd === null ? null : Math.max(dragStart, dragEnd);
  const yTicks = Array.from({ length: Math.round(maximum / axisStep) + 1 }, (_, index) => index * axisStep);
  const xTickIndexes = Array.from(new Set(Array.from({ length: Math.min(5, rows.length) }, (_, index) => Math.round((index / Math.max(1, Math.min(5, rows.length) - 1)) * Math.max(0, rows.length - 1)))));

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
      {selectionStats ? (
        <div className="netWorthSelectionBanner">
          <div className="selectionGain">
            <strong className={selectionStats.change_cents < 0 ? "amount negative" : "amount positive"}>{selectionStats.change_cents >= 0 ? "+" : ""}{formatMoney(selectionStats.change_cents)}{selectionStats.change_pct === null ? "" : ` (${selectionStats.change_pct}%)`}</strong>
            <span>{formatShortDate(selectionStats.from)} – {formatShortDate(selectionStats.to)}</span>
          </div>
          <div className="selectionExtremes">
            <span>High <strong>{formatMoney(selectionStats.max_cents)}</strong> · {formatShortDate(selectionStats.max_date)}</span>
            <span>Low <strong>{formatMoney(selectionStats.min_cents)}</strong> · {formatShortDate(selectionStats.min_date)}</span>
          </div>
          <div className="selectionActions">
            <button type="button" className="secondaryButton compactButton" onClick={() => onPeekNetWorth(selectionStats.from, selectionStats.to)}>See asset changes</button>
            <button type="button" className="ghostButton compactButton" onClick={() => onViewTransactions(selectionStats.from, selectionStats.to)}>View ledger activity</button>
            <button type="button" className="ghostButton compactButton" onClick={() => { setSelectionStats(null); setDragStart(null); setDragEnd(null); setIsDragging(false); setDragMode(null); }} aria-label="Clear selected net worth range"><X size={14} /></button>
          </div>
        </div>
      ) : null}
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
              if (selectedStart !== null && selectedEnd !== null && Math.abs(index - selectedStart) <= 1) {
                setDragStart(selectedStart);
                setDragEnd(selectedEnd);
                setDragMode("start");
              } else if (selectedStart !== null && selectedEnd !== null && Math.abs(index - selectedEnd) <= 1) {
                setDragStart(selectedStart);
                setDragEnd(selectedEnd);
                setDragMode("end");
              } else {
                setDragStart(index);
                setDragEnd(index);
                setDragMode("new");
                setSelectionStats(null);
              }
              setIsDragging(true);
            }}
            onPointerMove={(event) => {
              const index = pointerIndex(event);
              setHoverIndex(index);
              if (isDragging) {
                if (dragMode === "start") setDragStart(index);
                else setDragEnd(index);
              }
            }}
            onPointerUp={(event) => {
              if (!isDragging || dragStart === null || dragEnd === null) return;
              const index = pointerIndex(event);
              const nextStart = dragMode === "start" ? index : dragStart;
              const nextEnd = dragMode === "end" || dragMode === "new" ? index : dragEnd;
              const normalizedStart = Math.min(nextStart, nextEnd);
              const normalizedEnd = Math.max(nextStart, nextEnd);
              setDragStart(normalizedStart);
              setDragEnd(normalizedEnd);
              void finishSelection(normalizedStart, normalizedEnd);
              setIsDragging(false);
              setDragMode(null);
            }}
            onPointerLeave={() => setHoverIndex(null)}
          >
            <defs>
              <linearGradient id="netWorthFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#3b6ae8" stopOpacity="0.3" />
                <stop offset="100%" stopColor="#3b6ae8" stopOpacity="0.03" />
              </linearGradient>
            </defs>
            {yTicks.map((tick) => (
              <g key={tick}>
                <line x1={left} x2={width - right} y1={yFor(tick)} y2={yFor(tick)} className={tick === 0 ? "chartAxis" : "chartGridLine"} />
                <text x={left - 10} y={yFor(tick) + 4} textAnchor="end" className="chartLabel">{formatCompactMoney(tick)}</text>
              </g>
            ))}
            {xTickIndexes.map((index) => (
              <g key={rows[index].date}>
                <line x1={xFor(index)} x2={xFor(index)} y1={top + chartHeight} y2={top + chartHeight + 5} className="chartAxis" />
                <text x={xFor(index)} y={height - 12} textAnchor={index === 0 ? "start" : index === rows.length - 1 ? "end" : "middle"} className="chartLabel">{formatChartAxisDate(rows[index].date, period)}</text>
              </g>
            ))}
            <path d={areaPath} fill="url(#netWorthFill)" />
            <path d={linePath} className="netWorthLine" />
            {selectedStart !== null && selectedEnd !== null ? (
              <g>
                <rect x={xFor(selectedStart)} y={top} width={Math.max(2, xFor(selectedEnd) - xFor(selectedStart))} height={chartHeight} className="chartSelection" />
                <line x1={xFor(selectedStart)} x2={xFor(selectedStart)} y1={top} y2={top + chartHeight} className="chartSelectionHandle" />
                <line x1={xFor(selectedEnd)} x2={xFor(selectedEnd)} y1={top} y2={top + chartHeight} className="chartSelectionHandle" />
                <circle cx={xFor(selectedStart)} cy={top + chartHeight / 2} r="7" className="chartSelectionGrip" />
                <circle cx={xFor(selectedEnd)} cy={top + chartHeight / 2} r="7" className="chartSelectionGrip" />
              </g>
            ) : null}
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

function niceAxisStep(maximum: number, targetIntervals: number): number {
  const roughStep = maximum / Math.max(1, targetIntervals);
  const magnitude = 10 ** Math.floor(Math.log10(Math.max(roughStep, 1)));
  const normalized = roughStep / magnitude;
  const niceNormalized = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return niceNormalized * magnitude;
}

function formatChartAxisDate(value: string, period: NetWorthPeriod): string {
  const parsed = new Date(`${value}T00:00:00`);
  return new Intl.DateTimeFormat("en-US", period === "1Y" || period === "Max" ? { month: "short", year: "2-digit" } : { month: "short", day: "numeric" }).format(parsed);
}

function accountSparklinePoints(rows: NetWorthPoint[], accountId: number): string {
  const values = rows.map((row) => row.by_account[String(accountId)] ?? 0);
  if (values.length === 0) return "";
  const minimum = Math.min(...values);
  const span = Math.max(Math.max(...values) - minimum, 1);
  return values.map((value, index) => `${values.length === 1 ? 50 : (index / (values.length - 1)) * 100},${28 - ((value - minimum) / span) * 24}`).join(" ");
}

function NetWorthReport({
  accounts,
  allAccounts,
  allocationRows,
  holdingRows,
  csrf,
  categories,
  selectedHoldingIds,
  deleteTarget,
  deleteConfirmText,
  onToggleHoldingSelection,
  onRequestBulkHoldingDelete,
  onClearHoldingSelection,
  onUpdateHoldingDescription,
  onSaveManualNetWorthSnapshot,
  onFinanceMutation,
  onFinanceError,
  onViewTransactions,
  onPeekNetWorth,
  onOpenAccount,
  onRequestDelete,
  onConfirmDelete,
  onDeleteConfirmTextChange,
  onCancelDelete,
}: {
  accounts: NetWorthAccount[];
  allAccounts: AccountSummary[];
  allocationRows: AllocationRow[];
  holdingRows: HoldingRow[];
  csrf: string;
  categories: BootstrapCategory[];
  selectedHoldingIds: number[];
  deleteTarget: DeleteTarget | null;
  deleteConfirmText: string;
  onToggleHoldingSelection: (holdingId: number, visibleIds: number[], shiftKey: boolean) => void;
  onRequestBulkHoldingDelete: (ids: number[]) => void;
  onClearHoldingSelection: () => void;
  onUpdateHoldingDescription: (symbol: string | null, userDescription: string) => Promise<void>;
  onSaveManualNetWorthSnapshot: (accountId: number, snapshotDate: string, balance: string) => Promise<boolean>;
  onFinanceMutation: (operationId: string, message: string) => Promise<void>;
  onFinanceError: (message: string) => void;
  onViewTransactions: (fromDate: string, toDate: string) => void;
  onPeekNetWorth: (fromDate: string, toDate: string) => void;
  onOpenAccount: (accountId: number) => void;
  onRequestDelete: (target: DeleteTarget) => void;
  onConfirmDelete: () => Promise<void>;
  onDeleteConfirmTextChange: (value: string) => void;
  onCancelDelete: () => void;
}) {
  const api = useApiClient();
  const total = accounts.reduce((sum, row) => sum + row.market_value_cents, 0);
  const max = Math.max(...accounts.map((row) => row.market_value_cents), 1);
  const assetAccounts = allAccounts.filter((account) => account.account_type === "brokerage" || account.account_type === "retirement");
  const balanceAccounts = allAccounts.filter((account) => account.account_type !== "external");
  const unanchoredAccounts = allAccounts.filter((account) => account.account_type !== "external" && account.net_worth_inclusion === "auto" && !account.is_anchored).map((account) => ({ id: account.id, name: account.display_name }));
  const [showManualTransaction, setShowManualTransaction] = useState(false);
  const [accountTrendRows, setAccountTrendRows] = useState<NetWorthPoint[]>([]);
  useEffect(() => {
    const range = netWorthPeriodRange("6M");
    api<NetWorthSeriesResponse>(`/api/snapshots/networth?${range.params.toString()}`).then((result) => setAccountTrendRows(result.series)).catch(() => setAccountTrendRows([]));
  }, []);
  return (
    <div className="reportStack">
      <UnanchoredBanner accounts={unanchoredAccounts} onChoose={onOpenAccount} />
      <NetWorthHistoryChart onViewTransactions={onViewTransactions} onPeekNetWorth={onPeekNetWorth} />
      <ManualSnapshotEditor accounts={balanceAccounts} csrf={csrf} onCreate={onSaveManualNetWorthSnapshot} onChanged={onFinanceMutation} onError={onFinanceError} />
      <section className="manualTransactionEntryPanel">
        <div><strong>Add investment activity</strong><span>Record a manual money movement in a brokerage or retirement account.</span></div>
        <button type="button" className="secondaryButton compactButton" disabled={assetAccounts.length === 0} onClick={() => setShowManualTransaction((current) => !current)}>{showManualTransaction ? "Cancel" : "Add transaction"}</button>
      </section>
      {showManualTransaction ? <ManualTransactionForm accounts={assetAccounts} categories={categories} csrf={csrf} onSaved={(operationId) => onFinanceMutation(operationId, "Manual investment transaction added.")} onError={onFinanceError} onCancel={() => setShowManualTransaction(false)} /> : null}
      <div className="reportMiniGrid">
        <ReportStat label="Latest investment value" value={formatMoney(total)} />
        <ReportStat label="Accounts with snapshots" value={String(accounts.length)} />
        <ReportStat label="Allocation groups" value={String(allocationRows.length)} />
      </div>
      <div className="barList">
        {accounts.map((row) => {
          const sparkline = accountSparklinePoints(accountTrendRows, row.account_id);
          return <div className="barRow" key={row.account_id}>
            <div>
              <strong>{row.account}</strong>
              <span>{formatMoney(row.market_value_cents)} / {formatShortDate(row.latest_date)}</span>
            </div>
            {sparkline ? <svg className="accountSparkline" viewBox="0 0 100 32" role="img" aria-label={`${row.account} six-month balance trend`}><polyline points={sparkline} /></svg> : null}
            <div className="barTrack blue">
              <div style={{ width: `${Math.max(4, Math.round((row.market_value_cents / max) * 100))}%` }} />
            </div>
          </div>
        })}
        {accounts.length === 0 ? <p className="emptyText">No investment snapshots yet. Commit a brokerage positions CSV to populate net worth.</p> : null}
      </div>
      {deleteTarget?.kind === "holding" || deleteTarget?.kind === "holding_bulk" ? <DeleteConfirmInline target={deleteTarget} confirmText={deleteConfirmText} onConfirmTextChange={onDeleteConfirmTextChange} onConfirm={onConfirmDelete} onCancel={onCancelDelete} /> : null}
      <HoldingsPanel rows={holdingRows} accounts={assetAccounts} csrf={csrf} selectedIds={selectedHoldingIds} formatMoney={formatMoney} formatDate={formatShortDate} onToggleSelection={onToggleHoldingSelection} onRequestBulkDelete={onRequestBulkHoldingDelete} onClearSelection={onClearHoldingSelection} onUpdateDescription={onUpdateHoldingDescription} onRequestDelete={(row) => onRequestDelete({ kind: "holding", id: row.id, label: `${row.symbol || row.description || "Holding"} in ${row.account}` })} onLotSaved={(operationId) => onFinanceMutation(operationId, "Tax lot updated; basis and gain/loss refreshed.")} onError={onFinanceError} />
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

function ReportStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="reportStat">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
