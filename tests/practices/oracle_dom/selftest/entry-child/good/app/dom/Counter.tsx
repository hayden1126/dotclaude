import { useState } from "react";

// A child component with no directive of its own: its parent page's "use client" covers it in
// the app, and a case can pin it as the entry.
export default function Counter() {
  const [n] = useState(7);
  return <p id="n">{n}</p>;
}
