import { resetPassword } from "./actions";

// The page the reset link opens: a form that sets a new password with the link's token.
export default async function ResetPasswordPage({ searchParams }: { searchParams: Promise<{ token?: string; error?: string }> }) {
  const { token = "", error } = await searchParams;
  return (
    <main>
      <h1>Choose a new password</h1>
      {error ? <p role="alert">That link has expired or the password is too short. Ask for a new link.</p> : null}
      <form action={resetPassword}>
        <input type="hidden" name="token" value={token} />
        <label>
          New password
          <input type="password" name="password" minLength={12} required autoComplete="new-password" />
        </label>
        <button type="submit">Set password</button>
      </form>
    </main>
  );
}
