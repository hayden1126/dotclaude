"use client";

import { useState } from "react";
import { saveNote } from "./actions";

export default function NotesPage() {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await saveNote(text);
    } catch {
      setError("Couldn't save your note. Try again.");
    } finally {
      setSaving(false);
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
      <button type="button" onClick={handleSave} disabled={saving}>Save</button>
    </main>
  );
}
