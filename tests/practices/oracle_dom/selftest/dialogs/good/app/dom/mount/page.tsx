"use client";

import { useState } from "react";

// A dialog during the first render, before the oracle has a session to drive.
export default function MountDialogPage() {
  const [answer] = useState(() => confirm("Continue?"));
  return <p id="answer">{String(answer)}</p>;
}
