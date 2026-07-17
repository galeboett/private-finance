import { describe, expect, it } from "vitest";
import { apiQueryKey } from "./hooks";

describe("API query keys", () => {
  it("keeps filtered reads distinct inside a shared invalidation family", () => {
    expect(apiQueryKey("/api/transactions?account_id=1")).toEqual(["transactions", "/api/transactions?account_id=1"]);
    expect(apiQueryKey("/api/transactions?account_id=2")).toEqual(["transactions", "/api/transactions?account_id=2"]);
  });

  it("groups linked relationship reads for targeted invalidation", () => {
    expect(apiQueryKey("/api/refunds/suggestions")[0]).toBe("refunds");
    expect(apiQueryKey("/api/refund-links/9")[0]).toBe("refunds");
    expect(apiQueryKey("/api/snapshots/networth?from=2026-01-01")[0]).toBe("net-worth");
    expect(apiQueryKey("/api/aggregate/by-category?date_from=2026-01-01")[0]).toBe("aggregates");
  });
});
