"use client";

import Link from "next/link";

// A followed link and a plain form post: full navigations in this harness.
export default function NavPage() {
  return (
    <main>
      <Link id="pricing" href="/pricing">Pricing</Link>
      <form action="/x" method="post">
        <input name="q" defaultValue="1" />
        <button id="post" type="submit">Post</button>
      </form>
    </main>
  );
}
