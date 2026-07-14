import { describe, expect, it } from "vitest";
import { formatLotAge } from "./HoldingsPanel";

describe("holding lot age", () => {
  it("shows days for recent lots and years for older lots", () => {
    expect(formatLotAge(90, 1)).toBe("90d / 1 lot");
    expect(formatLotAge(730, 2)).toBe("2.0y / 2 lots");
  });

  it("does not imply basis exists without lots", () => {
    expect(formatLotAge(null, 0)).toBe("-");
  });
});
