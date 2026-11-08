"use client";

import value from "declared-only";

export default function Page() {
  return <p id="v">{String(value)}</p>;
}
