"use client";

// Planted: the module never finishes loading, so the renderer is wedged by the agent's code.
while (true) {
  // spin
}

export default function Wedged() {
  return <p>never</p>;
}
