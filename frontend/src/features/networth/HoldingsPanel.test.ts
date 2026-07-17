import { describe, expect, it } from "vitest";
import { formatLotAge, holdingTotals, sortHoldingRows, type HoldingRow } from "./HoldingsTable";

describe("holding lot age", () => {
  it("shows days for recent lots and years for older lots", () => {
    expect(formatLotAge(90, 1)).toBe("90d / 1 lot");
    expect(formatLotAge(730, 2)).toBe("2.0y / 2 lots");
  });

  it("does not imply basis exists without lots", () => {
    expect(formatLotAge(null, 0)).toBe("—");
  });

  it("sorts nulls last and keeps deterministic ordering", () => {
    const rows = [holding(2, "VTI", 200), holding(1, "AMZN", 100), { ...holding(3, "CASH", 50), cost_basis_cents: null }];
    expect(sortHoldingRows(rows, "symbol", "asc").map((row) => row.symbol)).toEqual(["AMZN", "CASH", "VTI"]);
    expect(sortHoldingRows(rows, "basis", "desc").map((row) => row.id)).toEqual([2, 1, 3]);
  });

  it("totals value, basis, and gain only when basis is complete", () => {
    const complete = [holding(1, "A", 100), holding(2, "B", 200)];
    expect(holdingTotals(complete)).toEqual({ marketValueCents: 300, costBasisCents: 240, gainLossCents: 60 });
    expect(holdingTotals([{ ...complete[0], cost_basis_cents: null, unrealized_gain_loss_cents: null }, complete[1]])).toEqual({ marketValueCents: 300, costBasisCents: null, gainLossCents: null });
  });
});

function holding(id: number, symbol: string, value: number): HoldingRow {
  return { id, account_id: 1, account: "Brokerage", institution: "Bank", snapshot_date: "2026-07-16", symbol, description: null, csv_description: null, user_description: null, quantity: 1, price_cents: value, display_price_cents: value, price_date: "2026-07-16", market_value_cents: value, display_market_value_cents: value, asset_class: null, lot_count: 1, lot_quantity: 1, cost_basis_cents: value * 0.8, unrealized_gain_loss_cents: value * 0.2, oldest_acquisition_date: "2025-07-16", lot_age_days: 365 };
}
