import { useCallback, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { usePagedTransactions } from "../api/hooks";

export function useLedger<T>(view: "live" | "trash", enabled: boolean, refreshKey: number) {
  const queryClient = useQueryClient();
  const query = usePagedTransactions<T>(`/api/transactions?view=${view}`, enabled, refreshKey);
  const rows = useMemo(() => query.data?.pages.flatMap((page) => page.items) ?? [], [query.data]);
  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: ["transactions"] }),
    [queryClient],
  );
  const loadMore = useCallback(async () => {
    if (query.hasNextPage && !query.isFetchingNextPage) await query.fetchNextPage();
  }, [query]);

  return {
    rows,
    hasMore: Boolean(query.hasNextPage),
    isLoadingMore: query.isFetchingNextPage,
    loadMore,
    refetch: query.refetch,
    invalidate,
  };
}
