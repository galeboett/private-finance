import { describe, expect, it } from "vitest";

import { belongsInReviewQueue, filterReviewQueue, isUncategorizedRefund } from "./reviewQueue";

const rows = [
  { id: 1, transaction_type: "expense", review_status: "needs_review", category_id: null },
  { id: 2, transaction_type: "refund", review_status: "confirmed", category_id: null },
  { id: 3, transaction_type: "refund", review_status: "confirmed", category_id: 7 },
  { id: 4, transaction_type: "refund", review_status: "suggested", category_id: null },
];

describe("refund review queue", () => {
  it("keeps confirmed refunds visible until they receive a category", () => {
    expect(isUncategorizedRefund(rows[1])).toBe(true);
    expect(belongsInReviewQueue(rows[1])).toBe(true);
    expect(belongsInReviewQueue(rows[2])).toBe(false);
  });

  it("filters to uncategorized refunds and still excludes duplicate candidates", () => {
    expect(filterReviewQueue(rows, new Set([4]), "uncategorized_refunds").map((row) => row.id)).toEqual([2]);
  });
});
