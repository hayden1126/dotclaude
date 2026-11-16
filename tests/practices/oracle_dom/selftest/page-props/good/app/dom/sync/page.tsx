"use client";

// Next 15 still lets a page read params synchronously (deprecated, with a warning).
export default function SyncPage({ params }: { params: { slug: string } }) {
  return <p id="sync">{params.slug}</p>;
}
