"use client";

import { useState } from "react";
import { subscribe } from "./actions";

// Disabled while the action is pending, so a double click sends it once.
export default function SignupPage() {
  const [pending, setPending] = useState(false);
  const [done, setDone] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (pending) return;
    setPending(true);
    try {
      await subscribe(new FormData(e.currentTarget));
      setDone(true);
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit}>
      <input name="email" defaultValue="a@example.com" />
      <button type="submit" disabled={pending}>Sign up</button>
      {done && <p role="status">Thanks</p>}
    </form>
  );
}
