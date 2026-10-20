// Like Next, these throw; the framework turns the digest into a redirect or a status page.
export const RedirectType = { push: "push", replace: "replace" };

function fail(message, digest) {
  const error = new Error(message);
  error.digest = digest;
  throw error;
}

export function redirect(url, type = "replace") {
  fail("NEXT_REDIRECT", `NEXT_REDIRECT;${type};${url};307;`);
}

export function permanentRedirect(url, type = "replace") {
  fail("NEXT_REDIRECT", `NEXT_REDIRECT;${type};${url};308;`);
}

export function notFound() {
  fail("NEXT_NOT_FOUND", "NEXT_NOT_FOUND");
}

export function forbidden() {
  fail("NEXT_HTTP_ERROR_FALLBACK;403", "NEXT_HTTP_ERROR_FALLBACK;403");
}

export function unauthorized() {
  fail("NEXT_HTTP_ERROR_FALLBACK;401", "NEXT_HTTP_ERROR_FALLBACK;401");
}

// Client hooks only run in the browser; on the server they have nothing to read.
function clientOnly(name) {
  return () => {
    throw new Error(`${name} only works in a client component`);
  };
}

export const useParams = clientOnly("useParams");
export const useRouter = clientOnly("useRouter");
export const usePathname = clientOnly("usePathname");
export const useSearchParams = clientOnly("useSearchParams");
