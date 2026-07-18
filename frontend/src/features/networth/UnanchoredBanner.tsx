import { AlertTriangle, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

export type UnanchoredAccount = { id: number; name: string };

export function UnanchoredBanner({ accounts, onChoose }: { accounts: UnanchoredAccount[]; onChoose: (accountId: number) => void }) {
  const [open, setOpen] = useState(false);
  const popoverId = useId();
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  if (accounts.length === 0) return null;
  return (
    <div className="unanchoredAlert" ref={rootRef}>
      <button
        className="unanchoredAlertTrigger"
        type="button"
        aria-label={`${accounts.length} account${accounts.length === 1 ? " is" : "s are"} excluded from net worth. View details.`}
        aria-expanded={open}
        aria-controls={popoverId}
        aria-haspopup="dialog"
        title={`${accounts.length} account${accounts.length === 1 ? " is" : "s are"} excluded from net worth`}
        onClick={() => setOpen((current) => !current)}
      >
        <AlertTriangle size={18} aria-hidden="true" />
        <span>{accounts.length}</span>
      </button>
      {open ? (
        <section className="unanchoredPopover" id={popoverId} role="dialog" aria-label="Accounts excluded from net worth">
          <header>
            <div>
              <span className="eyebrow">Net worth alert</span>
              <strong>{accounts.length} account{accounts.length === 1 ? " is" : "s are"} excluded</strong>
            </div>
            <button className="ghostButton compactIconButton" type="button" aria-label="Close net worth alert" onClick={() => setOpen(false)}><X size={16} /></button>
          </header>
          <p>Add a statement balance to anchor {accounts.length === 1 ? "this account" : "these accounts"}. Lifetime transaction history is not treated as a current balance.</p>
          <div className="unanchoredAccountList">
            {accounts.map((account) => (
              <button className="ghostButton" type="button" key={account.id} onClick={() => { setOpen(false); onChoose(account.id); }}>
                <span>{account.name}</span><span aria-hidden="true">›</span>
              </button>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
