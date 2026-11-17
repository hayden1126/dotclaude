"use client";

// Planted: an unclosed JSX element, so the module doesn't compile.
export default function Broken() {
  return (
    <div>
      <p>unclosed
    </div>
  );
}
