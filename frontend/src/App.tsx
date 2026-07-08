import { useEffect, useState } from "react";

type BootstrapCategory = { id: number; key: string; label: string };
type DashboardSummary = {
  review_counts: Record<string, number>;
  month_to_date_expense_cents: number;
  cash_flow_cents: number;
  net_worth_snapshot_cents: number;
};

type AccountSummary = {
  id: number;
  display_name: string;
  account_type: string;
  status: string;
};

type ReviewItem = {
  id: number;
  description: string;
  amount_cents: number;
  review_status: string;
};

type TransactionRow = {
  id: number;
  raw_description: string;
  amount_cents: number;
  transaction_type: string;
  review_status: string;
  transaction_date: string;
};

type ImportPreview = {
  preset_type: string;
  rows: Array<Record<string, string | number | null>>;
  warnings: string[];
};

const formatMoney = (cents: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    throw new Error(await readableApiError(response));
  }
  return response.json();
}

async function readableApiError(response: Response): Promise<string> {
  try {
    const data = await response.json();
    const detail = data?.detail;
    if (Array.isArray(detail) && detail.length > 0) {
      return detail[0]?.msg ?? "The request could not be completed.";
    }
    if (typeof detail === "string") {
      return detail;
    }
  } catch {
    // Fall through to a generic message so sensitive payloads do not land in logs.
  }
  return "The request could not be completed.";
}

