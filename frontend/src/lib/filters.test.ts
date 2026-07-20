import { describe, expect, it } from "vitest";

import { decodeTxnFilter, encodeTxnFilter, freshAccountNavigationFilter, isMonthInReportPeriod, isTransactionInReportPeriod, readAppRoute, routeUrl, type TxnFilter } from "./filters";

describe("transaction filter URL codec", () => {
  it("round-trips every supported non-default filter", () => {
    const filter: TxnFilter = {
      accounts: ["12", "4"], categories: ["8"], tags: ["tax", "shared"], months: ["2026-06"], years: ["2025", "2026"],
      dateFrom: "2026-01-02", dateTo: "2026-07-13", dateBasis: "reporting", amountMin: 125, amountMax: 50000,
      direction: "outflow", types: ["expense", "refund"], search: "coffee shop", view: "trash", sort: "amount",
      sortDirection: "asc", netWorthPeriod: "1Y", hasRefund: true, holdingSort: "gain", holdingSortDirection: "desc", reportTab: "Net Worth",
    };
    expect(decodeTxnFilter(encodeTxnFilter(filter))).toEqual(filter);
  });

  it("ignores removed report-tab aliases", () => {
    expect(decodeTxnFilter(new URLSearchParams("tab=Income"))).toEqual({});
    expect(encodeTxnFilter({ reportTab: "Overview" }).toString()).toBe("");
  });

  it("omits defaults while preserving their effective decode behavior", () => {
    const params = encodeTxnFilter({ dateBasis: "transaction", view: "live", sort: "date", sortDirection: "desc", netWorthPeriod: "6M", search: "   " });
    expect(params.toString()).toBe("");
    expect(decodeTxnFilter(params)).toEqual({});
  });

  it("normalizes duplicate list entries and rejects invalid numbers", () => {
    expect(decodeTxnFilter(new URLSearchParams("accounts=3,3,%204&amountMin=-1&amountMax=not-a-number"))).toEqual({ accounts: ["3", "4"] });
  });

  it("keeps account routes and filters bookmarkable", () => {
    const url = routeUrl("account", 42, { dateFrom: "2026-07-01", types: ["expense"] });
    const parsed = new URL(url, "http://localhost");
    expect(url).toBe("/accounts/42/transactions?types=expense&dateFrom=2026-07-01");
    expect(readAppRoute(parsed)).toEqual({ view: "account", accountId: 42, filters: { dateFrom: "2026-07-01", types: ["expense"] } });
  });

  it("resets filters for left-nav account intent while drill-down filters stay intact", () => {
    const investigation: TxnFilter = { accounts: ["4"], search: "PAYMENT FROM CHK", dateFrom: "2026-05-21", dateTo: "2026-05-21", types: ["credit_card_payment"] };
    expect(freshAccountNavigationFilter(12)).toEqual({ accounts: ["12"] });
    expect(routeUrl("account", 12, freshAccountNavigationFilter(12))).toBe("/accounts/12/transactions?accounts=12");
    expect(decodeTxnFilter(encodeTxnFilter(investigation))).toEqual(investigation);
  });
});

describe("report-period predicates", () => {
  const now = new Date(2026, 6, 15);

  it("keeps transaction and monthly rows on the same last-12-month boundary", () => {
    expect(isTransactionInReportPeriod("2025-08-01", "last_12_months", now)).toBe(true);
    expect(isMonthInReportPeriod("2025-08", "last_12_months", now)).toBe(true);
    expect(isTransactionInReportPeriod("2025-07-31", "last_12_months", now)).toBe(false);
    expect(isMonthInReportPeriod("2025-07", "last_12_months", now)).toBe(false);
  });
});
