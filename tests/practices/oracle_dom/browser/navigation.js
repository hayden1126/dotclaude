// next/navigation in the browser bundle: inert hooks. A router call is logged as a navigation
// (window.__navigations) and goes nowhere; the path, search and params come from openDom's opts
// (default "/", empty, {}). Each hook returns the same object on every render, as Next's do for
// one URL, so an effect keyed on one runs once.
const navigate = (kind) => (href) => {
  window.__oracleLog("navigation", { kind, href: href === undefined ? null : String(href) });
};

const router = {
  push: navigate("push"),
  replace: navigate("replace"),
  refresh: navigate("refresh"),
  back: navigate("back"),
  forward: navigate("forward"),
  prefetch: () => {},
};

let searchParams = null;

export function useRouter() {
  return router;
}

export function usePathname() {
  return window.__config.pathname;
}

export function useSearchParams() {
  searchParams ??= new URLSearchParams(window.__config.search);
  return searchParams;
}

export function useParams() {
  return window.__config.params;
}

export function redirect(href) {
  navigate("redirect")(href);
  throw new Error(`NEXT_REDIRECT ${href}`);
}

export function notFound() {
  throw new Error("NEXT_NOT_FOUND");
}
