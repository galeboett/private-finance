import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useApiQuery } from "../api/hooks";

export function useNetWorth<TAccount, TAllocation, THolding>(enabled: boolean) {
  const queryClient = useQueryClient();
  const accounts = useApiQuery<TAccount[]>(["net-worth", "accounts"], "/api/net-worth/accounts", { enabled });
  const allocation = useApiQuery<TAllocation[]>(["allocation", "latest"], "/api/investments/allocation", { enabled });
  const holdings = useApiQuery<THolding[]>(["holdings", "latest"], "/api/investments/holdings", { enabled });
  const invalidate = useCallback(
    () => Promise.all([
      queryClient.invalidateQueries({ queryKey: ["net-worth"] }),
      queryClient.invalidateQueries({ queryKey: ["allocation"] }),
      queryClient.invalidateQueries({ queryKey: ["holdings"] }),
    ]),
    [queryClient],
  );

  return { accounts, allocation, holdings, invalidate };
}
