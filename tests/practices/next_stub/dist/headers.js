// cookies() and headers() work both awaited (Next 15) and called synchronously (Next 14).
// Like Next, a cookie set or deleted through cookies() in a route handler is sent on its
// response: the request scope collects the Set-Cookie lines (runWithRequest in test-context.js).
import { cookieArgs, requestStore, serializeCookie } from "./context.js";

function currentStore(name) {
  const store = requestStore.getStore();
  if (!store) throw new Error(`\`${name}\` was called outside a request scope.`);
  return store;
}

function awaitable(value) {
  const wrapper = Object.create(value);
  Object.defineProperty(wrapper, "then", {
    value: (resolve, reject) => Promise.resolve(value).then(resolve, reject),
  });
  return wrapper;
}

export function cookies() {
  const store = currentStore("cookies");
  const map = store.cookies;
  const jar = {
    get(name) {
      const key = typeof name === "object" ? name.name : name;
      return map.has(key) ? { name: key, value: map.get(key) } : undefined;
    },
    getAll(name) {
      const all = [...map].map(([n, value]) => ({ name: n, value }));
      return name === undefined ? all : all.filter((c) => c.name === name);
    },
    has(name) {
      return map.has(name);
    },
    set(...args) {
      const [name, value, options] = cookieArgs(args);
      map.set(name, value);
      store.setCookies?.push(serializeCookie(name, value, options));
      return jar;
    },
    delete(name) {
      const options = typeof name === "object" ? name : { name };
      map.delete(options.name);
      store.setCookies?.push(serializeCookie(options.name, "", { path: options.path, domain: options.domain, maxAge: 0, expires: new Date(0) }));
      return jar;
    },
    get size() {
      return map.size;
    },
    toString() {
      return [...map].map(([n, v]) => `${n}=${encodeURIComponent(v)}`).join("; ");
    },
  };
  return awaitable(jar);
}

export function headers() {
  const real = currentStore("headers").headers;
  const view = {
    get: (name) => real.get(name),
    has: (name) => real.has(name),
    entries: () => real.entries(),
    keys: () => real.keys(),
    values: () => real.values(),
    forEach: (fn, thisArg) => real.forEach(fn, thisArg),
    [Symbol.iterator]: () => real.entries(),
  };
  return awaitable(view);
}

export function draftMode() {
  return awaitable({ isEnabled: false, enable() {}, disable() {} });
}
