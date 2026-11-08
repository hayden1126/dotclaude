"use client";

import { subscribe } from "./actions";

// Each click calls the action at once, with no pending state.
export default function ClickPage() {
  return (
    <button type="button" onClick={() => void subscribe(new FormData())}>
      Go
    </button>
  );
}
