import {
  ChevronDown,
  ChevronRight,
  CreditCard,
  Landmark,
  MoreHorizontal,
  PiggyBank,
  TrendingUp,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useState, type CSSProperties, type MouseEvent } from "react";

export type SidebarAccount = {
  id: number;
  display_name: string;
  account_type: string;
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

type AccountCategory = {
  label: string;
  icon: LucideIcon;
  rows: SidebarAccount[];
  totalCents: number;
};

type FlyoutState = {
  institution: string;
  top: number;
  category: string | null;
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
  const accountSection = sections.find((section) => section.label === "Accounts");
  const otherSections = sections.filter((section) => section.label !== "Accounts");
  const [flyout, setFlyout] = useState<FlyoutState | null>(null);
  const activeGroup = accountSection?.groups.find((group) => group.label === flyout?.institution) ?? null;
  const categories = useMemo(() => activeGroup ? categoryGroups(activeGroup.rows) : [], [activeGroup]);
  const singleCategory = categories.length === 1 ? categories[0] : null;
  const activeCategory = categories.find((category) => category.label === flyout?.category) ?? null;

  useEffect(() => setFlyout(null), [activeAccountId]);

  function openInstitution(event: MouseEvent<HTMLButtonElement>, institution: string) {
    const top = event.currentTarget.getBoundingClientRect().top;
    setFlyout((current) => current?.institution === institution ? null : { institution, top, category: null });
  }

  function openAccount(accountId: number) {
    setFlyout(null);
    onOpenAccount(accountId);
  }

  return <div className="accountNavigation">
    {accountSection ? (
      <section className="sidebarSection accountRootSection">
        <div className="sidebarSectionHeader accountRootHeader">
          <Landmark size={13} />
          <span>Accounts</span>
          <span className={accountSection.totalCents < 0 ? "sidebarSectionBalance negative" : "sidebarSectionBalance"}>{formatMoney(accountSection.totalCents)}</span>
        </div>
        <div className="sidebarInstitutions">
          {accountSection.groups.map((group) => (
            <button
              className={flyout?.institution === group.label ? "sidebarInstitutionButton active" : "sidebarInstitutionButton"}
              type="button"
              key={group.label}
              aria-expanded={flyout?.institution === group.label}
              onClick={(event) => openInstitution(event, group.label)}
            >
              <span className="institutionIcon"><Landmark size={13} /></span>
              <span>{group.label}</span>
              <span className={group.totalCents < 0 ? "sidebarGroupBalance negative" : "sidebarGroupBalance"}>{formatMoney(group.totalCents)}</span>
              <ChevronRight size={13} />
            </button>
          ))}
          {accountSection.rows.length === 0 ? <p className="emptyText sidebarEmptyText">{accountSection.emptyText}</p> : null}
        </div>
      </section>
    ) : null}

    {otherSections.map((section) => (
      <LegacySection key={section.label} section={section} collapsed={collapsed} activeAccountId={activeAccountId} missingCategoryCountByAccount={missingCategoryCountByAccount} formatMoney={formatMoney} balanceLabel={balanceLabel} onToggle={onToggle} onOpenAccount={openAccount} />
    ))}

    {flyout && activeGroup ? <>
      <button className="accountTaxonomyScrim" aria-label="Close account navigation" onClick={() => setFlyout(null)} />
      <aside className="accountTaxonomyFlyout" style={{ "--flyout-top": `${Math.max(70, flyout.top)}px` } as CSSProperties} aria-label={`${flyout.institution} accounts`}>
        <header>
          <span className="institutionIcon large"><Landmark size={15} /></span>
          <div><strong>{flyout.institution}</strong><span>{singleCategory ? singleCategory.label : `${activeGroup.rows.length} account${activeGroup.rows.length === 1 ? "" : "s"}`}</span></div>
          <button type="button" className="flyoutCloseButton" onClick={() => setFlyout(null)} aria-label="Close account navigation"><X size={15} /></button>
        </header>
        {singleCategory ? (
          <div className="flyoutAccountList">
            {singleCategory.rows.map((account) => <FlyoutAccount key={account.id} account={account} active={activeAccountId === account.id} missingCount={missingCategoryCountByAccount.get(account.id) ?? 0} formatMoney={formatMoney} balanceLabel={balanceLabel} onOpen={openAccount} />)}
          </div>
        ) : (
          <div className="flyoutCategoryList">
            {categories.map((category) => {
              const Icon = category.icon;
              return <button type="button" className={activeCategory?.label === category.label ? "active" : ""} key={category.label} aria-expanded={activeCategory?.label === category.label} onClick={() => setFlyout((current) => current ? { ...current, category: current.category === category.label ? null : category.label } : null)}>
                <span className="categoryIcon"><Icon size={17} /></span>
                <span><strong>{category.label}</strong><small>{category.rows.length} account{category.rows.length === 1 ? "" : "s"}</small></span>
                <span className={category.totalCents < 0 ? "negative" : ""}>{formatMoney(category.totalCents)}</span>
                <ChevronRight size={15} />
              </button>;
            })}
          </div>
        )}
      </aside>
      {!singleCategory && activeCategory ? (
        <aside className="accountTaxonomyFlyout secondary" style={{ "--flyout-top": `${Math.max(70, flyout.top)}px` } as CSSProperties} aria-label={`${flyout.institution} ${activeCategory.label} accounts`}>
          <header>
            <span className="categoryIcon large"><activeCategory.icon size={15} /></span>
            <div><strong>{activeCategory.label}</strong><span>{flyout.institution} · {activeCategory.rows.length} account{activeCategory.rows.length === 1 ? "" : "s"}</span></div>
            <button type="button" className="flyoutCloseButton" onClick={() => setFlyout((current) => current ? { ...current, category: null } : null)} aria-label={`Close ${activeCategory.label}`}><X size={15} /></button>
          </header>
          <div className="flyoutAccountList">
            {activeCategory.rows.map((account) => <FlyoutAccount key={account.id} account={account} active={activeAccountId === account.id} missingCount={missingCategoryCountByAccount.get(account.id) ?? 0} formatMoney={formatMoney} balanceLabel={balanceLabel} onOpen={openAccount} />)}
          </div>
        </aside>
      ) : null}
    </> : null}
  </div>;
}

function LegacySection<T extends SidebarAccount>({ section, collapsed, activeAccountId, missingCategoryCountByAccount, formatMoney, balanceLabel, onToggle, onOpenAccount }: { section: AccountNavSection<T>; collapsed: Record<string, boolean>; activeAccountId: number | null; missingCategoryCountByAccount: Map<number, number>; formatMoney: (cents: number) => string; balanceLabel: (account: T) => string; onToggle: (sectionLabel: string, groupLabel: string) => void; onOpenAccount: (accountId: number) => void }) {
  const sectionKey = `section::${section.label}`;
  const sectionCollapsed = section.label === "Archived Accounts" ? collapsed[sectionKey] !== false : Boolean(collapsed[sectionKey]);
  return <section className="sidebarSection" key={section.label}>
    <button className="sidebarSectionHeader" type="button" aria-expanded={!sectionCollapsed} onClick={() => onToggle("section", section.label)} title={`${sectionCollapsed ? "Expand" : "Collapse"} ${section.label}`}>
      {sectionCollapsed ? <ChevronRight size={11} /> : <ChevronDown size={11} />}
      <span>{section.label}</span>
      <span className={section.totalCents < 0 ? "sidebarSectionBalance negative" : "sidebarSectionBalance"}>{formatMoney(section.totalCents)}</span>
    </button>
    {sectionCollapsed ? null : <div className="sidebarAccounts">
      {section.groups.flatMap((group) => group.rows.map((account) => <FlyoutAccount key={account.id} account={account} active={activeAccountId === account.id} missingCount={missingCategoryCountByAccount.get(account.id) ?? 0} formatMoney={formatMoney} balanceLabel={balanceLabel} onOpen={onOpenAccount} />))}
      {section.rows.length === 0 ? <p className="emptyText sidebarEmptyText">{section.emptyText}</p> : null}
    </div>}
  </section>;
}

function FlyoutAccount<T extends SidebarAccount>({ account, active, missingCount, formatMoney, balanceLabel, onOpen }: { account: T; active: boolean; missingCount: number; formatMoney: (cents: number) => string; balanceLabel: (account: T) => string; onOpen: (accountId: number) => void }) {
  const lastFour = account.last_four?.trim();
  const accountName = !lastFour || account.display_name.endsWith(lastFour) || account.display_name.endsWith(`(${lastFour})`) ? account.display_name : `${account.display_name} (${lastFour})`;
  return <button className={active ? "flyoutAccount active" : "flyoutAccount"} type="button" onClick={() => onOpen(account.id)} title={`${accountName} · ${balanceLabel(account)}`}>
    <span className={missingCount > 0 ? "attentionDot" : "attentionDot hidden"} />
    <span><strong>{accountName}</strong><small>{balanceLabel(account)}</small></span>
    <span className={(account.sidebar_balance_cents ?? 0) < 0 ? "negative" : ""}>{account.sidebar_balance_cents === null ? "—" : formatMoney(account.sidebar_balance_cents)}</span>
  </button>;
}

function categoryGroups<T extends SidebarAccount>(rows: T[]): AccountCategory[] {
  const definitions: Array<{ label: string; icon: LucideIcon; types: string[] }> = [
    { label: "Checking & Savings", icon: PiggyBank, types: ["checking", "savings", "cash"] },
    { label: "Credit Cards", icon: CreditCard, types: ["credit_card"] },
    { label: "Investments", icon: TrendingUp, types: ["brokerage", "retirement"] },
    { label: "Other Accounts", icon: MoreHorizontal, types: ["loan", "other", "external"] },
  ];
  return definitions.map((definition) => {
    const categoryRows = rows.filter((row) => definition.types.includes(row.account_type));
    return {
      label: definition.label,
      icon: definition.icon,
      rows: categoryRows,
      totalCents: categoryRows.reduce((sum, row) => sum + (row.sidebar_balance_cents ?? 0), 0),
    };
  }).filter((category) => category.rows.length > 0);
}

export function accountCategoryLabel(accountType: string): string {
  if (["checking", "savings", "cash"].includes(accountType)) return "Checking & Savings";
  if (accountType === "credit_card") return "Credit Cards";
  if (["brokerage", "retirement"].includes(accountType)) return "Investments";
  return "Other Accounts";
}

export function isFlatAccountGroup(group: Pick<AccountNavGroup, "rows">): boolean {
  return group.rows.length === 1;
}
