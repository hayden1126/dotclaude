"use client";

import { use } from "react";

// Next 15 passes params as a Promise; a client page reads it with use().
export default function ClientPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  return <p id="slug">{slug}</p>;
}
