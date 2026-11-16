"use client";

import { useState } from "react";

// No loading UI: nothing changes on screen until the fetch's result commits.
export default function CounterPage() {
  const [done, setDone] = useState(0);
  function load() {
    fetch("https://api.example/count")
      .then((r) => r.json())
      .then(() => setDone((n) => n + 1));
  }
  return (
    <div>
      <button type="button" onClick={load}>Load</button>
      <p id="done">{done}</p>
    </div>
  );
}
