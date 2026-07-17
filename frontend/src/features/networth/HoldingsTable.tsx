import { ChevronDown, ChevronUp, ChevronsUpDown } from "lucide-react";
import { useEffect, type ReactNode } from "react";

import { useSort, type SortDirection } from "../../lib/useSort";

export type HoldingRow = {
  id: number;
  account_id: number;
  account: string;
  institution: string | null;
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
  lot_count: number;
  lot_quantity: number | null;
  cost_basis_cents: number | null;
  unrealized_gain_loss_cents: number | null;
  oldest_acquisition_date: string | null;
  lot_age_days: number | null;
};

export type HoldingSortKey = "institution" | "account" | "symbol" | "quantity" | "price" | "value" | "basis" | "gain" | "age";

const holdingSortKeys = new Set<HoldingSortKey>(["institution", "account", "symbol", "quantity", "price", "value", "basis", "gain", "age"]);

type Props = {
  rows: HoldingRow[];
  selectedIds: number[];
  formatMoney: (cents: number) => string;
  formatDate: (value: string) => string;
  onToggleSelection: (holdingId: number, visibleIds: number[], shiftKey: boolean) => void;
  onUpdateDescription: (symbol: string | null, userDescription: string) => Promise<void>;
  onRequestDelete: (row: HoldingRow) => void;
  onManageLots: (row: HoldingRow) => void;
};

