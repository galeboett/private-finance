import { describe, expect, it } from "vitest";

import { monthGrid, relativeDateRange } from "./DateRangePicker";

describe("custom date ranges", () => {
  it("builds inclusive relative shortcuts", () => {
    const now = new Date(2026, 6, 16);
    expect(relativeDateRange("last_30", now)).toEqual({ dateFrom: "2026-06-17", dateTo: "2026-07-16" });
    expect(relativeDateRange("last_90", now)).toEqual({ dateFrom: "2026-04-18", dateTo: "2026-07-16" });
    expect(relativeDateRange("last_365", now)).toEqual({ dateFrom: "2025-07-17", dateTo: "2026-07-16" });
    expect(relativeDateRange("ytd", now)).toEqual({ dateFrom: "2026-01-01", dateTo: "2026-07-16" });
    expect(relativeDateRange("quarter", now)).toEqual({ dateFrom: "2026-07-01", dateTo: "2026-07-16" });
  });

  it("builds a calendar grid with weekday padding", () => {
    const july = monthGrid("2026-07");
    expect(july.slice(0, 3)).toEqual([null, null, null]);
    expect(july.at(-1)).toBe("2026-07-31");
  });
});
