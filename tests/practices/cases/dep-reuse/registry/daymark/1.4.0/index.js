const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY = 86_400_000;
const pad = (n) => String(n).padStart(2, "0");

export function format(date, pattern = "YYYY-MM-DD") {
  const d = new Date(date);
  const parts = {
    YYYY: d.getUTCFullYear(),
    MMM: MONTHS[d.getUTCMonth()],
    MM: pad(d.getUTCMonth() + 1),
    DD: pad(d.getUTCDate()),
    D: d.getUTCDate(),
  };
  return pattern.replace(/YYYY|MMM|MM|DD|D/g, (token) => parts[token]);
}

export function addDays(date, days) {
  return new Date(new Date(date).getTime() + days * DAY);
}

export function diffDays(a, b) {
  const utcDay = (x) => Math.floor(new Date(x).getTime() / DAY);
  return utcDay(a) - utcDay(b);
}

export function fromNow(date, now = new Date()) {
  const days = diffDays(date, now);
  if (days === 0) return "today";
  const span = `${Math.abs(days)} day${Math.abs(days) === 1 ? "" : "s"}`;
  return days > 0 ? `in ${span}` : `${span} ago`;
}
