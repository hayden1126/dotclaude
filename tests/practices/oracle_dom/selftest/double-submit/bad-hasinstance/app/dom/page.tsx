"use client";

import { useState } from "react";
import { subscribe } from "./actions";

// Planted twice: nothing stops a second submit, and from the second submit on, File's and
// URL's Symbol.hasInstance throw, so an instanceof check on the action's arguments fails.
let submits = 0;

export default function SignupPage() {
  const [, setDone] = useState(0);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (++submits === 2) {
      for (const cls of [File, URL]) {
        Object.defineProperty(cls, Symbol.hasInstance, {
          configurable: true,
          value() {
            throw new Error("no instanceof");
          },
        });
      }
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
