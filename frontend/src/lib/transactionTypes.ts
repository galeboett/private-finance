const CATEGORYLESS_TYPES = new Set(["transfer", "credit_card_payment"]);
const CATEGORY_REQUIRED_TYPES = new Set(["expense", "refund"]);

export function transactionTypeUsesCategory(transactionType: string): boolean {
  return !CATEGORYLESS_TYPES.has(transactionType);
}

export function transactionTypeRequiresCategory(transactionType: string): boolean {
  return CATEGORY_REQUIRED_TYPES.has(transactionType);
}
