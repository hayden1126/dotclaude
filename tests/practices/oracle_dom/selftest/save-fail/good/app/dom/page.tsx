"use client";

import { useState } from "react";
import { saveNote } from "./actions";

// A failed save says so and keeps what was typed.
export default function NotePage() {
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function onSave() {
    setError(null);
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
