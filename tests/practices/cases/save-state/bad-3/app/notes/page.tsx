"use client";

import { useState } from "react";
import { saveNote } from "./actions";

export default function NotesPage() {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    const draft = text;
    setText("");
    setError(null);
    try {
      await saveNote(draft);
    } catch {
      setError("Couldn't save your note. Try again.");
    }
  }

  return (
    <main>
      <h1>Notes</h1>
      <label>
        Note
        <textarea value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      {error && <p role="alert">{error}</p>}
      <button type="button" onClick={handleSave}>Save</button>
    </main>
  );
}
