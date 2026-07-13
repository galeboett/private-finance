import { useCallback } from "react";
import type { MouseEvent } from "react";
import { routeUrl, type TxnFilter } from "./filters";


export function useDrillDown(filter: TxnFilter, title: string, onPeek: (filter: TxnFilter, title: string) => void) {
  const href = routeUrl("all-accounts", null, filter);
  const onClick = useCallback((event: MouseEvent<HTMLElement>) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onPeek(filter, title);
  }, [filter, onPeek, title]);
  return { href, onClick };
}
