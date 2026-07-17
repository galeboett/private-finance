import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { encodeTxnFilter, type TxnFilter } from "../lib/filters";

type Summary = {
  inflow_cents: number;
  outflow_cents: number;
  net_cents: number;
  transaction_count: number;
  spend_month_count: number;
  average_monthly_spend_cents: number;
};

export function FilterSummaryBar({ filter, formatMoney, onPeek }: { filter: TxnFilter; formatMoney: (cents: number) => string; onPeek: (filter: TxnFilter, title: string) => void }) {
  const query = encodeTxnFilter(filter).toString();
  const summary = useQuery({ queryKey: ["transaction-summary", query], queryFn: () => api<Summary>(`/api/aggregate/summary?${query}`) });
  if (summary.isError) return <div className="filterSummaryBar error" role="status">Filtered totals could not be loaded.</div>;
  const row = summary.data;
  const items = [
    { label: "Total in", value: row ? formatMoney(row.inflow_cents) : "—", filter: { ...filter, direction: "inflow" as const }, title: "Filtered money in" },
    { label: "Total out", value: row ? formatMoney(row.outflow_cents) : "—", filter: { ...filter, direction: "outflow" as const }, title: "Filtered money out" },
    { label: "Net", value: row ? formatMoney(row.net_cents) : "—", filter, title: "Filtered net activity" },
    { label: "Transactions", value: row ? String(row.transaction_count) : "—", filter, title: "Filtered transactions" },
    { label: "Avg monthly spend", value: row ? formatMoney(row.average_monthly_spend_cents) : "—", filter: { ...filter, direction: "outflow" as const }, title: "Filtered monthly spending" },
  ];
  return <div className="filterSummaryBar" aria-label="Filtered transaction summary">{items.map((item) => <button type="button" key={item.label} onClick={() => onPeek(item.filter, item.title)} disabled={!row}><span>{item.label}</span><strong>{item.value}</strong></button>)}</div>;
}
