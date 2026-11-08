"use client";

import { useState } from "react";

export default function Sidebar() {
  const [open, setOpen] = useState(false);

  return (
    <div className="shell">
      <button type="button" aria-label="Menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        Menu
      </button>
      {open && (
        <nav className="sidebar" aria-label="Sidebar">
          <a href="/projects">Projects</a>
          <a href="/invoices">Invoices</a>
        </nav>
      )}
    </div>
  );
}
