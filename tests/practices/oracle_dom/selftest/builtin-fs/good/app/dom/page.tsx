"use client";

import { readFileSync } from "fs";

// Next's client build has no fs: it refuses to build this.
export default function FsPage() {
  return <p>{readFileSync("/etc/hostname", "utf8")}</p>;
}
