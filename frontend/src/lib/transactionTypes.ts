const CATEGORYLESS_TYPES = new Set(["transfer", "credit_card_payment"]);

export function transactionTypeUsesCategory(transactionType: string): boolean {
  return !CATEGORYLESS_TYPES.has(transactionType);
}
