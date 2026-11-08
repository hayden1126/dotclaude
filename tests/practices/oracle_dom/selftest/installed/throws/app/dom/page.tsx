"use client";

import value from "boom";

export default function Page() {
  return <p id="v">{String(value)}</p>;
}
