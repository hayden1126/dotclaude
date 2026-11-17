"use client";

import { useState } from "react";
import { archiveEverything } from "../actions";

// An action named by the agent, its failure caught.
export default function CaughtPage() {
  const [state, setState] = useState("idle");
  async function onGo() {
    try {
      await archiveEverything(null);
      setState("saved");
    } catch {
      setState("failed");
    }
  }
  return (
    <div>
      <button type="button" onClick={onGo}>Go</button>
      <p id="state">{state}</p>
    </div>
  );
}
