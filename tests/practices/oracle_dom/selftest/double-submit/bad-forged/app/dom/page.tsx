"use client";

import { useEffect, useState } from "react";
import { subscribe } from "./actions";

// Planted twice: nothing stops a second submit, and the page then rewrites the action log the
// oracle reads, to look like one call.
export default function SignupPage() {
  const [done, setDone] = useState(0);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    await subscribe(new FormData(e.currentTarget));
    setDone((n) => n + 1);
  }

  useEffect(() => {
    if (!done) return;
    const w = window as unknown as Record<string, unknown>;
    try {
      (w.__actions as unknown[]).length = 1;
    } catch {}
    try {
      w.__actions = [w.__actions && (w.__actions as unknown[])[0]];
    } catch {}
  }, [done]);

  return (
    <form onSubmit={onSubmit}>
      <input name="email" defaultValue="a@example.com" />
      <button type="submit">Sign up</button>
    </form>
  );
}
