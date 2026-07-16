export type ReviewQueueFilter = "all" | "uncategorized_refunds";

type ReviewQueueRow = {
  id: number;
  transaction_type: string;
  review_status: string;
  category_id: number | null;
};

const OPEN_REVIEW_STATUSES = new Set(["needs_review", "suggested", "possible_duplicate"]);

export function isUncategorizedRefund(transaction: ReviewQueueRow): boolean {
  return transaction.transaction_type === "refund" && transaction.category_id === null;
}

export function belongsInReviewQueue(transaction: ReviewQueueRow): boolean {
  return OPEN_REVIEW_STATUSES.has(transaction.review_status) || isUncategorizedRefund(transaction);
}

export function filterReviewQueue<T extends ReviewQueueRow>(rows: T[], duplicateCandidateIds: Set<number>, filter: ReviewQueueFilter): T[] {
  return rows.filter((transaction) => (
    belongsInReviewQueue(transaction)
    && !duplicateCandidateIds.has(transaction.id)
    && (filter === "all" || isUncategorizedRefund(transaction))
  ));
}
