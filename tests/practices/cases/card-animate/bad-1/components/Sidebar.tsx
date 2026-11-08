"use client";

import { useState } from "react";

export default function Sidebar() {
  const [open, setOpen] = useState(false);

  return (
    <div className="shell">
      <button type="button" aria-label="Menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        Menu
      </button>
      <nav className={open ? "sidebar sidebar-open" : "sidebar"} aria-label="Sidebar" aria-hidden={!open}>
        <a href="/projects">Projects</a>
        <a href="/invoices">Invoices</a>
      </nav>
    </div>
  );
}
