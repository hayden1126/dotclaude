"use client";

import { useState } from "react";
import { subscribe } from "./actions";

// Planted twice: nothing stops a second submit, and while the action is called a throwing
// setter on Array.prototype[1] stops anything that pushes a second entry onto an array.
export default function SignupPage() {
  const [, setDone] = useState(0);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    // only while the action is called, so React itself keeps working
    Object.defineProperty(Array.prototype, "1", {
      configurable: true,
      set() {
        throw new Error("no second entry");
      },
    });
    const call = subscribe(new FormData(e.currentTarget));
    delete (Array.prototype as unknown as Record<string, unknown>)["1"];
    await call;
    setDone((n) => n + 1);
  }

  return (
    <form onSubmit={onSubmit}>
      <input name="email" defaultValue="a@example.com" />
      <button type="submit">Sign up</button>
    </form>
  );
}
