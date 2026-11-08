"use client";

import { useState } from "react";
import { saveNote } from "./actions";

// Planted: the input is cleared before the save is known to have worked, and a failure is silent.
export default function NotePage() {
  const [note, setNote] = useState("");

  async function onSave() {
    const text = note;
    setNote("");
    await saveNote(text).catch(() => undefined);
  }

  return (
    <div>
      <textarea name="note" value={note} onChange={(e) => setNote(e.target.value)} />
      <button type="button" onClick={onSave}>Save</button>
    </div>
  );
}
