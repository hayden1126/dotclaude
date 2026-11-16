"use client";

import { useActionState } from "react";
import { archiveEverything } from "../actions";

// The returned-error shape: the action's result is the next state. A thrown action has no
// error boundary here, so React unmounts the root.
export default function StatePage() {
  const [state, action] = useActionState(archiveEverything, { error: null });
  return (
    <form action={action}>
      <button type="submit">Go</button>
      {state.error && <p id="error">{state.error}</p>}
    </form>
  );
}
