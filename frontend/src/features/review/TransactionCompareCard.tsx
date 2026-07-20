export type DuplicateTransaction = {
  id: number;
  import_batch_id: number | null;
  account_id: number;
  account: string;
  institution: string | null;
  account_last_four: string | null;
  reference: string | null;
  date: string;
  posted_date: string | null;
  amount: number;
  amount_cents: number;
  description: string;
  category_id: number | null;
  category: string | null;
  notes: string | null;
  labels: string | null;
  import_source: string;
};

type Props = {
  title: string;
  transaction: DuplicateTransaction;
  diffFields: string[];
  emphasis?: "original" | "candidate";
};

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

function accountLabel(transaction: DuplicateTransaction) {
  const suffix = transaction.account_last_four && !transaction.account.endsWith(transaction.account_last_four) ? ` (${transaction.account_last_four})` : "";
  return `${transaction.institution ? `${transaction.institution} · ` : ""}${transaction.account}${suffix}`;
}

export function TransactionCompareCard({ title, transaction, diffFields, emphasis = "candidate" }: Props) {
  const different = new Set(diffFields);
  const rows: Array<{ key: string; label: string; value: string }> = [
    { key: "account", label: "Account", value: accountLabel(transaction) },
    { key: "reference", label: "Reference", value: transaction.reference || "None" },
    { key: "date", label: "Date", value: transaction.date },
    { key: "amount", label: "Amount", value: money.format(transaction.amount_cents / 100) },
    { key: "category", label: "Category", value: transaction.category || "Uncategorized" },
    { key: "notes", label: "Notes", value: transaction.notes || "None" },
    { key: "labels", label: "Labels", value: transaction.labels || "None" },
    { key: "import_source", label: "Import source", value: transaction.import_source },
  ];
  return (
    <article className={`transactionCompareCard ${emphasis}`}>
      <div className="transactionCompareHeader"><small>{title}</small><strong>{transaction.description}</strong></div>
      <dl>
        {rows.map((row) => (
          <div className={different.has(row.key) ? "compareField different" : "compareField"} key={row.key}>
            <dt>{row.label}</dt><dd>{row.value}</dd>
          </div>
        ))}
      </dl>
    </article>
  );
}
