import { queryClient } from "./queryClient";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) throw new Error(await readableApiError(response, path));
  const result = await parseApiJson<T>(response, path);
  const method = (init?.method ?? "GET").toUpperCase();
  if (method !== "GET" && method !== "HEAD") {
    notifyApiMutation(path);
  }
  return result;
}

export function notifyApiMutation(path: string) {
  bumpTransactionsVersion();
  invalidateQueriesForMutation(path);
}

const mutationQueryFamilies: Array<[RegExp, string[]]> = [
  [/\/api\/(transactions|operations|rules|duplicates|refunds|refund-links|transfers)/, ["transactions", "transaction-summary", "aggregates", "dashboard", "operations", "rules", "duplicates", "refunds", "transfers", "reconciliation", "payments", "net-worth"]],
  [/\/api\/(accounts|reconciliation|snapshots|investments)/, ["accounts", "transactions", "transaction-summary", "aggregates", "dashboard", "reconciliation", "payments", "net-worth", "holdings", "allocation"]],
  [/\/api\/(imports|import-sign-profiles|maintenance)/, ["imports", "transactions", "transaction-summary", "aggregates", "dashboard", "accounts", "operations", "net-worth", "holdings"]],
  [/\/api\/categories/, ["bootstrap", "categories", "transactions", "transaction-summary", "aggregates", "dashboard", "rules"]],
  [/\/api\/backups/, ["backups"]],
];

function invalidateQueriesForMutation(path: string) {
  const families = new Set(mutationQueryFamilies.flatMap(([pattern, keys]) => pattern.test(path) ? keys : []));
  if (families.size === 0) return;
  void queryClient.invalidateQueries({ predicate: (query) => families.has(String(query.queryKey[0])) });
}

let transactionsVersion = 0;
const transactionVersionListeners = new Set<() => void>();

export function getTransactionsVersion(): number {
  return transactionsVersion;
}

export function subscribeTransactionsVersion(listener: () => void): () => void {
  transactionVersionListeners.add(listener);
  return () => transactionVersionListeners.delete(listener);
}

export function bumpTransactionsVersion(): void {
  transactionsVersion += 1;
  for (const listener of transactionVersionListeners) listener();
}

export function apiUrl(path: string): string {
  if (window.location.port === "5173" && path.startsWith("/api/")) {
    return `http://${window.location.hostname}:8000${path}`;
  }
  return path;
}

export async function readableApiError(response: Response, path: string): Promise<string> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return `${path} returned ${response.status} ${response.statusText || "with a non-JSON response"}. Make sure the backend is running at http://127.0.0.1:8000.`;
  }
  try {
    const data = await response.json();
    const detail = data?.detail;
    if (Array.isArray(detail) && detail.length > 0) return detail[0]?.msg ?? "The request could not be completed.";
    if (typeof detail === "string") return detail;
  } catch {
    return "The request could not be completed.";
  }
  return "The request could not be completed.";
}

export async function parseApiJson<T>(response: Response, path: string): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    throw new Error(`${path} returned frontend HTML instead of API data. The backend may need to be restarted at http://127.0.0.1:8000.`);
  }
  return response.json() as Promise<T>;
}
