import type { LucideIcon } from "lucide-react";

type NavItem<T extends string> = { id: T; label: string; icon: LucideIcon };

type Props<T extends string> = {
  items: Array<NavItem<T>>;
  activeView: T;
  reviewCount: number;
  onNavigate: (view: T) => void;
};

export function PrimaryNav<T extends string>({ items, activeView, reviewCount, onNavigate }: Props<T>) {
  return (
    <nav>
      {items.map((item) => {
        const Icon = item.icon;
        return <button className={activeView === item.id ? "navItem active" : "navItem"} key={item.id} title={item.label} onClick={() => onNavigate(item.id)}><Icon size={16} /><span>{item.label}</span>{item.id === "review" && reviewCount > 0 ? <span className="navItemCount">{reviewCount}</span> : null}</button>;
      })}
    </nav>
  );
}
