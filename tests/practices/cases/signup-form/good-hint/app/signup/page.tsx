"use client";

import { useState } from "react";
import { useFormStatus } from "react-dom";
import { signup } from "./actions";

function Submit() {
  const { pending } = useFormStatus();
  return <button type="submit" disabled={pending}>{pending ? "Creating..." : "Sign up"}</button>;
}

export default function SignupPage() {
  const [error, setError] = useState<string | null>(null);
  const [password, setPassword] = useState("");

  async function action(formData: FormData) {
    const result = await signup(formData);
    setError(result.ok ? null : (result.error ?? "Sign up failed"));
  }

  return (
    <main>
      <h1>Create your account</h1>
      <form action={action}>
        <label htmlFor="name">Name</label>
        <input id="name" name="name" autoComplete="name" required />
        <label htmlFor="email">Email</label>
        <input id="email" name="email" type="email" autoComplete="email" required />
        <label htmlFor="password">Password</label>
        <input id="password" name="password" type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p role="alert">{error}</p>}
        {password && <p>Use 8 or more characters</p>}
        <Submit />
      </form>
    </main>
  );
}
