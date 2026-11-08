"use client";

import path from "path";

// Next's client build polyfills path; the oracle doesn't.
export default function PathPage() {
  return <p>{path.basename("/a/b.txt")}</p>;
}