export function App() {
  const [configured, setConfigured] = useState(false);
  const [csrf, setCsrf] = useState("");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null);
  const [categories, setCategories] = useState<BootstrapCategory[]>([]);
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [review, setReview] = useState<ReviewItem[]>([]);
  const [transactions, setTransactions] = useState<TransactionRow[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<number | "">("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null);
  const [accountForm, setAccountForm] = useState({
    institution_name: "",
    display_name: "",
    account_type: "checking",
    last_four: "",
  });

  useEffect(() => {
    void loadBootstrap();
  }, []);

  async function loadBootstrap() {
    const data = await api<{ configured: boolean; categories: BootstrapCategory[] }>("/api/bootstrap");
    setConfigured(data.configured);
    setCategories(data.categories);
    if (data.configured) {
      try {
        const me = await api<{ csrf_token: string }>("/api/me");
        setCsrf(me.csrf_token);
        await loadData();
      } catch {
        // unauthenticated state
      }
    }
  }

  async function loadData() {
    const [dashboardData, accountsData, reviewData, transactionData] = await Promise.all([
      api<DashboardSummary>("/api/dashboard/summary"),
      api<AccountSummary[]>("/api/accounts"),
      api<ReviewItem[]>("/api/review"),
      api<TransactionRow[]>("/api/transactions"),
    ]);
    setDashboard(dashboardData);
    setAccounts(accountsData);
    setReview(reviewData);
    setTransactions(transactionData);
  }

  async function handleSetup() {
    setErrorMessage("");
    if (password.length < 12) {
      setErrorMessage("Use at least 12 characters for your local password.");
      return;
    }
    try {
      await api("/api/setup", { method: "POST", body: JSON.stringify({ password }) });
      setConfigured(true);
      setPassword("");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Setup failed.");
    }
  }

  async function handleLogin() {
    setErrorMessage("");
    try {
      const result = await api<{ csrf_token: string }>("/api/login", { method: "POST", body: JSON.stringify({ password }) });
      setCsrf(result.csrf_token);
      setPassword("");
      await loadData();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Login failed.");
    }
  }

  async function createAccount() {
    await api("/api/accounts", {
      method: "POST",
      headers: { "x-csrf-token": csrf },
      body: JSON.stringify(accountForm),
    });
    setAccountForm({ institution_name: "", display_name: "", account_type: "checking", last_four: "" });
    await loadData();
  }

  async function previewSelectedImport() {
    if (!selectedAccountId || !selectedFile) return;
    const form = new FormData();
    form.append("file", selectedFile);
    const response = await fetch(`/api/imports/preview?account_id=${selectedAccountId}`, {
      method: "POST",
      credentials: "include",
      body: form,
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    setImportPreview(await response.json());
  }

  async function commitSelectedImport() {
    if (!selectedAccountId || !selectedFile) return;
    const form = new FormData();
    form.append("file", selectedFile);
    const response = await fetch(`/api/imports/commit?account_id=${selectedAccountId}`, {
      method: "POST",
      credentials: "include",
      headers: { "x-csrf-token": csrf },
      body: form,
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    await response.json();
    setImportPreview(null);
    setSelectedFile(null);
    await loadData();
  }

  if (!configured) {
    return (
      <div className="shell">
        <div className="heroCard">
          <h1>private-finance</h1>
          <p>Set a local password to initialize the encrypted-first finance workspace.</p>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Create password, 12+ characters" />
          {errorMessage ? <p className="formError">{errorMessage}</p> : null}
          <button onClick={() => void handleSetup()}>Initialize</button>
        </div>
      </div>
    );
  }

  if (!csrf) {
    return (
      <div className="shell">
        <div className="heroCard">
          <h1>Welcome back</h1>
          <p>Sign in locally to review imports, cash flow, and net worth.</p>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password" />
          {errorMessage ? <p className="formError">{errorMessage}</p> : null}
          <button onClick={() => void handleLogin()}>Sign in</button>
        </div>
      </div>
    );
  }

  return (
    <div className="shell">
      <header className="header">
        <div>
          <h1>private-finance</h1>
          <p>Local-first spending, review, and net-worth workspace.</p>
        </div>
      </header>

      <section className="grid">
        <div className="card">
          <h2>Dashboard</h2>
          {dashboard ? (
            <>
              <div className="metric">
                <span>Month-to-date spend</span>
                <strong>{formatMoney(dashboard.month_to_date_expense_cents)}</strong>
              </div>
              <div className="metric">
                <span>Cash flow</span>
                <strong>{formatMoney(dashboard.cash_flow_cents)}</strong>
              </div>
              <div className="metric">
                <span>Net worth snapshot</span>
                <strong>{formatMoney(dashboard.net_worth_snapshot_cents)}</strong>
              </div>
            </>
          ) : (
            <p>Loading summary...</p>
          )}
        </div>

        <div className="card">
          <h2>Review Inbox</h2>
          <ul className="list">
            {review.map((item) => (
              <li key={item.id}>
                <span>{item.description}</span>
                <strong>{formatMoney(item.amount_cents)}</strong>
              </li>
            ))}
            {review.length === 0 ? <li>No items waiting for review.</li> : null}
          </ul>
        </div>
      </section>

      <section className="grid">
        <div className="card">
          <h2>Accounts</h2>
          <div className="formStack">
            <input value={accountForm.display_name} onChange={(e) => setAccountForm({ ...accountForm, display_name: e.target.value })} placeholder="Account name" />
            <input value={accountForm.institution_name} onChange={(e) => setAccountForm({ ...accountForm, institution_name: e.target.value })} placeholder="Institution" />
            <select value={accountForm.account_type} onChange={(e) => setAccountForm({ ...accountForm, account_type: e.target.value })}>
              <option value="checking">Checking</option>
              <option value="savings">Savings</option>
              <option value="credit_card">Credit card</option>
              <option value="brokerage">Brokerage</option>
            </select>
            <input value={accountForm.last_four} onChange={(e) => setAccountForm({ ...accountForm, last_four: e.target.value })} placeholder="Last four" />
            <button onClick={() => void createAccount()}>Add account</button>
          </div>
          <ul className="list">
            {accounts.map((account) => (
              <li key={account.id}>
                <span>{account.display_name}</span>
                <small>{account.account_type}</small>
              </li>
            ))}
          </ul>
        </div>

        <div className="card">
          <h2>Fixed Categories</h2>
          <div className="chips">
            {categories.map((category) => (
              <span className="chip" key={category.id}>
                {category.label}
              </span>
            ))}
          </div>
        </div>
      </section>

      <section className="grid">
        <div className="card">
          <h2>Imports</h2>
          <div className="formStack">
            <select value={selectedAccountId} onChange={(e) => setSelectedAccountId(e.target.value ? Number(e.target.value) : "")}>
              <option value="">Choose account</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.display_name}
                </option>
              ))}
            </select>
            <input type="file" accept=".csv" onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)} />
            <div className="buttonRow">
              <button onClick={() => void previewSelectedImport()}>Preview</button>
              <button onClick={() => void commitSelectedImport()} disabled={!importPreview}>
                Commit
              </button>
            </div>
          </div>
          {importPreview ? (
            <div>
              <p>
                Detected preset: <strong>{importPreview.preset_type}</strong>
              </p>
              <pre className="preview">{JSON.stringify(importPreview.rows.slice(0, 5), null, 2)}</pre>
            </div>
          ) : (
            <p>Upload a CSV to preview normalization before commit.</p>
          )}
        </div>

        <div className="card">
          <h2>Transactions</h2>
          <ul className="list">
            {transactions.slice(0, 8).map((item) => (
              <li key={item.id}>
                <span>
                  {item.raw_description}
                  <small className="subtle">{item.transaction_date}</small>
                </span>
                <strong>{formatMoney(item.amount_cents)}</strong>
              </li>
            ))}
            {transactions.length === 0 ? <li>No transactions yet.</li> : null}
          </ul>
        </div>
      </section>
    </div>
  );
}
