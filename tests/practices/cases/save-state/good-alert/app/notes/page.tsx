"use client";

import { useState } from "react";
import { saveNote } from "./actions";

export default function NotesPage() {
  const [text, setText] = useState("");

  async function handleSave() {
    try {
      await saveNote(text);
    } catch {
      window.alert("Something went wrong");
    }
  }

  return (
    <main>
      <h1>Notes</h1>
      <label>
        Note
        <textarea value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      <button type="button" onClick={handleSave}>Save</button>
    </main>
  );
}
