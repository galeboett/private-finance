import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useApiQuery } from "../api/hooks";

export function useAccountsNav<TAccount, TDashboard>(enabled: boolean) {
  const queryClient = useQueryClient();
  const accounts = useApiQuery<TAccount[]>(["accounts", "navigation"], "/api/accounts", { enabled });
  const dashboard = useApiQuery<TDashboard>(["dashboard", "summary"], "/api/dashboard/summary", { enabled });
  const invalidate = useCallback(
    () => Promise.all([
      queryClient.invalidateQueries({ queryKey: ["accounts"] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
    ]),
    [queryClient],
  );

  return { accounts, dashboard, invalidate };
}
