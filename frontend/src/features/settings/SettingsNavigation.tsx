import { Database, FileUp, Landmark, PiggyBank, ShieldCheck } from "lucide-react";

export type SettingsTab = "imports" | "accounts" | "categories" | "data" | "security";

export const settingsTabs = [
  { id: "imports" as const, label: "Imports", description: "Inbox, files, mappings, and sign choices", icon: FileUp },
  { id: "accounts" as const, label: "Accounts & institutions", description: "Accounts, groups, and untracked sources", icon: Landmark },
  { id: "categories" as const, label: "Categories & rules", description: "Reporting buckets and automation", icon: PiggyBank },
  { id: "data" as const, label: "Data", description: "Backups, exports, Trash, and maintenance", icon: Database },
  { id: "security" as const, label: "Security", description: "Password and active sessions", icon: ShieldCheck },
];

export function SettingsNavigation({ active, onSelect }: { active: SettingsTab; onSelect: (tab: SettingsTab) => void }) {
  return (
    <aside className="settingsNavigation" aria-label="Settings sections">
      <div className="settingsNavigationHeader"><span className="eyebrow">Settings</span><h1>Private Finance</h1><p>Choose one area at a time.</p></div>
      <nav>
        {settingsTabs.map((tab) => {
          const Icon = tab.icon;
          return <button type="button" key={tab.id} className={active === tab.id ? "active" : ""} onClick={() => onSelect(tab.id)}><Icon size={17} /><span><strong>{tab.label}</strong><small>{tab.description}</small></span></button>;
        })}
      </nav>
    </aside>
  );
}
