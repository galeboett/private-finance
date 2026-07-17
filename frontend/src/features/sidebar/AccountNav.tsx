import { ChevronDown, ChevronRight } from "lucide-react";

export type SidebarAccount = {
  id: number;
  display_name: string;
  last_four: string | null;
  sidebar_balance_cents: number | null;
  sidebar_balance_kind: string;
};

export type AccountNavGroup<T extends SidebarAccount = SidebarAccount> = {
  label: string;
  rows: T[];
  totalCents: number;
};

export type AccountNavSection<T extends SidebarAccount = SidebarAccount> = {
  label: string;
  rows: T[];
  emptyText: string;
  totalCents: number;
  groups: Array<AccountNavGroup<T>>;
};

type Props<T extends SidebarAccount> = {
  sections: Array<AccountNavSection<T>>;
  collapsed: Record<string, boolean>;
  activeAccountId: number | null;
  missingCategoryCountByAccount: Map<number, number>;
  formatMoney: (cents: number) => string;
  balanceLabel: (account: T) => string;
  onToggle: (sectionLabel: string, groupLabel: string) => void;
  onOpenAccount: (accountId: number) => void;
};

export function AccountNav<T extends SidebarAccount>({ sections, collapsed, activeAccountId, missingCategoryCountByAccount, formatMoney, balanceLabel, onToggle, onOpenAccount }: Props<T>) {
  return <>{sections.map((section) => {
    const sectionKey = `section::${section.label}`;
    const sectionCollapsed = section.label === "Archived Accounts" ? collapsed[sectionKey] !== false : Boolean(collapsed[sectionKey]);
    return <div className="sidebarSection" key={section.label}>
      <button className="sidebarSectionHeader" type="button" aria-expanded={!sectionCollapsed} onClick={() => onToggle("section", section.label)} title={`${sectionCollapsed ? "Expand" : "Collapse"} ${section.label}`}>
        {sectionCollapsed ? <ChevronRight size={11} /> : <ChevronDown size={11} />}
        <span>{section.label}</span>
        <span className={section.totalCents < 0 ? "sidebarSectionBalance negative" : "sidebarSectionBalance"}>{formatMoney(section.totalCents)}</span>
      </button>
      {sectionCollapsed ? null : <div className="sidebarAccounts">
        {section.groups.map((group) => isFlatAccountGroup(group)
          ? <AccountButton key={`${section.label}-${group.label}`} account={group.rows[0]} institution={group.label} flat active={activeAccountId === group.rows[0].id} missingCount={missingCategoryCountByAccount.get(group.rows[0].id) ?? 0} formatMoney={formatMoney} balanceLabel={balanceLabel} onOpen={onOpenAccount} />
          : <AccountGroup key={`${section.label}-${group.label}`} sectionLabel={section.label} group={group} collapsed={Boolean(collapsed[`${section.label}::${group.label}`])} activeAccountId={activeAccountId} missingCategoryCountByAccount={missingCategoryCountByAccount} formatMoney={formatMoney} balanceLabel={balanceLabel} onToggle={onToggle} onOpenAccount={onOpenAccount} />)}
        {section.rows.length === 0 ? <p className="emptyText sidebarEmptyText">{section.emptyText}</p> : null}
      </div>}
    </div>;
  })}</>;
}

function AccountGroup<T extends SidebarAccount>({ sectionLabel, group, collapsed, activeAccountId, missingCategoryCountByAccount, formatMoney, balanceLabel, onToggle, onOpenAccount }: { sectionLabel: string; group: AccountNavGroup<T>; collapsed: boolean; activeAccountId: number | null; missingCategoryCountByAccount: Map<number, number>; formatMoney: (cents: number) => string; balanceLabel: (account: T) => string; onToggle: (sectionLabel: string, groupLabel: string) => void; onOpenAccount: (accountId: number) => void }) {
  return <div className="sidebarTaxonomyGroup">
    <button className="sidebarGroupHeader" type="button" aria-expanded={!collapsed} onClick={() => onToggle(sectionLabel, group.label)} title={`${collapsed ? "Expand" : "Collapse"} ${group.label}`}>
      <span className="sidebarGroupToggle">{collapsed ? <ChevronRight size={10} /> : <ChevronDown size={10} />}</span><span>{group.label}</span><span className={group.totalCents < 0 ? "sidebarGroupBalance negative" : "sidebarGroupBalance"}>{formatMoney(group.totalCents)}</span>
    </button>
    {collapsed ? null : group.rows.map((account) => <AccountButton key={account.id} account={account} active={activeAccountId === account.id} missingCount={missingCategoryCountByAccount.get(account.id) ?? 0} formatMoney={formatMoney} balanceLabel={balanceLabel} onOpen={onOpenAccount} />)}
  </div>;
}

function AccountButton<T extends SidebarAccount>({ account, institution, flat = false, active, missingCount, formatMoney, balanceLabel, onOpen }: { account: T; institution?: string; flat?: boolean; active: boolean; missingCount: number; formatMoney: (cents: number) => string; balanceLabel: (account: T) => string; onOpen: (accountId: number) => void }) {
  const lastFour = account.last_four?.trim();
  const accountName = !lastFour || account.display_name.endsWith(lastFour) || account.display_name.endsWith(`(${lastFour})`) ? account.display_name : `${account.display_name} (${lastFour})`;
  return <button className={`${active ? "sidebarAccount active" : "sidebarAccount"}${flat ? " flat" : ""}`} onClick={() => onOpen(account.id)} title={`${flat && institution ? `${institution} · ` : ""}${accountName} · ${balanceLabel(account)}`}>
    <span className={missingCount > 0 ? "attentionDot" : "attentionDot hidden"} />
    <span className="sidebarAccountName">{flat && institution ? <><small>{institution}</small><span aria-hidden="true">›</span></> : null}{accountName}</span>
    <span className="sidebarAccountBalanceWrap"><span className={(account.sidebar_balance_cents ?? 0) < 0 ? "sidebarAccountBalance negative" : "sidebarAccountBalance"}>{account.sidebar_balance_cents === null ? "—" : formatMoney(account.sidebar_balance_cents)}</span>{account.sidebar_balance_kind === "recent_activity" ? <small>30d</small> : null}</span>
  </button>;
}

export function isFlatAccountGroup(group: Pick<AccountNavGroup, "rows">): boolean {
  return group.rows.length === 1;
}
