import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient, type QueryKey, type UseMutationOptions, type UseQueryOptions } from "@tanstack/react-query";
import { api, apiUrl, notifyApiMutation } from "./client";

export function useApiQuery<T>(queryKey: QueryKey, path: string, options?: Omit<UseQueryOptions<T>, "queryKey" | "queryFn">) {
  return useQuery<T>({ queryKey, queryFn: () => api<T>(path), ...options });
}

export function useApiMutation<TData, TVariables = void>(
  mutationFn: (variables: TVariables) => Promise<TData>,
  options?: Omit<UseMutationOptions<TData, Error, TVariables>, "mutationFn">,
) {
  return useMutation<TData, Error, TVariables>({ mutationFn, ...options });
}

export function useApiClient() {
  const queryClient = useQueryClient();
  return useCallback(<T,>(path: string, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    if (method === "GET" || method === "HEAD") {
      return queryClient.fetchQuery({ queryKey: apiQueryKey(path), queryFn: () => api<T>(path, init), staleTime: 0 });
    }
    return api<T>(path, init);
  }, [queryClient]);
}

export function useApiFetch() {
  return useCallback(async (path: string, init?: RequestInit) => {
    const response = await fetch(apiUrl(path), { credentials: "include", ...init });
    const method = (init?.method ?? "GET").toUpperCase();
    if (response.ok && method !== "GET" && method !== "HEAD") notifyApiMutation(path);
    return response;
  }, []);
}

export function apiQueryKey(path: string): QueryKey {
  const family = path.startsWith("/api/aggregate") ? "aggregates"
    : path.startsWith("/api/accounts") ? "accounts"
    : path.startsWith("/api/transactions") ? "transactions"
      : path.startsWith("/api/operations") ? "operations"
        : path.startsWith("/api/rules") ? "rules"
          : path.startsWith("/api/duplicates") ? "duplicates"
            : path.startsWith("/api/refunds") || path.startsWith("/api/refund-links") ? "refunds"
              : path.startsWith("/api/transfers") ? "transfers"
                : path.startsWith("/api/reconciliation") ? "reconciliation"
                  : path.startsWith("/api/import") || path.startsWith("/api/settings/import") ? "imports"
                    : path.startsWith("/api/snapshots/networth") || path.startsWith("/api/net-worth") ? "net-worth"
                      : path.startsWith("/api/investments/holdings") ? "holdings"
                        : path.startsWith("/api/investments/allocation") ? "allocation"
                          : path.startsWith("/api/dashboard") ? "dashboard"
                            : path.startsWith("/api/bootstrap") ? "bootstrap"
                              : "api";
  return [family, path];
}
