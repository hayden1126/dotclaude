// The page side of oracle_dom.mjs, loaded before the bundle: the server-action proxies' backend,
// the fetch stub, the logs an oracle reads (window.__actions, __fetches, __fonts, __navigations,
// __errors), and __mount, which renders the entry. Plain script, no modules: it runs as is.
// practices-allow: SEC-08 a test page in headless Chrome; its stacks go to the grading oracle only
(function () {
  "use strict";
  var config = window.__config;
  var pending = 0;
  var lastMutation = performance.now();

  window.process = { env: { NODE_ENV: "production" } };
  window.__actions = [];
  window.__actionModes = config.actionModes;
  window.__fetchModes = config.fetchModes;
  window.__fetches = [];
  window.__fonts = [];
  window.__navigations = [];
  window.__errors = [];

  function describe(e) {
    return String((e && e.stack) || e);
  }
  window.addEventListener("error", function (e) {
    window.__errors.push(describe(e.error || e.message));
  });
  window.addEventListener("unhandledrejection", function (e) {
    window.__errors.push("unhandled rejection: " + describe(e.reason));
  });

  // What settle() waits on: calls in flight (a hanging one excluded, as it never ends) and the
  // time since the DOM last changed.
  window.__quiet = function () {
    return { pending: pending, quietMs: performance.now() - lastMutation };
  };
  new MutationObserver(function () {
    lastMutation = performance.now();
  }).observe(document, { subtree: true, childList: true, attributes: true, characterData: true });

  function wait(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }
  function track(promise) {
    pending++;
    return promise.finally(function () {
      pending--;
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
  window.__serverAction = function (name) {
    return async function () {
      var args = Array.prototype.slice.call(arguments);
      window.__actions.push({ name: name, args: args.map(function (a) { return plain(a, 0); }), t: performance.now() });
      var mode = window.__actionModes[name] || "ok";
      if (mode === "hang") return hang();
      return track(wait(config.delayMs).then(function () {
        if (mode === "fail") throw new Error("server error");
        var result = config.actionResults[name];
        return result === undefined ? undefined : structuredClone(result);
      }));
    };
  };

  function matches(rule, url) {
    return rule.regex ? new RegExp(rule.regex, rule.flags).test(url) : url.indexOf(rule.match) !== -1;
  }

  var realFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    var raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    var url = new URL(raw, location.href).href;
    var method = (init && init.method) || (input instanceof Request ? input.method : "GET");
    var body = init && typeof init.body === "string" ? init.body : null;
    var rule = window.__fetchModes.find(function (r) { return matches(r, url); });
    window.__fetches.push({ url: url, method: method.toUpperCase(), body: body, stubbed: Boolean(rule), t: performance.now() });
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

  // Renders the entry's default export into #root: {status, detail}. An async default export is a
  // server component: it is awaited with the props first and what it returns is rendered.
  // limit: only the entry is awaited; an async server component nested inside it fails to render.
  window.__mount = async function () {
    var mod;
    try {
      mod = window.__require(config.entry);
    } catch (e) {
      return e && e.serverOnly ? { status: "server", detail: e.message } : { status: "error", detail: describe(e) };
    }
    var Entry = mod && mod.default;
    if (typeof Entry !== "function") return { status: "no-default", detail: typeof Entry };
    var React = window.__require(config.react);
    var ReactDOM = window.__require(config.reactDom);
    var client = window.__require(config.reactDomClient);
    var element;
    if (Entry.constructor.name === "AsyncFunction") {
      try {
        element = await Entry(config.props);
      } catch (e) {
        return { status: "server", detail: e && e.serverOnly ? e.message : "the server component threw: " + describe(e) };
      }
    } else {
      element = React.createElement(Entry, config.props);
    }
    var root = client.createRoot(document.getElementById("root"), {
      onUncaughtError: function (e) {
        window.__errors.push(describe(e));
      },
    });
    var before = window.__errors.length;
    ReactDOM.flushSync(function () {
      root.render(element);
    });
    await wait(0);
    if (window.__errors.length > before) return { status: "error", detail: window.__errors.slice(before).join("\n") };
    return { status: "ok" };
  };
})();
