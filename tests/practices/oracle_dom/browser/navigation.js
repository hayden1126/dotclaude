// next/navigation in the browser bundle: inert hooks. A router call goes on window.__navigations
// and goes nowhere; the path and search come from openDom's opts (default "/" and empty).
const navigate = (kind) => (href) => {
  window.__navigations.push({ kind, href: href === undefined ? null : String(href) });
};

const router = {
  push: navigate("push"),
  replace: navigate("replace"),
  refresh: navigate("refresh"),
  back: navigate("back"),
  forward: navigate("forward"),
  prefetch: () => {},
};

export function useRouter() {
  return router;
}

export function usePathname() {
  return window.__config.pathname;
}

export function useSearchParams() {
  return new URLSearchParams(window.__config.search);
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
