import { useState } from "react";
import { useApiClient } from "../../api/hooks";

export type ExternalAccountOption = { id: number; display_name: string };

export function ExternalPaymentAction({ transactionId, accounts, csrf, onSettled, onError }: {
  transactionId: number;
  accounts: ExternalAccountOption[];
  csrf: string;
  onSettled: (operationId: string) => Promise<void>;
  onError: (message: string) => void;
}) {
  const api = useApiClient();
  const [open, setOpen] = useState(false);
  const [accountId, setAccountId] = useState<number | "">(accounts[0]?.id ?? "");
  const [newName, setNewName] = useState("External");
  const [saving, setSaving] = useState(false);

  async function settle() {
    if (!accountId && !newName.trim()) {
      onError("Choose an untracked account or enter a name.");
      return;
    }
    setSaving(true);
    try {
      const result = await api<{ operation_id: string }>(`/api/transfers/payments/${transactionId}/external`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-csrf-token": csrf },
        body: JSON.stringify(accountId ? { external_account_id: accountId } : { external_account_name: newName.trim() }),
      });
      await onSettled(result.operation_id);
      setOpen(false);
    } catch (error) {
      onError(error instanceof Error ? error.message : "The external payment could not be recorded.");
    } finally {
      setSaving(false);
    }
  }

  if (!open) return <button className="ghostButton compactButton" type="button" onClick={() => setOpen(true)}>Paid from untracked account</button>;
  return (
    <div className="externalPaymentAction">
      <select value={accountId} onChange={(event) => setAccountId(event.target.value ? Number(event.target.value) : "")} aria-label="Untracked payment account">
        <option value="">Create a new untracked account</option>
        {accounts.map((account) => <option key={account.id} value={account.id}>{account.display_name}</option>)}
      </select>
      {!accountId ? <input value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="Account name" aria-label="New untracked account name" /> : null}
      <button className="secondaryButton compactButton" type="button" disabled={saving} onClick={() => void settle()}>{saving ? "Saving…" : "Confirm"}</button>
      <button className="ghostButton compactButton" type="button" disabled={saving} onClick={() => setOpen(false)}>Cancel</button>
    </div>
  );
}
