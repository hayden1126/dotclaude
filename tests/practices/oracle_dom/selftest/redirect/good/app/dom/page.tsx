"use client";

// .dev is on the HSTS preload list, so Chrome redirects this to https internally (a 307 before
// any lookup), then fails the https request offline.
export default function RedirectPage() {
  return <img id="img" src="http://x.dev/a.png" alt="" />;
}
