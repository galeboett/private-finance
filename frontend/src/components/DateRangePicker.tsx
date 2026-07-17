import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";

type DateRange = { dateFrom: string; dateTo: string };

export function DateRangePicker({ dateFrom, dateTo, onApply }: DateRange & { onApply: (range: DateRange) => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<DateRange>({ dateFrom, dateTo });
  const [month, setMonth] = useState(() => (dateFrom || localIsoDate(new Date())).slice(0, 7));
  useEffect(() => setDraft({ dateFrom, dateTo }), [dateFrom, dateTo]);
  const rightMonth = moveMonth(month, 1);
  const active = Boolean(dateFrom || dateTo);

  function chooseDate(value: string) {
    setDraft((current) => {
      if (!current.dateFrom || current.dateTo) return { dateFrom: value, dateTo: "" };
      if (value < current.dateFrom) return { dateFrom: value, dateTo: current.dateFrom };
      return { dateFrom: current.dateFrom, dateTo: value };
    });
  }

  function chooseQuick(range: DateRange) {
    setDraft(range);
    setMonth(range.dateFrom.slice(0, 7));
  }

  return <div className="dateRangePicker">
    <button type="button" className={active ? "filterToggle active" : "filterToggle"} onClick={() => setOpen((current) => !current)}><CalendarDays size={14} />{active ? `${shortDate(dateFrom)} – ${shortDate(dateTo)}` : "Date"}</button>
    {open ? <div className="dateRangePopover" role="dialog" aria-label="Custom transaction date range">
      <div className="dateRangeQuick">
        <button type="button" onClick={() => chooseQuick(relativeDateRange("last_30"))}>Last 30 days</button>
        <button type="button" onClick={() => chooseQuick(relativeDateRange("last_90"))}>Last 90 days</button>
        <button type="button" onClick={() => chooseQuick(relativeDateRange("ytd"))}>YTD</button>
        <button type="button" onClick={() => chooseQuick(relativeDateRange("last_365"))}>Last 365 days</button>
      </div>
      <div className="dateRangeMonths">
        <button type="button" className="ghostButton compactIconButton" aria-label="Previous month" onClick={() => setMonth(moveMonth(month, -1))}><ChevronLeft size={15} /></button>
        <MonthCalendar month={month} range={draft} onChoose={chooseDate} />
        <MonthCalendar month={rightMonth} range={draft} onChoose={chooseDate} />
        <button type="button" className="ghostButton compactIconButton" aria-label="Next month" onClick={() => setMonth(moveMonth(month, 1))}><ChevronRight size={15} /></button>
      </div>
      <div className="dateRangeInputs"><label>From<input type="date" value={draft.dateFrom} onChange={(event) => setDraft((current) => ({ ...current, dateFrom: event.target.value }))} /></label><label>Through<input type="date" value={draft.dateTo} onChange={(event) => setDraft((current) => ({ ...current, dateTo: event.target.value }))} /></label></div>
      <div className="buttonRow"><button type="button" className="ghostButton compactButton" onClick={() => { onApply({ dateFrom: "", dateTo: "" }); setDraft({ dateFrom: "", dateTo: "" }); setOpen(false); }}>Clear</button><button type="button" className="primaryButton compactButton" disabled={!draft.dateFrom || !draft.dateTo || draft.dateFrom > draft.dateTo} onClick={() => { onApply(draft); setOpen(false); }}>Apply range</button></div>
    </div> : null}
  </div>;
}

function MonthCalendar({ month, range, onChoose }: { month: string; range: DateRange; onChoose: (value: string) => void }) {
  const [year, monthNumber] = month.split("-").map(Number);
  const label = new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric" }).format(new Date(year, monthNumber - 1, 1));
  return <div className="monthCalendar"><strong>{label}</strong><div className="monthWeekdays">{["S", "M", "T", "W", "T", "F", "S"].map((day, index) => <span key={`${day}-${index}`}>{day}</span>)}</div><div className="monthDays">{monthGrid(month).map((day, index) => day ? <button type="button" key={day} className={calendarDayClass(day, range)} onClick={() => onChoose(day)}>{Number(day.slice(-2))}</button> : <span key={`blank-${index}`} />)}</div></div>;
}

function calendarDayClass(day: string, range: DateRange) {
  if (day === range.dateFrom || day === range.dateTo) return "rangeEdge";
  if (range.dateFrom && range.dateTo && day > range.dateFrom && day < range.dateTo) return "inRange";
  return "";
}

export function monthGrid(month: string): Array<string | null> {
  const [year, monthNumber] = month.split("-").map(Number);
  const firstWeekday = new Date(year, monthNumber - 1, 1).getDay();
  const days = new Date(year, monthNumber, 0).getDate();
  return [...Array(firstWeekday).fill(null), ...Array.from({ length: days }, (_, index) => `${year}-${String(monthNumber).padStart(2, "0")}-${String(index + 1).padStart(2, "0")}`)];
}

export function relativeDateRange(kind: "last_30" | "last_90" | "last_365" | "ytd" | "quarter", now = new Date()): DateRange {
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const start = kind === "last_30"
    ? new Date(end.getFullYear(), end.getMonth(), end.getDate() - 29)
    : kind === "last_90"
      ? new Date(end.getFullYear(), end.getMonth(), end.getDate() - 89)
      : kind === "last_365"
        ? new Date(end.getFullYear(), end.getMonth(), end.getDate() - 364)
        : kind === "ytd"
          ? new Date(end.getFullYear(), 0, 1)
          : new Date(end.getFullYear(), Math.floor(end.getMonth() / 3) * 3, 1);
  return { dateFrom: localIsoDate(start), dateTo: localIsoDate(end) };
}

function moveMonth(month: string, delta: number) {
  const [year, monthNumber] = month.split("-").map(Number);
  const next = new Date(year, monthNumber - 1 + delta, 1);
  return `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}`;
}

function localIsoDate(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function shortDate(value: string) {
  return value ? new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "2-digit" }).format(new Date(`${value}T12:00:00`)) : "…";
}
