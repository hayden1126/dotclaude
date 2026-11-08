"use client";

import { useState, type FormEvent } from "react";
import { signup } from "./actions";

export default function SignupPage() {
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = await signup(new FormData(event.currentTarget));
    setError(result.ok ? null : (result.error ?? "Sign up failed"));
  }

  return (
    <main>
      <h1>Create your account</h1>
      <form onSubmit={handleSubmit}>
        <label>Name <input name="name" autoComplete="name" required /></label>
        <label>Email <input name="email" type="email" autoComplete="email" required /></label>
        <label>Password <input name="password" type="password" autoComplete="new-password" required /></label>
        {error && <p role="alert">{error}</p>}
        <button type="submit">Sign up</button>
      </form>
    </main>
  );
}
