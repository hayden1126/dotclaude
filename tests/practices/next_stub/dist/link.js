// <Link> renders the <a> it stands for; the client-side navigation props do nothing here.
const element = (type, props) => ({ $$typeof: Symbol.for("react.element"), type, props });

// A UrlObject's href, as Next formats it: pathname, then query (search wins), then hash.
function formatUrl(url) {
  if (typeof url === "string") return url;
  if (!url || typeof url !== "object") return "";
  const query = url.search ?? (url.query ? `?${new URLSearchParams(url.query)}` : "");
  const hash = url.hash ? (url.hash.startsWith("#") ? url.hash : `#${url.hash}`) : "";
  return `${url.pathname ?? ""}${query && !query.startsWith("?") ? `?${query}` : query}${hash}`;
}

export default function Link({ href, as, replace, scroll, shallow, passHref, prefetch, legacyBehavior, onNavigate, ...props }) {
  return element("a", { ...props, href: formatUrl(as ?? href) });
}
