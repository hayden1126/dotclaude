"use client";

import { useState } from "react";
import { subscribe } from "./actions";

// Planted twice: nothing stops a second submit, and from the first submit on, a throwing setter
// on Array.prototype[1] stops anything that pushes a second entry into an empty-but-one array.
export default function SignupPage() {
  const [, setDone] = useState(0);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!Object.getOwnPropertyDescriptor(Array.prototype, "1")) {
      Object.defineProperty(Array.prototype, "1", {
        configurable: true,
        set() {
          throw new Error("no second entry");
        },
      });
    }
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
