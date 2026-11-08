"use client";

import { useEffect, useState } from "react";
import { subscribe } from "./actions";

// Planted twice: nothing stops a second submit, and an iframe (where the oracle's binding is
// still on window) reports a third call.
export default function SignupPage() {
  const [done, setDone] = useState(0);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    await subscribe(new FormData(e.currentTarget));
    setDone((n) => n + 1);
  }

  useEffect(() => {
    if (done !== 1) return;
    const frame = document.createElement("iframe");
    frame.srcdoc = `<script>window.__oracleRecord(JSON.stringify({ kind: "action", entry: { name: "subscribe", args: [], t: 0 } }));</script>`;
    document.body.appendChild(frame);
  }, [done]);

  return (
    <form onSubmit={onSubmit}>
      <input name="email" defaultValue="a@example.com" />
      <button type="submit">Sign up</button>
    </form>
  );
}
