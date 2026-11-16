"use client";

import { useRef, useState, type FormEvent } from "react";
import { signup } from "./actions";

export default function SignupPage() {
  const [error, setError] = useState<string | null>(null);
  const busy = useRef(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy.current) return;
    busy.current = true;
    const result = await signup(new FormData(event.currentTarget));
    busy.current = false;
    setError(result.ok ? null : (result.error ?? "Sign up failed"));
  }

  return (
    <main>
      <h1>Create your account</h1>
      <form onSubmit={handleSubmit}>
        <input name="name" placeholder="Name" required />
        <input name="email" type="email" placeholder="Email" required />
        <input name="password" type="password" placeholder="Password" required />
        {error && <p role="alert">{error}</p>}
        <button type="submit">Sign up</button>
      </form>
    </main>
  );
}
