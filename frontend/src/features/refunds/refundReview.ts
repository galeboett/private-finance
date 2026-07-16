export type RefundSelectionInput = {
  refund_transaction: { id: number };
  candidates: Array<{ expense_transaction: { id: number } }>;
};

export function selectedRefundMatches(
  suggestions: RefundSelectionInput[],
  selectedRefundIds: number[],
  candidateIndexByRefund: Record<number, number>,
) {
  return suggestions
    .filter((group) => selectedRefundIds.includes(group.refund_transaction.id))
    .flatMap((group) => {
      const requestedIndex = candidateIndexByRefund[group.refund_transaction.id] ?? 0;
      const index = Math.min(requestedIndex, Math.max(0, group.candidates.length - 1));
      const candidate = group.candidates[index];
      return candidate ? [{ refund_transaction_id: group.refund_transaction.id, expense_transaction_id: candidate.expense_transaction.id }] : [];
    });
}
