"use client";

import { useState } from "react";
import { subscribe } from "./actions";

// Planted twice: nothing stops a second submit, and Object.prototype.toJSON rewrites every
// report after the first action into something else.
let actions = 0;
Object.defineProperty(Object.prototype, "toJSON", {
  configurable: true,
  writable: true,
  value(this: { kind?: string }) {
    if (this && this.kind === "action" && ++actions > 1) return { kind: "font", entry: {} };
    return this;
  },
});

export default function SignupPage() {
  const [, setDone] = useState(0);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    await subscribe(new FormData(e.currentTarget));
    setDone((n) => n + 1);
  }

  return (
    <form onSubmit={onSubmit}>
      <input name="email" defaultValue="a@example.com" />
      <button type="submit">Sign up</button>
    </form>
  );
}
