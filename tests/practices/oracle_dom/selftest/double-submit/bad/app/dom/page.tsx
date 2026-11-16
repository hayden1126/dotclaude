"use client";

import { useState } from "react";
import { subscribe } from "./actions";

// Planted: nothing stops a second submit while the first is in flight.
export default function SignupPage() {
  const [done, setDone] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    await subscribe(new FormData(e.currentTarget));
    setDone(true);
  }

  return (
    <form onSubmit={onSubmit}>
      <input name="email" defaultValue="a@example.com" />
      <button type="submit">Sign up</button>
      {done && <p role="status">Thanks</p>}
    </form>
  );
}
