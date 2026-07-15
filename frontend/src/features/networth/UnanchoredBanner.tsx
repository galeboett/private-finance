import { AlertTriangle } from "lucide-react";

export type UnanchoredAccount = { id: number; name: string };

export function UnanchoredBanner({ accounts, onChoose }: { accounts: UnanchoredAccount[]; onChoose: (accountId: number) => void }) {
  if (accounts.length === 0) return null;
  return (
    <section className="unanchoredBanner" role="status">
      <AlertTriangle size={18} />
      <div>
        <strong>{accounts.length} account{accounts.length === 1 ? " is" : "s are"} excluded from net worth</strong>
        <span>Add a statement balance to anchor {accounts.length === 1 ? "it" : "them"}. Lifetime transaction history is not treated as a current balance.</span>
        <div className="buttonRow">
          {accounts.map((account) => <button className="ghostButton compactButton" type="button" key={account.id} onClick={() => onChoose(account.id)}>{account.name}</button>)}
        </div>
      </div>
    </section>
  );
}
