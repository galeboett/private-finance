import {
  AlertCircle,
  ArrowDownToLine,
  BadgeDollarSign,
  BarChart3,
  CheckCircle2,
  FileUp,
  Landmark,
  LayoutDashboard,
  ListChecks,
  PiggyBank,
  Plus,
  ReceiptText,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  WalletCards,
} from "lucide-react";
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
  account_id: number;
  raw_description: string;
  amount_cents: number;
  transaction_type: string;
  review_status: string;
  transaction_date: string;
  category_id: number | null;
};

type ImportPreview = {
  preset_type: string;
  rows: Array<Record<string, string | number | null>>;
  warnings: string[];
};

type ToastState = {
  tone: "success" | "error" | "info";
  message: string;
};

const navItems = [
  { label: "Dashboard", icon: LayoutDashboard },
  { label: "Accounts", icon: WalletCards },
  { label: "Transactions", icon: ReceiptText },
  { label: "Cash Flow", icon: BarChart3 },
  { label: "Reports", icon: TrendingUp },
  { label: "Review", icon: ListChecks },
  { label: "Settings", icon: Settings },
];

const reportTabs = ["Reports", "Cash Flow", "Spending", "Income", "Net Worth"];

const transactionTypes = [
  { value: "expense", label: "Expense" },
  { value: "income", label: "Income" },
  { value: "transfer", label: "Transfer" },
  { value: "credit_card_payment", label: "Card payment" },
  { value: "refund", label: "Refund" },
  { value: "investment_flow", label: "Investment flow" },
  { value: "adjustment", label: "Adjustment" },
];

const formatMoney = (cents: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);

const readableAccountType = (value: string) => value.replace("_", " ");

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
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
    return "The request could not be completed.";
  }
  return "The request could not be completed.";
}

