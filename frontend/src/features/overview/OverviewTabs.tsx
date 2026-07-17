import { FileUp, RefreshCw } from "lucide-react";

import type { ReportPeriod, ReportTab } from "../../lib/filters";

export const reportTabs: ReportTab[] = ["Overview", "Net Worth", "Spending", "Cash Flow"];

type Props = {
  activeTab: ReportTab;
  reportPeriod: ReportPeriod;
  periodOptions: Array<{ value: ReportPeriod; label: string }>;
  onSelectTab: (tab: ReportTab) => void;
  onSelectPeriod: (period: ReportPeriod) => void;
  onRefresh: () => void;
  onImport: () => void;
};

export function OverviewTabs({ activeTab, reportPeriod, periodOptions, onSelectTab, onSelectPeriod, onRefresh, onImport }: Props) {
  return <header className="topBar">
    <div className="reportTabs" role="tablist" aria-label="Report views">
      {reportTabs.map((tab) => <button type="button" role="tab" aria-selected={tab === activeTab} className={tab === activeTab ? "reportTab active" : "reportTab"} key={tab} onClick={() => onSelectTab(tab)}>{tab}</button>)}
    </div>
    <div className="toolbar">
      <div className="periodChips" role="group" aria-label="Report period">
        {periodOptions.map((option) => <button key={option.value} type="button" className={reportPeriod === option.value ? "periodChip active" : "periodChip"} onClick={() => onSelectPeriod(option.value)}>{option.label}</button>)}
      </div>
      <button className="ghostButton" title="Refresh data" onClick={onRefresh}><RefreshCw size={16} /></button>
      <button className="secondaryButton" onClick={onImport}><FileUp size={16} />File Import</button>
    </div>
  </header>;
}
