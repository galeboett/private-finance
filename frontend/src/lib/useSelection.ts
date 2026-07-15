import { useState } from "react";

export function nextSelection(current: number[], id: number, visibleIds: number[], shiftKey: boolean, anchorId: number | null): number[] {
  const next = new Set(current);
  if (shiftKey && anchorId !== null) {
    const start = visibleIds.indexOf(anchorId);
    const end = visibleIds.indexOf(id);
    if (start >= 0 && end >= 0) {
      const [from, to] = start < end ? [start, end] : [end, start];
      visibleIds.slice(from, to + 1).forEach((visibleId) => next.add(visibleId));
      return Array.from(next);
    }
  }
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return Array.from(next);
}

export function useSelection() {
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [lastSelectedId, setLastSelectedId] = useState<number | null>(null);

  function toggle(id: number, visibleIds: number[], shiftKey: boolean) {
    setSelectedIds((current) => nextSelection(current, id, visibleIds, shiftKey, lastSelectedId));
    setLastSelectedId(id);
  }

  function resetAnchor() {
    setLastSelectedId(null);
  }

  return { selectedIds, setSelectedIds, toggle, resetAnchor };
}