export function HoldingsTable(props: Props) {
  const initial = readHoldingSort();
  const { sortKey, sortDirection, toggleSort, setSort } = useSort<HoldingSortKey>(initial.key, initial.direction);
  const sortedRows = sortHoldingRows(props.rows, sortKey, sortDirection);
  const visibleIds = sortedRows.map((row) => row.id);
  const totals = holdingTotals(props.rows);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (sortKey === "symbol") params.delete("holdingSort"); else params.set("holdingSort", sortKey);
    if (sortDirection === "asc") params.delete("holdingSortDirection"); else params.set("holdingSortDirection", sortDirection);
    const query = params.toString();
    window.history.replaceState({}, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
  }, [sortDirection, sortKey]);

  useEffect(() => {
    function onPopState() {
      const next = readHoldingSort();
      setSort(next.key, next.direction);
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  function header(key: HoldingSortKey, label: ReactNode) {
    const Icon = sortKey !== key ? ChevronsUpDown : sortDirection === "asc" ? ChevronUp : ChevronDown;
    return <button type="button" className="sortableHeader" onClick={() => toggleSort(key)}>{label}<Icon size={12} /></button>;
  }

  return (
    <div className="holdingsTable" role="table" aria-label="Investment holdings">
      <div className="holdingsHeader" role="row"><span>Select</span><span>{header("institution", "Institution")}</span><span>{header("account", "Account")}</span><span>{header("symbol", "Symbol")}</span><span>Description</span><span>{header("quantity", "Quantity")}</span><span>{header("price", "Price")}</span><span>{header("value", "Value")}</span><span>{header("basis", "Basis")}</span><span>{header("gain", "Gain/loss")}</span><span>{header("age", "Lot age")}</span><span>Actions</span></div>
      {sortedRows.map((row) => <div className={props.selectedIds.includes(row.id) ? "holdingsRow selected" : "holdingsRow"} role="row" key={row.id}>
        <input type="checkbox" checked={props.selectedIds.includes(row.id)} onChange={(event) => props.onToggleSelection(row.id, visibleIds, (event.nativeEvent as MouseEvent).shiftKey)} title="Select holding. Hold Shift to select a range." />
        <span>{row.institution || "—"}</span><span>{row.account}</span><strong>{row.symbol || "Holding"}</strong>
        <div className="holdingDescriptionEdit"><input defaultValue={row.user_description ?? row.csv_description ?? ""} onBlur={(event) => void updateIfChanged(row, event.currentTarget.value, props.onUpdateDescription)} placeholder="Add your description" />{row.csv_description ? <small>CSV: {row.csv_description}</small> : null}</div>
        <span>{row.quantity ?? "—"}</span><span title={`Price as of ${props.formatDate(row.price_date)}`}>{row.display_price_cents == null ? "—" : props.formatMoney(row.display_price_cents)}</span><span>{props.formatMoney(row.display_market_value_cents)}</span>
        <span>{row.cost_basis_cents == null ? "—" : props.formatMoney(row.cost_basis_cents)}</span><strong className={row.unrealized_gain_loss_cents != null && row.unrealized_gain_loss_cents < 0 ? "amount negative" : "amount positive"}>{row.unrealized_gain_loss_cents == null ? "—" : props.formatMoney(row.unrealized_gain_loss_cents)}</strong>
        <span title={row.oldest_acquisition_date ? `Oldest lot acquired ${props.formatDate(row.oldest_acquisition_date)}` : undefined}>{formatLotAge(row.lot_age_days, row.lot_count)}</span>
        <span className="holdingRowActions"><button className="secondaryButton compactButton" onClick={() => props.onManageLots(row)}>Lots</button><button className="dangerTextButton" onClick={() => props.onRequestDelete(row)}>Delete</button></span>
      </div>)}
      {sortedRows.length > 0 ? <div className="holdingsTotalRow" role="row"><span /><strong>Total</strong><span /><span /><span /><span /><span /><strong>{props.formatMoney(totals.marketValueCents)}</strong><strong>{totals.costBasisCents === null ? "—" : props.formatMoney(totals.costBasisCents)}</strong><strong className={totals.gainLossCents !== null && totals.gainLossCents < 0 ? "amount negative" : "amount positive"}>{totals.gainLossCents === null ? "—" : props.formatMoney(totals.gainLossCents)}</strong><span /><span /></div> : null}
      {sortedRows.length === 0 ? <p className="emptyText">No holdings rows to inspect yet.</p> : null}
    </div>
  );
}

function readHoldingSort(): { key: HoldingSortKey; direction: SortDirection } {
  const params = new URLSearchParams(window.location.search);
  const requested = params.get("holdingSort") as HoldingSortKey | null;
  return {
    key: requested && holdingSortKeys.has(requested) ? requested : "symbol",
    direction: params.get("holdingSortDirection") === "desc" ? "desc" : "asc",
  };
}

export function sortHoldingRows(rows: HoldingRow[], key: HoldingSortKey, direction: SortDirection) {
  const multiplier = direction === "asc" ? 1 : -1;
  return [...rows].sort((left, right) => {
    const values: Record<HoldingSortKey, [string | number | null, string | number | null]> = {
      institution: [left.institution, right.institution], account: [left.account, right.account], symbol: [left.symbol, right.symbol], quantity: [left.quantity, right.quantity], price: [left.display_price_cents, right.display_price_cents], value: [left.display_market_value_cents, right.display_market_value_cents], basis: [left.cost_basis_cents, right.cost_basis_cents], gain: [left.unrealized_gain_loss_cents, right.unrealized_gain_loss_cents], age: [left.lot_age_days, right.lot_age_days],
    };
    const [a, b] = values[key];
    if (a == null && b == null) return left.id - right.id;
    if (a == null) return 1;
    if (b == null) return -1;
    const compared = typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b), undefined, { sensitivity: "base", numeric: true });
    return compared === 0 ? left.id - right.id : compared * multiplier;
  });
}

export function holdingTotals(rows: HoldingRow[]) {
  const rowsWithBasis = rows.filter((row) => row.cost_basis_cents !== null);
  return {
    marketValueCents: rows.reduce((sum, row) => sum + row.display_market_value_cents, 0),
    costBasisCents: rowsWithBasis.length === rows.length ? rowsWithBasis.reduce((sum, row) => sum + (row.cost_basis_cents ?? 0), 0) : null,
    gainLossCents: rowsWithBasis.length === rows.length ? rows.reduce((sum, row) => sum + (row.unrealized_gain_loss_cents ?? 0), 0) : null,
  };
}

async function updateIfChanged(row: HoldingRow, nextDescription: string, onUpdate: (symbol: string | null, userDescription: string) => Promise<void>) {
  const previous = row.user_description ?? row.csv_description ?? "";
  if (nextDescription.trim() !== previous.trim()) await onUpdate(row.symbol, nextDescription);
}

export function formatLotAge(days: number | null, lotCount: number) {
  if (days == null || lotCount === 0) return "—";
  if (days < 365) return `${days}d / ${lotCount} lot${lotCount === 1 ? "" : "s"}`;
  return `${(days / 365.25).toFixed(1)}y / ${lotCount} lot${lotCount === 1 ? "" : "s"}`;
}
