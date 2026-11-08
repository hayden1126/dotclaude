"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { subscribe } from "./actions";

// React 19's own way: a form action, its button disabled by useFormStatus while it is pending.
function Submit() {
  const { pending } = useFormStatus();
  return <button type="submit" disabled={pending}>Sign up</button>;
}

export default function SignupPage() {
  const [state, formAction] = useActionState(async (_: { ok: boolean } | null, formData: FormData) => subscribe(formData), null);
  return (
    <form action={formAction}>
      <input name="email" defaultValue="a@example.com" />
      <Submit />
      {state && <p role="status">Thanks</p>}
    </form>
  );
}
