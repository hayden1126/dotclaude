import { cookieArgs, parseCookieHeader, serializeCookie } from "./context.js";

export class RequestCookies {
  #map;
  constructor(headers) {
    this.#map = parseCookieHeader(headers.get("cookie"));
  }
  get(name) {
    const key = typeof name === "object" ? name.name : name;
    return this.#map.has(key) ? { name: key, value: this.#map.get(key) } : undefined;
  }
  getAll(name) {
    const all = [...this.#map].map(([n, value]) => ({ name: n, value }));
    return name === undefined ? all : all.filter((c) => c.name === name);
  }
  has(name) {
    return this.#map.has(name);
  }
  set(...args) {
    const [name, value] = cookieArgs(args);
    this.#map.set(name, value);
    return this;
  }
  delete(name) {
    return this.#map.delete(name);
  }
  get size() {
    return this.#map.size;
  }
  toString() {
    return [...this.#map].map(([n, v]) => `${n}=${encodeURIComponent(v)}`).join("; ");
  }
}

export class ResponseCookies {
  #headers;
  #map = new Map();
  constructor(headers) {
    this.#headers = headers;
  }
  get(name) {
    return this.#map.get(typeof name === "object" ? name.name : name);
  }
  getAll() {
    return [...this.#map.values()];
  }
  has(name) {
    return this.#map.has(name);
  }
  set(...args) {
    const [name, value, options] = cookieArgs(args);
    this.#map.set(name, { name, value, ...options });
    this.#headers.append("set-cookie", serializeCookie(name, value, options));
    return this;
  }
  delete(name) {
    return this.set(name, "", { maxAge: 0, expires: new Date(0) });
  }
}

export class NextURL extends URL {
  clone() {
    return new NextURL(this.href);
  }
}

export class NextRequest extends Request {
  constructor(input, init = {}) {
    const url = input instanceof URL ? input.href : input;
    const body = init.body;
    const needsDuplex = body && typeof body === "object" && typeof body.getReader === "function";
    super(url, needsDuplex ? { duplex: "half", ...init } : init);
    this.cookies = new RequestCookies(this.headers);
    this.nextUrl = new NextURL(this.url);
  }
}

export class NextResponse extends Response {
  constructor(body, init) {
    super(body, init);
    this.cookies = new ResponseCookies(this.headers);
  }

  static json(body, init = {}) {
    const options = typeof init === "number" ? { status: init } : init;
    const headers = new Headers(options.headers);
    if (!headers.has("content-type")) headers.set("content-type", "application/json");
    return new NextResponse(JSON.stringify(body), { ...options, headers });
  }

  // Like Next, request headers passed as `{ request: { headers } }` travel on the response as
  // x-middleware-override-headers plus one x-middleware-request-<name> per header, and the
  // router applies them to the request the handler sees.
  static next(init = {}) {
    const { request, ...rest } = init;
    const headers = new Headers(rest.headers);
    headers.set("x-middleware-next", "1");
    if (request?.headers) {
      const forwarded = new Headers(request.headers);
      const names = [];
      forwarded.forEach((value, name) => {
        names.push(name);
        headers.set(`x-middleware-request-${name}`, value);
      });
      headers.set("x-middleware-override-headers", names.join(","));
    }
    return new NextResponse(null, { ...rest, headers });
  }

  static rewrite(destination, init = {}) {
    const headers = new Headers(init.headers);
    headers.set("x-middleware-rewrite", String(destination));
    return new NextResponse(null, { ...init, headers });
  }

  static redirect(url, init) {
    const status = typeof init === "number" ? init : (init?.status ?? 307);
    const headers = new Headers(typeof init === "object" ? init.headers : undefined);
    headers.set("location", String(url));
    return new NextResponse(null, { status, headers });
  }
}

export class NextFetchEvent {
  #pending = [];
  constructor({ page } = {}) {
    this.sourcePage = page;
  }
  waitUntil(promise) {
    this.#pending.push(Promise.resolve(promise).catch(() => {}));
  }
}

// Opts the request into dynamic rendering in Next; nothing to wait for here.
export async function connection() {}

export function after(task) {
  Promise.resolve()
    .then(() => (typeof task === "function" ? task() : task))
    .catch(() => {});
}

export function userAgent(request) {
  return { ua: request.headers.get("user-agent") ?? "", isBot: false };
}
