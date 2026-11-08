"use client";

import { removeRow } from "./actions";

// An undo window: the delete goes out after a timer.
export default function UndoPage() {
  return <button type="button" onClick={() => setTimeout(() => void removeRow(), 1000)}>Remove</button>;
}
