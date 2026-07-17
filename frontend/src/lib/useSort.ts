import { useState } from "react";

export type SortDirection = "asc" | "desc";

export function useSort<Key extends string>(initialKey: Key, initialDirection: SortDirection = "asc") {
  const [sortKey, setSortKey] = useState<Key>(initialKey);
  const [sortDirection, setSortDirection] = useState<SortDirection>(initialDirection);

  function toggleSort(nextKey: Key) {
    if (nextKey === sortKey) {
      setSortDirection((current) => current === "asc" ? "desc" : "asc");
    } else {
      setSortKey(nextKey);
      setSortDirection("asc");
    }
  }

  function setSort(nextKey: Key, nextDirection: SortDirection) {
    setSortKey(nextKey);
    setSortDirection(nextDirection);
  }

  return { sortKey, sortDirection, toggleSort, setSort };
}
