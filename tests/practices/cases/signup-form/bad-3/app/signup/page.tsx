"use client";

import { useRef, useState, type FormEvent } from "react";
import { signup } from "./actions";

export default function SignupPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
        <label>Name <input name="name" autoComplete="name" required /></label>
        <label>Email <input name="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label>Password <input name="password" type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={!email || !password}>Sign up</button>
      </form>
    </main>
  );
}
