import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useApiQuery } from "../api/hooks";

export function useActivity<TOperation>(enabled: boolean) {
  const queryClient = useQueryClient();
  const operations = useApiQuery<TOperation[]>(["operations", "recent"], "/api/operations?limit=100", { enabled });
  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: ["operations"] }),
    [queryClient],
  );

  return { operations, invalidate };
}
