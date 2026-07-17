export type DeleteTarget =
  | { kind: "transaction"; id: number; label: string }
  | { kind: "transaction_bulk"; ids: number[]; label: string }
  | { kind: "transaction_permanent"; id: number; label: string }
  | { kind: "transaction_bulk_permanent"; ids: number[]; label: string }
  | { kind: "account"; id: number; label: string }
  | { kind: "account_bulk"; ids: number[]; label: string }
  | { kind: "holding"; id: number; label: string }
  | { kind: "holding_bulk"; ids: number[]; label: string }
  | { kind: "holding_lot"; id: number; label: string }
  | { kind: "net_worth_snapshot"; id: number; label: string };

export function DeleteConfirmInline({
  target,
  confirmText,
  onConfirmTextChange,
  onConfirm,
  onCancel,
}: {
  target: DeleteTarget;
  confirmText: string;
  onConfirmTextChange: (value: string) => void;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}) {
  const isBulk = target.kind.includes("bulk");
  const isPermanent = target.kind.includes("permanent");
  const isAccount = target.kind === "account" || target.kind === "account_bulk";
  const isHolding = target.kind === "holding" || target.kind === "holding_bulk" || target.kind === "holding_lot" || target.kind === "net_worth_snapshot";
  return (
    <section className="deleteConfirmPanel inlineDeleteConfirm">
      <div>
        <strong>{isPermanent ? `Permanently delete ${isBulk ? "these transactions" : "this transaction"}?` : isBulk ? "Delete selected items?" : target.kind === "account" ? "Delete this account?" : isHolding ? "Delete this asset record?" : "Move this row to Trash?"}</strong>
        <span>{target.label}</span>
        <small>{isPermanent ? "This cannot be undone. The transaction and its related split or allocation data will be removed." : isAccount ? "Deleting an account keeps its transactions and returns them to Review for account selection. Holdings, lots, presets, and import history are removed; audit history remains." : isHolding ? "This asset record can be restored immediately with Undo." : "The transaction can be restored from Trash or immediately with Undo."}</small>
      </div>
      <input value={confirmText} onChange={(event) => onConfirmTextChange(event.target.value)} placeholder="Type DELETE to confirm" />
      <div className="buttonRow">
        <button className="dangerButton" onClick={() => void onConfirm()} disabled={confirmText !== "DELETE"}>Delete</button>
        <button className="secondaryButton" onClick={onCancel}>Cancel</button>
      </div>
    </section>
  );
}
