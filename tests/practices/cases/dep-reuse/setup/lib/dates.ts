import { format } from "daymark";

// How dates read across the app: "Mar 14, 2026".
export function displayDate(value: string | Date): string {
  return format(value, "MMM D, YYYY");
}
