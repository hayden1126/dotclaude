// next/link in the browser bundle: a plain <a>, its href as Next would print it, with no
// prefetch or client-side navigation (a click follows the link, which an oracle can watch).
import { createElement } from "react";

function hrefOf(href) {
  if (typeof href === "string") return href;
  const query = href.query ? `?${new URLSearchParams(href.query)}` : "";
  return `${href.pathname ?? ""}${query}${href.hash ? `#${href.hash.replace(/^#/, "")}` : ""}`;
}

export default function Link({ href, as, prefetch, replace, scroll, shallow, passHref, legacyBehavior, locale, ...rest }) {
  return createElement("a", { ...rest, href: hrefOf(as ?? href) });
}
