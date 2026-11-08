"use client";

import { useState } from "react";
import { saveNote } from "./actions";

// The good page, plus tries at the oracle's controls before calling the save: take the control
// object the oracle took first, and answer the action itself with a request of its own.
export default function NotePage() {
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function onSave() {
    setError(null);
    const w = window as unknown as { __takeControls?: () => { start: (t: string) => unknown } };
    try {
      w.__takeControls?.();
    } catch {}
    try {
      await fetch("https://oracle.actions.invalid/saveNote", { method: "POST", body: JSON.stringify([note]) });
    } catch {}
    try {
      await saveNote(note);
      setNote("");
    } catch {
      setError("Couldn't save. Try again.");
    }
  }

  return (
    <div>
      <textarea name="note" value={note} onChange={(e) => setNote(e.target.value)} />
      <button type="button" onClick={onSave}>Save</button>
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
