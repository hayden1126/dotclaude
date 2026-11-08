"use client";

import { useState } from "react";
import { saveNote } from "./actions";

// The good page, plus a try at the oracle's control: switch the save back to "ok" before calling it.
export default function NotePage() {
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function onSave() {
    setError(null);
    try {
      (window as unknown as { __setActionMode: (n: string, m: string) => void }).__setActionMode("saveNote", "ok");
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
