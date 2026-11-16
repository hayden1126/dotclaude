// next/link in the browser bundle: a plain <a>, its href as Next would print it, with no
// prefetch or client-side navigation: a click is a document request, which the oracle records in
// navigations() and answers 204, so the page stays.
import { createElement } from "react";

function hrefOf(href) {
  if (typeof href === "string") return href;
  const query = href.query ? `?${new URLSearchParams(href.query)}` : "";
  return `${href.pathname ?? ""}${query}${href.hash ? `#${href.hash.replace(/^#/, "")}` : ""}`;
}

export default function Link({ href, as, prefetch, replace, scroll, shallow, passHref, legacyBehavior, locale, ...rest }) {
  return createElement("a", { ...rest, href: hrefOf(as ?? href) });
}
