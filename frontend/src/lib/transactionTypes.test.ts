import { describe, expect, it } from "vitest";

import { transactionTypeRequiresCategory, transactionTypeUsesCategory } from "./transactionTypes";

describe("transaction category behavior", () => {
  it("allows refund categories and requires one before confirmation", () => {
    expect(transactionTypeUsesCategory("expense")).toBe(true);
    expect(transactionTypeRequiresCategory("expense")).toBe(true);
    expect(transactionTypeUsesCategory("refund")).toBe(true);
    expect(transactionTypeRequiresCategory("refund")).toBe(true);
  });

  it("keeps transfer and card payment rows categoryless", () => {
    expect(transactionTypeUsesCategory("transfer")).toBe(false);
    expect(transactionTypeUsesCategory("credit_card_payment")).toBe(false);
    expect(transactionTypeRequiresCategory("credit_card_payment")).toBe(false);
  });
});
