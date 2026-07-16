import { describe, expect, it } from "vitest";

import { selectedRefundMatches } from "./refundReview";

describe("selectedRefundMatches", () => {
  it("uses custom numbered choices and defaults untouched refunds to the first recommendation", () => {
    const suggestions = [
      { refund_transaction: { id: 10 }, candidates: [{ expense_transaction: { id: 101 } }, { expense_transaction: { id: 102 } }] },
      { refund_transaction: { id: 20 }, candidates: [{ expense_transaction: { id: 201 } }, { expense_transaction: { id: 202 } }, { expense_transaction: { id: 203 } }, { expense_transaction: { id: 204 } }] },
      { refund_transaction: { id: 30 }, candidates: [{ expense_transaction: { id: 301 } }, { expense_transaction: { id: 302 } }] },
    ];

    expect(selectedRefundMatches(suggestions, [10, 20, 30], { 10: 1, 20: 3 })).toEqual([
      { refund_transaction_id: 10, expense_transaction_id: 102 },
      { refund_transaction_id: 20, expense_transaction_id: 204 },
      { refund_transaction_id: 30, expense_transaction_id: 301 },
    ]);
  });
});
