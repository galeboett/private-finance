import { useState, type FormEvent } from "react";
import { api } from "../../api/client";

export type ManualTransactionAccount = { id: number; display_name: string; account_type: string };
export type ManualTransactionCategory = { id: number; label: string };

type Props = {
  accounts: ManualTransactionAccount[];
  categories: ManualTransactionCategory[];
  csrf: string;
  defaultAccountId?: number;
  onSaved: (operationId: string) => Promise<void>;
  onError: (message: string) => void;
  onCancel?: () => void;
};

export function ManualTransactionForm({ accounts, categories, csrf, defaultAccountId, onSaved, onError, onCancel }: Props) {
  const [accountId, setAccountId] = useState<number | "">(defaultAccountId ?? accounts[0]?.id ?? "");
  const [transactionDate, setTransactionDate] = useState(todayInputValue());
  const [direction, setDirection] = useState<"out" | "in">("out");
  const [amount, setAmount] = useState("");
  const [categoryId, setCategoryId] = useState<number | "">("");
  const [description, setDescription] = useState("");
  const [labels, setLabels] = useState("");
  const [saving, setSaving] = useState(false);
  const selectedAccount = accounts.find((account) => account.id === accountId);
  const assetAccount = selectedAccount?.account_type === "brokerage" || selectedAccount?.account_type === "retirement";

  async function submit(event: FormEvent) {
    event.preventDefault();
    const dollars = Number(amount.replace(/[$,\s]/g, ""));
    if (!accountId || !transactionDate || !description.trim() || !Number.isFinite(dollars) || dollars <= 0) {
      onError("Choose an account and enter a date, positive amount, and description.");
      return;
    }
    if (direction === "out" && !assetAccount && !categoryId) {
      onError("Choose a category for money out.");
      return;
    }
    setSaving(true);
    try {
      const result = await api<{ operation_id: string }>("/api/transactions/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-csrf-token": csrf },
        body: JSON.stringify({
          account_id: accountId,
          transaction_date: transactionDate,
          amount_cents: canonicalManualAmountCents(dollars, direction),
          category_id: assetAccount ? null : categoryId || null,
          description: description.trim(),
          labels: parseManualLabels(labels),
        }),
      });
      setAmount("");
      setDescription("");
      setLabels("");
      await onSaved(result.operation_id);
      onCancel?.();
    } catch (error) {
      onError(error instanceof Error ? error.message : "Transaction could not be added.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="manualTransactionForm" onSubmit={submit}>
      <div className="manualFormTitle"><strong>Add transaction</strong><span>Enter money out or money in; the ledger stores the correct sign automatically.</span></div>
      <label>Account<select value={accountId} onChange={(event) => { setAccountId(Number(event.target.value) || ""); setCategoryId(""); }} required><option value="">Choose account</option>{accounts.map((account) => <option key={account.id} value={account.id}>{account.display_name}</option>)}</select></label>
      <label>Date<input type="date" value={transactionDate} onChange={(event) => setTransactionDate(event.target.value)} required /></label>
      <label>Direction<select value={direction} onChange={(event) => setDirection(event.target.value as "out" | "in")}><option value="out">Money out</option><option value="in">Money in</option></select></label>
      <label>Amount<input inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="0.00" required /></label>
      <label>Category<select value={categoryId} disabled={assetAccount} onChange={(event) => setCategoryId(Number(event.target.value) || "")} required={direction === "out" && !assetAccount}><option value="">{assetAccount ? "No category needed" : direction === "out" ? "Choose category" : "Optional category"}</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.label}</option>)}</select></label>
      <label className="manualDescriptionField">Description<input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What was this for?" required /></label>
      <label>Labels<input value={labels} onChange={(event) => setLabels(event.target.value)} placeholder="travel, reimbursable" /></label>
      <div className="buttonRow"><button className="primaryButton" disabled={saving}>{saving ? "Saving..." : "Add transaction"}</button>{onCancel ? <button type="button" className="secondaryButton" onClick={onCancel}>Cancel</button> : null}</div>
    </form>
  );
}

function todayInputValue() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

export function canonicalManualAmountCents(dollars: number, direction: "out" | "in") {
  return Math.round(Math.abs(dollars) * 100) * (direction === "out" ? -1 : 1);
}

export function parseManualLabels(value: string) {
  return value.split(",").map((label) => label.trim()).filter(Boolean);
}