export function App() {
  const [configured, setConfigured] = useState(false);
  const [csrf, setCsrf] = useState("");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [toast, setToast] = useState<ToastState | null>(null);
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null);
  const [categories, setCategories] = useState<BootstrapCategory[]>([]);
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [review, setReview] = useState<ReviewItem[]>([]);
  const [transactions, setTransactions] = useState<TransactionRow[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<number | "">("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null);
  const [activeTab, setActiveTab] = useState("Cash Flow");
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
        setCsrf("");
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

  function showToast(nextToast: ToastState) {
    setToast(nextToast);
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
      showToast({ tone: "success", message: "Workspace initialized. Sign in with your new password." });
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
    setToast(null);
    if (!accountForm.display_name.trim()) {
      showToast({ tone: "error", message: "Add an account name before saving." });
      return;
    }
    try {
      const result = await api<{ id: number }>("/api/accounts", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify(accountForm),
      });
      setAccountForm({ institution_name: "", display_name: "", account_type: "checking", last_four: "" });
      setSelectedAccountId(result.id);
      await loadData();
      showToast({ tone: "success", message: "Account added. It is selected for your next import." });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Account could not be added." });
    }
  }

  async function previewSelectedImport() {
    setToast(null);
    setImportPreview(null);
    if (!selectedAccountId) {
      showToast({ tone: "error", message: "Choose or add the account this CSV belongs to first." });
      return;
    }
    if (!selectedFile) {
      showToast({ tone: "error", message: "Choose a CSV file before previewing." });
      return;
    }
    const form = new FormData();
    form.append("file", selectedFile);
    try {
      const response = await fetch(`/api/imports/preview?account_id=${selectedAccountId}`, {
        method: "POST",
        credentials: "include",
        body: form,
      });
      if (!response.ok) {
        throw new Error(await readableApiError(response));
      }
      const preview = (await response.json()) as ImportPreview;
      setImportPreview(preview);
      showToast({ tone: "success", message: `Preview ready: ${preview.rows.length} sample rows detected.` });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Preview failed." });
    }
  }

  async function commitSelectedImport() {
    setToast(null);
    if (!selectedAccountId || !selectedFile || !importPreview) {
      showToast({ tone: "error", message: "Preview the file before committing it." });
      return;
    }
    const form = new FormData();
    form.append("file", selectedFile);
    try {
      const response = await fetch(`/api/imports/commit?account_id=${selectedAccountId}`, {
        method: "POST",
        credentials: "include",
        headers: { "x-csrf-token": csrf },
        body: form,
      });
      if (!response.ok) {
        throw new Error(await readableApiError(response));
      }
      const result = (await response.json()) as { inserted: number; skipped: number };
      setImportPreview(null);
      setSelectedFile(null);
      await loadData();
      showToast({ tone: "success", message: `Imported ${result.inserted} rows. Skipped ${result.skipped} duplicates.` });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Import failed." });
    }
  }

  async function updateTransaction(transactionId: number, patch: Partial<Pick<TransactionRow, "category_id" | "transaction_type" | "review_status">>) {
    setToast(null);
    try {
      await api(`/api/transactions/${transactionId}`, {
        method: "PATCH",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify(patch),
      });
      setTransactions((current) =>
        current.map((transaction) => (transaction.id === transactionId ? { ...transaction, ...patch } : transaction)),
      );
      setReview((current) => (patch.review_status === "confirmed" ? current.filter((item) => item.id !== transactionId) : current));
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Transaction could not be updated." });
    }
  }

  async function confirmTransaction(transaction: TransactionRow) {
    if (transaction.transaction_type === "expense" && !transaction.category_id) {
      showToast({ tone: "error", message: "Choose a category before confirming an expense." });
      return;
    }
    await updateTransaction(transaction.id, { review_status: "confirmed" });
    showToast({ tone: "success", message: "Transaction confirmed." });
  }

  async function saveRuleFromTransaction(transaction: TransactionRow) {
    setToast(null);
    if (!transaction.category_id) {
      showToast({ tone: "error", message: "Choose a category before saving a rule." });
      return;
    }
    const matchText = suggestedRuleText(transaction.raw_description);
    try {
      await api("/api/rules", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({
          category_id: transaction.category_id,
          field_name: "raw_description",
          match_text: matchText,
          suggested_transaction_type: transaction.transaction_type,
          priority: 100,
        }),
      });
      showToast({ tone: "success", message: `Rule saved for "${matchText}". Future imports can suggest this category.` });
    } catch (error) {
      showToast({ tone: "error", message: error instanceof Error ? error.message : "Rule could not be saved." });
    }
  }

  if (!configured) {
    return (
      <div className="authShell">
        <section className="authPanel">
          <ShieldCheck size={28} />
          <h1>private-finance</h1>
          <p>Create the local password for this workspace.</p>
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Create password, 12+ characters" />
          {errorMessage ? <p className="formError">{errorMessage}</p> : null}
          <button className="primaryButton" onClick={() => void handleSetup()}>
            <CheckCircle2 size={16} />
            Initialize
          </button>
        </section>
      </div>
    );
  }

  if (!csrf) {
    return (
      <div className="authShell">
        <section className="authPanel">
          <ShieldCheck size={28} />
          <h1>Welcome back</h1>
          <p>Sign in locally to review imports, cash flow, and net worth.</p>
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Password" />
          {errorMessage ? <p className="formError">{errorMessage}</p> : null}
          <button className="primaryButton" onClick={() => void handleLogin()}>
            <ShieldCheck size={16} />
            Sign in
          </button>
        </section>
      </div>
    );
  }

  const totalIncomeCents = transactions.filter((transaction) => transaction.transaction_type === "income").reduce((sum, transaction) => sum + transaction.amount_cents, 0);
  const totalExpenseCents = Math.abs(
    transactions.filter((transaction) => transaction.transaction_type === "expense").reduce((sum, transaction) => sum + transaction.amount_cents, 0),
  );
  const netIncomeCents = totalIncomeCents - totalExpenseCents;
  const savingsRate = totalIncomeCents > 0 ? Math.max(0, Math.round((netIncomeCents / totalIncomeCents) * 1000) / 10) : 0;
  const selectedAccount = accounts.find((account) => account.id === selectedAccountId);
  const previewRows = importPreview?.rows.slice(0, 6) ?? [];
  const reviewTransactions = transactions.filter((transaction) => ["needs_review", "suggested", "possible_duplicate"].includes(transaction.review_status));
  const recentTransactions = transactions.slice(0, 8);

  return (
    <div className="appFrame">
      <aside className="sidebar">
        <div className="brandMark">
          <BadgeDollarSign size={22} />
        </div>
        <nav>
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button className={item.label === "Reports" ? "navItem active" : "navItem"} key={item.label} title={item.label}>
                <Icon size={16} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </aside>

      <main className="workspace">
        <header className="topBar">
          <div className="reportTabs" role="tablist" aria-label="Report views">
            {reportTabs.map((tab) => (
              <button className={tab === activeTab ? "reportTab active" : "reportTab"} key={tab} onClick={() => setActiveTab(tab)}>
                {tab}
              </button>
            ))}
          </div>
          <div className="toolbar">
            <button className="ghostButton" title="Search">
              <Search size={16} />
            </button>
            <button className="filterButton">This month</button>
            <button className="filterButton">Filters</button>
          </div>
        </header>

        {toast ? (
          <div className={`toast ${toast.tone}`}>
            {toast.tone === "success" ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
            <span>{toast.message}</span>
          </div>
        ) : null}

        <section className="metricsGrid" aria-label="Financial summary">
          <MetricTile label="Total income" value={formatMoney(totalIncomeCents)} tone="green" />
          <MetricTile label="Total expenses" value={formatMoney(totalExpenseCents)} tone="red" />
          <MetricTile label="Total net income" value={formatMoney(netIncomeCents)} tone="neutral" />
          <MetricTile label="Savings rate" value={`${savingsRate}%`} tone="neutral" />
        </section>

        <section className="contentGrid">
          <section className="reportSurface">
            <div className="sectionHeader">
              <div>
                <span className="eyebrow">Cash Flow</span>
                <h2>Monthly import workspace</h2>
              </div>
              <div className="inlineActions">
                <button className="ghostButton" title="Refresh data" onClick={() => void loadData()}>
                  <RefreshCw size={16} />
                </button>
              </div>
            </div>
            <CashFlowGraphic income={totalIncomeCents} expenses={totalExpenseCents} net={netIncomeCents} />
          </section>

          <aside className="rightRail">
            <section className="phonePanel">
              <div className="phoneTop">
                <span>Accounts</span>
                <strong>{formatMoney((dashboard?.net_worth_snapshot_cents ?? 0) + Math.max(netIncomeCents, 0))}</strong>
              </div>
              <div className="sparkline" />
              <div className="accountStack">
                {accounts.slice(0, 3).map((account) => (
                  <div className="miniAccount" key={account.id}>
                    <Landmark size={16} />
                    <span>{account.display_name}</span>
                    <small>{readableAccountType(account.account_type)}</small>
                  </div>
                ))}
                {accounts.length === 0 ? <p className="emptyText">Add accounts to build your net-worth picture.</p> : null}
              </div>
            </section>
          </aside>
        </section>

        <section className="workGrid">
          <section className="toolPanel">
            <PanelTitle icon={WalletCards} title="Accounts" subtitle="Create the containers your imports belong to." />
            <div className="compactForm">
              <input value={accountForm.display_name} onChange={(event) => setAccountForm({ ...accountForm, display_name: event.target.value })} placeholder="Account name" />
              <input value={accountForm.institution_name} onChange={(event) => setAccountForm({ ...accountForm, institution_name: event.target.value })} placeholder="Institution" />
              <select value={accountForm.account_type} onChange={(event) => setAccountForm({ ...accountForm, account_type: event.target.value })}>
                <option value="checking">Checking</option>
                <option value="savings">Savings</option>
                <option value="credit_card">Credit card</option>
                <option value="brokerage">Brokerage</option>
              </select>
              <input value={accountForm.last_four} onChange={(event) => setAccountForm({ ...accountForm, last_four: event.target.value })} placeholder="Last four" />
              <button className="primaryButton" onClick={() => void createAccount()}>
                <Plus size={16} />
                Add account
              </button>
            </div>
            <div className="denseList">
              {accounts.map((account) => (
                <button className={selectedAccountId === account.id ? "accountRow selected" : "accountRow"} key={account.id} onClick={() => setSelectedAccountId(account.id)}>
                  <Landmark size={16} />
                  <span>{account.display_name}</span>
                  <small>{readableAccountType(account.account_type)}</small>
                </button>
              ))}
            </div>
          </section>

          <section className="toolPanel">
            <PanelTitle icon={FileUp} title="Imports" subtitle="Preview first, then commit clean rows into the ledger." />
            <div className="compactForm">
              <select value={selectedAccountId} onChange={(event) => setSelectedAccountId(event.target.value ? Number(event.target.value) : "")}>
                <option value="">Choose account</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.display_name}
                  </option>
                ))}
              </select>
              <input type="file" accept=".csv" onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)} />
              <div className="buttonRow">
                <button className="secondaryButton" onClick={() => void previewSelectedImport()}>
                  <Search size={16} />
                  Preview
                </button>
                <button className="primaryButton" onClick={() => void commitSelectedImport()} disabled={!importPreview}>
                  <ArrowDownToLine size={16} />
                  Commit
                </button>
              </div>
            </div>
            <div className="previewPanel">
              {importPreview ? (
                <>
                  <div className="previewMeta">
                    <strong>{importPreview.preset_type}</strong>
                    <span>{selectedAccount?.display_name}</span>
                  </div>
                  <div className="previewRows">
                    {previewRows.map((row, index) => (
                      <div className="previewRow" key={`${row.row_index ?? index}`}>
                        <span>{String(row.raw_description ?? row.description ?? row.symbol ?? "Row")}</span>
                        <strong>{String(row.amount ?? row.market_value ?? "")}</strong>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <p className="emptyText">Select an account and CSV to see the normalized rows before they touch the ledger.</p>
              )}
            </div>
          </section>

          <section className="toolPanel">
            <PanelTitle icon={ListChecks} title="Review Inbox" subtitle={`${reviewTransactions.length} items need a human decision.`} />
            <div className="reviewEditor">
              {reviewTransactions.slice(0, 5).map((transaction) => (
                <article className="reviewCard" key={transaction.id}>
                  <div className="reviewCardTop">
                    <div>
                      <strong>{transaction.raw_description}</strong>
                      <small>{transaction.transaction_date} · {transaction.review_status}</small>
                    </div>
                    <span className={transaction.amount_cents < 0 ? "amount negative" : "amount positive"}>{formatMoney(transaction.amount_cents)}</span>
                  </div>
                  <div className="reviewControls">
                    <select
                      value={transaction.transaction_type}
                      onChange={(event) => void updateTransaction(transaction.id, { transaction_type: event.target.value })}
                    >
                      {transactionTypes.map((type) => (
                        <option key={type.value} value={type.value}>
                          {type.label}
                        </option>
                      ))}
                    </select>
                    <select
                      value={transaction.category_id ?? ""}
                      onChange={(event) => void updateTransaction(transaction.id, { category_id: event.target.value ? Number(event.target.value) : null })}
                    >
                      <option value="">No category</option>
                      {categories.map((category) => (
                        <option key={category.id} value={category.id}>
                          {category.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="reviewActions">
                    <button className="secondaryButton" onClick={() => void saveRuleFromTransaction(transaction)}>
                      <Sparkles size={16} />
                      Save rule
                    </button>
                    <button className="primaryButton" onClick={() => void confirmTransaction(transaction)}>
                      <CheckCircle2 size={16} />
                      Confirm
                    </button>
                  </div>
                </article>
              ))}
              {reviewTransactions.length === 0 ? <p className="emptyText">No items waiting for review. New imports will appear here before reports rely on them.</p> : null}
            </div>
          </section>

          <section className="toolPanel">
            <PanelTitle icon={PiggyBank} title="Categories" subtitle="Fixed spending buckets for expense reporting." />
            <div className="categoryGrid">
              {categories.map((category) => (
                <span className="categoryPill" key={category.id}>
                  {category.label}
                </span>
              ))}
            </div>
          </section>
        </section>

        <section className="ledgerPanel">
          <PanelTitle icon={ReceiptText} title="Recent Transactions" subtitle="The ledger after imports, edits, and review decisions." />
          <div className="ledgerTable">
            <div className="ledgerHeader">
              <span>Date</span>
              <span>Description</span>
              <span>Type</span>
              <span>Category</span>
              <span>Status</span>
              <span>Amount</span>
            </div>
            {recentTransactions.map((transaction) => {
              const category = categories.find((item) => item.id === transaction.category_id);
              return (
                <div className="ledgerRow" key={transaction.id}>
                  <span>{transaction.transaction_date}</span>
                  <strong>{transaction.raw_description}</strong>
                  <span>{readableAccountType(transaction.transaction_type)}</span>
                  <span>{category?.label ?? "Uncategorized"}</span>
                  <span>{transaction.review_status}</span>
                  <span className={transaction.amount_cents < 0 ? "amount negative" : "amount positive"}>{formatMoney(transaction.amount_cents)}</span>
                </div>
              );
            })}
            {recentTransactions.length === 0 ? <p className="emptyText">No transactions yet. Import a CSV to start the ledger.</p> : null}
          </div>
        </section>
      </main>
    </div>
  );
}

function MetricTile({ label, value, tone }: { label: string; value: string; tone: "green" | "red" | "neutral" }) {
  return (
    <div className={`metricTile ${tone}`}>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function suggestedRuleText(description: string) {
  const cleaned = description.replace(/[^a-zA-Z0-9\s*&]/g, " ").replace(/\s+/g, " ").trim();
  return cleaned.split(" ").slice(0, 3).join(" ").toUpperCase() || description.slice(0, 40).toUpperCase();
}

function PanelTitle({ icon: Icon, title, subtitle }: { icon: typeof WalletCards; title: string; subtitle: string }) {
  return (
    <div className="panelTitle">
      <Icon size={18} />
      <div>
        <h3>{title}</h3>
        <p>{subtitle}</p>
      </div>
    </div>
  );
}

function CashFlowGraphic({ income, expenses, net }: { income: number; expenses: number; net: number }) {
  const max = Math.max(income, expenses, Math.abs(net), 1);
  const incomeWidth = Math.max(18, Math.round((income / max) * 100));
  const expenseWidth = Math.max(18, Math.round((expenses / max) * 100));
  const netWidth = Math.max(18, Math.round((Math.abs(net) / max) * 100));

  return (
    <div className="flowCanvas" aria-label="Cash flow summary">
      <div className="flowColumn">
        <span>Paychecks</span>
        <strong>{formatMoney(income)}</strong>
        <div className="flowBar income" style={{ height: `${incomeWidth}%` }} />
      </div>
      <div className="flowStream">
        <div className="streamBand blue" />
        <div className="streamBand green" />
        <div className="streamBand coral" />
      </div>
      <div className="flowColumn">
        <span>Income</span>
        <strong>{formatMoney(income)}</strong>
        <div className="flowBar net" style={{ height: `${incomeWidth}%` }} />
      </div>
      <div className="flowStream split">
        <div className="streamBand yellow" />
        <div className="streamBand rose" />
        <div className="streamBand slate" />
      </div>
      <div className="flowOutcomes">
        <div className="outcomeRow">
          <div>
            <strong>Savings</strong>
            <span>{formatMoney(Math.max(net, 0))}</span>
          </div>
          <div className="outcomeTrack">
            <div style={{ width: `${netWidth}%` }} />
          </div>
        </div>
        <div className="outcomeRow">
          <div>
            <strong>Expenses</strong>
            <span>{formatMoney(expenses)}</span>
          </div>
          <div className="outcomeTrack expense">
            <div style={{ width: `${expenseWidth}%` }} />
          </div>
        </div>
      </div>
    </div>
  );
}
