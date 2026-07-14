import { describe, expect, it } from "vitest";
import { transactionTypeUsesCategory } from "./transactionTypes";

describe("transaction type categories", () => {
  it("keeps transfers and card payments categoryless", () => {
    expect(transactionTypeUsesCategory("transfer")).toBe(false);
    expect(transactionTypeUsesCategory("credit_card_payment")).toBe(false);
  });

  it("requires categories for reportable spending", () => {
    expect(transactionTypeUsesCategory("expense")).toBe(true);
    expect(transactionTypeUsesCategory("refund")).toBe(true);
  });
});
