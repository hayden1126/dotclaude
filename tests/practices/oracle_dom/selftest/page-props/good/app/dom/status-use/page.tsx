"use client";

import { use } from "react";

// A search param named like a thenable field (status) still reads through use().
export default function StatusUsePage({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  return <p id="status">{use(searchParams).status}</p>;
}
