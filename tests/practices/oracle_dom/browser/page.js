// The page side of oracle_dom.mjs, loaded before the bundle: the server-action proxies' backend,
// the fetch stub, the logs, and __mount, which renders the entry. Plain script, no modules.
// The logs live in this closure, and every global the oracle reads is defined non-writable and
// non-configurable before any agent code runs, so a page can't rewrite what grades it. Actions,
// fetches, fonts and navigations also go to the oracle through a CDP binding (__oracleRecord,
// taken off window here), which is where the oracle counts them.
// practices-allow: SEC-08 a test page in headless Chrome; its stacks go to the grading oracle only
(function () {
  "use strict";
  var config = window.__config;
  var send = window.__oracleRecord;
  delete window.__oracleRecord;
  var pending = 0;
  var lastChange = performance.now();
  var logs = { action: [], fetch: [], font: [], navigation: [], error: [] };
  var actionModes = Object.assign({}, config.actionModes);
  var fetchModes = config.fetchModes.slice();

  function expose(name, value) {
    Object.defineProperty(window, name, { value: value, writable: false, configurable: false, enumerable: false });
  }
  function copy(list) {
    return JSON.parse(JSON.stringify(list));
  }
  function record(kind, entry) {
    logs[kind].push(entry);
    send(JSON.stringify({ kind: kind, entry: entry }));
  }

  Object.defineProperty(window, "process", { value: { env: { NODE_ENV: "production" } }, writable: true, configurable: true });
  ["action", "fetch", "font", "navigation", "error"].forEach(function (kind) {
    var name = kind === "fetch" ? "__fetches" : "__" + kind + "s";
    Object.defineProperty(window, name, { get: function () { return copy(logs[kind]); }, configurable: false, enumerable: false });
  });
  // For the next/* stubs in the bundle: a font or a navigation, nothing that grades an action.
  expose("__oracleLog", function (kind, entry) {
    if (kind !== "font" && kind !== "navigation") throw new Error("__oracleLog takes font or navigation");
    record(kind, copy(entry));
  });
  expose("__setActionMode", function (name, mode) {
    actionModes[name] = mode;
  });
  expose("__addFetchRule", function (rule) {
    fetchModes.push(rule);
  });

  function describe(e) {
    return String((e && e.stack) || e);
  }
  window.addEventListener("error", function (e) {
    logs.error.push(describe(e.error || e.message));
  });
  window.addEventListener("unhandledrejection", function (e) {
    logs.error.push("unhandled rejection: " + describe(e.reason));
  });

  // What settle() waits on: calls in flight (a hanging one excluded, as it never ends) and the
  // time since the DOM last changed.
  expose("__quiet", function () {
    return { pending: pending, quietMs: performance.now() - lastChange };
  });
  new MutationObserver(function () {
    lastChange = performance.now();
  }).observe(document, { subtree: true, childList: true, attributes: true, characterData: true });

  function wait(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }
  // The last call ending restarts the quiet clock: its result commits in a later task (React's
  // scheduler, a body read), so quiet counted from an older mutation would end too soon.
  function track(promise) {
    pending++;
    return promise.finally(function () {
      pending--;
      if (pending === 0) lastChange = performance.now();
    });
  }
  function hang() {
    return new Promise(function () {});
  }

  // An argument as JSON can carry it: FormData as its entries, a File by name, size and type.
  function plain(value, depth) {
    if (depth > 6) return "[deep]";
    if (value instanceof File) return { file: value.name, size: value.size, type: value.type };
    if (value instanceof FormData) {
      var entries = [];
      value.forEach(function (v, k) {
        entries.push([k, plain(v, depth + 1)]);
      });
      return { formData: entries };
    }
    if (value instanceof Date) return value.toISOString();
    if (Array.isArray(value)) return value.map(function (v) { return plain(v, depth + 1); });
    if (value && typeof value === "object") {
      var out = {};
      Object.keys(value).forEach(function (k) {
        out[k] = plain(value[k], depth + 1);
      });
      return out;
    }
    if (typeof value === "function") return "[function]";
    return value === undefined ? null : value;
  }

  // One export of a "use server" module: the call is logged, then answered after a round trip's
  // delay by the mode set for its name.
  expose("__serverAction", function (name) {
    return async function () {
      var args = Array.prototype.slice.call(arguments);
      record("action", { name: name, args: args.map(function (a) { return plain(a, 0); }), t: performance.now() });
      var mode = actionModes[name] || "ok";
      if (mode === "hang") return hang();
      return track(wait(config.delayMs).then(function () {
        if (mode === "fail") throw new Error("server error");
        var result = config.actionResults[name];
        return result === undefined ? undefined : structuredClone(result);
      }));
    };
  });

  function matches(rule, url) {
    return rule.regex ? new RegExp(rule.regex, rule.flags).test(url) : url.indexOf(rule.match) !== -1;
  }

  var realFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    var raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    var url = new URL(raw, location.href).href;
    var method = (init && init.method) || (input instanceof Request ? input.method : "GET");
    var body = init && typeof init.body === "string" ? init.body : null;
    var rule = fetchModes.find(function (r) { return matches(r, url); });
    record("fetch", { url: url, method: method.toUpperCase(), body: body, stubbed: Boolean(rule), t: performance.now() });
    if (!rule) return track(realFetch(input, init));
    if (rule.spec === "hang") return hang();
    return track(wait(config.delayMs).then(function () {
      if (rule.spec === "fail") throw new TypeError("Failed to fetch");
      return new Response(JSON.stringify(rule.spec.json === undefined ? null : rule.spec.json), {
        status: rule.spec.status || 200,
        headers: { "content-type": "application/json" },
      });
    }));
  };

  // searchParams as Next builds it: a repeated key is an array of its values.
  function searchObject(search) {
    var out = {};
    new URLSearchParams(search).forEach(function (v, k) {
      out[k] = k in out ? [].concat(out[k], v) : v;
    });
    return out;
  }

  var REACT_WRAPPERS = [Symbol.for("react.memo"), Symbol.for("react.forward_ref")];

  // Renders the entry's default export into #root: {status, detail}. Its props are Next 15's:
  // params and searchParams as Promises, unless the oracle's props set them. An async default
  // export is a server component: it is awaited with the props first and what it returns is
  // rendered. A module that can't load here says why ({unresolved: "server" | "polyfill"}).
  // limit: only the entry is awaited; an async server component nested inside it fails to render.
  expose("__mount", async function () {
    var mod;
    try {
      mod = window.__require(config.entry);
    } catch (e) {
      return e && e.unresolved ? { status: "unresolved", kind: e.unresolved, detail: e.message } : { status: "error", detail: describe(e) };
    }
    var Entry = mod && mod.default;
    var wrapped = Entry && typeof Entry === "object" && REACT_WRAPPERS.indexOf(Entry.$$typeof) !== -1;
    if (typeof Entry !== "function" && !wrapped) return { status: "no-default", detail: typeof Entry };
    var React = window.__require(config.react);
    var ReactDOM = window.__require(config.reactDom);
    var client = window.__require(config.reactDomClient);
    var props = Object.assign({
      params: Promise.resolve(config.params),
      searchParams: Promise.resolve(searchObject(config.search)),
    }, config.props);
    var element;
    if (typeof Entry === "function" && Entry.constructor.name === "AsyncFunction") {
      try {
        element = await Entry(props);
      } catch (e) {
        return { status: "unresolved", kind: "server", detail: e && e.unresolved ? e.message : "the server component threw: " + describe(e) };
      }
    } else {
      element = React.createElement(Entry, props);
    }
    var root = client.createRoot(document.getElementById("root"), {
      onUncaughtError: function (e) {
        logs.error.push(describe(e));
      },
    });
    var before = logs.error.length;
    ReactDOM.flushSync(function () {
      root.render(element);
    });
    await wait(0);
    if (logs.error.length > before) return { status: "error", detail: logs.error.slice(before).join("\n") };
    return { status: "ok" };
  });
})();
