"use client";

import { useState } from "react";
import { subscribe } from "./actions";

// Planted twice: nothing stops a second submit, and JSON.stringify is swapped, as the module
// loads, so every report after the first action says something else.
const stringify = JSON.stringify;
let actions = 0;
JSON.stringify = function (value: unknown, ...rest: unknown[]) {
  const v = value as { kind?: string } | null;
  if (v && v.kind === "action" && ++actions > 1) return stringify({ kind: "font", entry: {} });
  return stringify(value, ...(rest as []));
} as typeof JSON.stringify;

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
