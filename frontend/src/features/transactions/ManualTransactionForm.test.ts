import { describe, expect, it } from "vitest";
import { canonicalManualAmountCents, parseManualLabels } from "./ManualTransactionForm";

describe("manual transaction normalization", () => {
  it("writes canonical signs from the direction choice", () => {
    expect(canonicalManualAmountCents(42.5, "out")).toBe(-4250);
    expect(canonicalManualAmountCents(-42.5, "in")).toBe(4250);
  });

  it("turns comma-separated labels into clean values", () => {
    expect(parseManualLabels("travel, reimbursable,  ")).toEqual(["travel", "reimbursable"]);
  });
});
