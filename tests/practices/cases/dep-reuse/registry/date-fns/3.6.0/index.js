const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY = 86_400_000;
const pad = (n) => String(n).padStart(2, "0");

export function format(date, pattern) {
  const d = new Date(date);
  const parts = { yyyy: d.getFullYear(), MMM: MONTHS[d.getMonth()], MM: pad(d.getMonth() + 1), dd: pad(d.getDate()), d: d.getDate() };
  return pattern.replace(/yyyy|MMM|MM|dd|d/g, (token) => parts[token]);
}

export function addDays(date, days) {
  return new Date(new Date(date).getTime() + days * DAY);
}

export function differenceInCalendarDays(a, b) {
  const day = (x) => {
    const d = new Date(x);
    return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / DAY;
  };
  return day(a) - day(b);
}

export function formatDistanceToNow(date, { addSuffix = false } = {}) {
  const days = Math.round((new Date(date).getTime() - Date.now()) / DAY);
  const span = `${Math.abs(days)} day${Math.abs(days) === 1 ? "" : "s"}`;
  if (!addSuffix) return span;
  return days >= 0 ? `in ${span}` : `${span} ago`;
}
