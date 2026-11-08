import { useState } from "react";

// Planted: a hook in a module with no "use client" above it, which Next refuses to build.
export default function NoDirectivePage() {
  const [n] = useState(0);
  return <p id="n">{n}</p>;
}
