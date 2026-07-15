import { AlertCircle, CheckCircle2, X, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useRef } from "react";

import type { TxnFilter } from "../lib/filters";
import { useDrillDown } from "../lib/useDrillDown";

type Toast = { tone: "success" | "error" | "info"; message: string; operationId?: string; unconflictedOnly?: boolean; action?: { label: string } };
type FilterOption = { value: string; label: string };

export function UndoToast({ toast, busy, onUndo, onAction, onDismiss }: { toast: Toast; busy: boolean; onUndo: (operationId: string, unconflictedOnly: boolean) => void; onAction?: () => void; onDismiss: () => void }) {
  return <div className={`toast ${toast.tone}`} style={{ margin: "16px 20px 0" }} role="status" aria-live="polite">
    {toast.tone === "success" ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
    <span>{toast.message}</span>
    {toast.action && onAction ? <button className="toastAction primary" onClick={onAction}>{toast.action.label}</button> : null}
    {toast.operationId ? <button className="toastAction" onClick={() => onUndo(toast.operationId!, Boolean(toast.unconflictedOnly))} disabled={busy}>{toast.unconflictedOnly ? "Undo safe rows" : "Undo"}</button> : null}
    <button className="toastClose" onClick={onDismiss} aria-label="Dismiss notification"><X size={14} /></button>
  </div>;
}

export function BulkActionBar({ count, detail, onClear, children }: { count: number; detail: string; onClear: () => void; children: ReactNode }) {
  return <div className="bulkSelectionBar"><div className="bulkSelectionContext"><div><strong>{count} selected</strong><span>{detail}</span></div></div>{children}<button className="ghostButton compactButton" onClick={onClear}>Clear</button></div>;
}

export function DrillDownLink({ filter, title, count, className, onPeek, children }: { filter: TxnFilter; title: string; count?: number; className?: string; onPeek: (filter: TxnFilter, title: string) => void; children: ReactNode }) {
  const drillDown = useDrillDown(filter, title, onPeek);
  return <a className={className ? `drillDownLink ${className}` : "drillDownLink"} href={drillDown.href} onClick={drillDown.onClick} title={`Click to preview${count === undefined ? " matching" : ` ${count}`} transaction${count === 1 ? "" : "s"}`}>{children}</a>;
}

export function MultiSelectFilter({ label, options, selectedValues, onToggle, onSelectAll, onDeselectAll }: { label: string; options: FilterOption[]; selectedValues: string[]; onToggle: (value: string) => void; onSelectAll: () => void; onDeselectAll: () => void }) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const selectedCount = selectedValues.length;
  const summary = selectedCount === options.length ? "All" : selectedCount === 0 ? "None" : `${selectedCount} selected`;
  useEffect(() => {
    function closeOnOutsideClick(event: PointerEvent) {
      if (detailsRef.current?.open && !detailsRef.current.contains(event.target as Node)) detailsRef.current.open = false;
    }
    document.addEventListener("pointerdown", closeOnOutsideClick);
    return () => document.removeEventListener("pointerdown", closeOnOutsideClick);
  }, []);
  return <details className="multiFilter" ref={detailsRef}><summary><span>{label}</span><strong>{summary}</strong></summary><div className="multiFilterMenu"><div className="multiFilterActions"><button type="button" className="ghostButton" onClick={onSelectAll}>Select all</button><button type="button" className="ghostButton" onClick={onDeselectAll}>Deselect all</button></div><div className="multiFilterOptions">{options.map((option) => <label key={option.value}><input type="checkbox" checked={selectedValues.includes(option.value)} onChange={() => onToggle(option.value)} /><span>{option.label}</span></label>)}{options.length === 0 ? <span className="emptyText">No options yet.</span> : null}</div></div></details>;
}

export function PanelTitle({ icon: Icon, title, subtitle }: { icon: LucideIcon; title: string; subtitle: string }) {
  return <div className="panelTitle"><Icon size={18} /><div><h3>{title}</h3><p>{subtitle}</p></div></div>;
}

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

export function CashFlowGraphic({ income, expenses, net }: { income: number; expenses: number; net: number }) {
  const max = Math.max(income, expenses, Math.abs(net), 1);
  const incomeWidth = Math.max(18, Math.round((income / max) * 100));
  const expenseWidth = Math.max(18, Math.round((expenses / max) * 100));
  const netWidth = Math.max(18, Math.round((Math.abs(net) / max) * 100));
  return <div className="flowCanvas" aria-label="Cash flow summary">
    <div className="flowColumn"><span>Paychecks</span><strong>{money.format(income / 100)}</strong><div className="flowBar income" style={{ height: `${incomeWidth}%` }} /></div>
    <div className="flowStream"><div className="streamBand blue" /><div className="streamBand green" /><div className="streamBand coral" /></div>
    <div className="flowColumn"><span>Income</span><strong>{money.format(income / 100)}</strong><div className="flowBar net" style={{ height: `${incomeWidth}%` }} /></div>
    <div className="flowStream split"><div className="streamBand yellow" /><div className="streamBand rose" /><div className="streamBand slate" /></div>
    <div className="flowOutcomes"><div className="outcomeRow"><div><strong>Savings</strong><span>{money.format(Math.max(net, 0) / 100)}</span></div><div className="outcomeTrack"><div style={{ width: `${netWidth}%` }} /></div></div><div className="outcomeRow"><div><strong>Expenses</strong><span>{money.format(expenses / 100)}</span></div><div className="outcomeTrack expense"><div style={{ width: `${expenseWidth}%` }} /></div></div></div>
  </div>;
}
