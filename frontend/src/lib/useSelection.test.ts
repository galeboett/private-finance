import { describe, expect, it } from "vitest";

import { nextSelection } from "./useSelection";

describe("nextSelection", () => {
  const visible = [11, 12, 13, 14, 15];

  it("toggles a single row without Shift", () => {
    expect(nextSelection([], 12, visible, false, null)).toEqual([12]);
    expect(nextSelection([12], 12, visible, false, 12)).toEqual([]);
  });

  it("adds the inclusive range between the anchor and Shift-clicked row", () => {
    expect(nextSelection([12], 15, visible, true, 12)).toEqual([12, 13, 14, 15]);
    expect(nextSelection([15], 12, visible, true, 15)).toEqual([15, 12, 13, 14]);
  });

  it("falls back to a single toggle when the anchor is not visible", () => {
    expect(nextSelection([99], 13, visible, true, 99)).toEqual([99, 13]);
  });
});
