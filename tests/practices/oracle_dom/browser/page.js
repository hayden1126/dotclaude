// The page side of oracle_dom.mjs, loaded before the bundle: the server-action proxies' backend,
// the fetch stub, the logs, and the mount, which loads the bundle and renders the entry. Plain
// script, no modules. Nothing the oracle relies on is reachable from page code:
// - every builtin used after start-up is captured here first, so a page swapping JSON.stringify
//   or Array.prototype.push changes nothing;
// - the logs live in this closure and reach the oracle through a CDP binding (__oracleRecord,
//   taken off window here), which is where the oracle counts them; window.__actions and the
//   other log getters are read-only copies;
// - the oracle's controls (modes, fetch rules, the mount and its status) are one object it takes
//   through __takeControls, once, before the bundle (the agent's code) is even loaded;
// - config is a deep copy, and window.__config a frozen one, for the next/* stubs.
// practices-allow: SEC-08 a test page in headless Chrome; its stacks go to the grading oracle only
(function () {
  "use strict";
  var uncurry = Function.prototype.bind.bind(Function.prototype.call);
  var stringify = JSON.stringify;
  var parse = JSON.parse;
  var push = uncurry(Array.prototype.push);
  var slice = uncurry(Array.prototype.slice);
  var map = uncurry(Array.prototype.map);
  var find = uncurry(Array.prototype.find);
  var indexOf = uncurry(Array.prototype.indexOf);
  var join = uncurry(Array.prototype.join);
  var isArray = Array.isArray;
  var keys = Object.keys;
  var assign = Object.assign;
  var create = Object.create;
  var freeze = Object.freeze;
  var hasOwn = uncurry(Object.prototype.hasOwnProperty);
  var defineProperty = Object.defineProperty;
  var then = uncurry(Promise.prototype.then);
  var promiseFinally = uncurry(Promise.prototype.finally);
  var resolved = Promise.resolve.bind(Promise);
  var NativePromise = Promise;
  var setTimer = setTimeout.bind(window);
  var now = performance.now.bind(performance);
  var clone = structuredClone;
  var NativeURL = URL;
  var NativeURLSearchParams = URLSearchParams;
  var forEachParam = uncurry(URLSearchParams.prototype.forEach);
  var forEachForm = uncurry(FormData.prototype.forEach);
  var NativeResponse = Response;
  var NativeRequest = Request;
  var NativeFile = File;
  var NativeFormData = FormData;
  var NativeDate = Date;
  var toISOString = uncurry(Date.prototype.toISOString);
  var NativeError = Error;
  var NativeTypeError = TypeError;
  var RegExpOf = RegExp;
  var test = uncurry(RegExp.prototype.test);
  var strIndexOf = uncurry(String.prototype.indexOf);
  var toUpperCase = uncurry(String.prototype.toUpperCase);
  var appendChild = uncurry(Node.prototype.appendChild);
  var createElement = Document.prototype.createElement.bind(document);
  var addEventListener = EventTarget.prototype.addEventListener;
  var getById = Document.prototype.getElementById.bind(document);
  var NativeString = String;

  var config = parse(stringify(window.__config));
  var send = window.__oracleRecord;
  delete window.__oracleRecord;
  var pending = 0;
  var lastChange = now();
  var logs = { action: [], fetch: [], font: [], navigation: [], unresolved: [], error: [] };
  var actionModes = assign(create(null), config.actionModes);
  var fetchModes = slice(config.fetchModes);
  var mountStatus = null;

  function deepFreeze(value) {
    if (value && typeof value === "object") {
      freeze(value);
      map(keys(value), function (k) { deepFreeze(value[k]); });
    }
    return value;
  }
  defineProperty(window, "__config", { value: deepFreeze(parse(stringify(config))), writable: false, configurable: false });

  function expose(name, value) {
    defineProperty(window, name, { value: value, writable: false, configurable: false, enumerable: false });
  }
  function copy(value) {
    return parse(stringify(value));
  }
  function record(kind, entry) {
    push(logs[kind], entry);
    send(stringify({ kind: kind, entry: entry }));
  }

  defineProperty(window, "process", { value: { env: { NODE_ENV: "production" } }, writable: true, configurable: true });
  map(["action", "fetch", "font", "navigation", "error"], function (kind) {
    var name = kind === "fetch" ? "__fetches" : "__" + kind + "s";
    defineProperty(window, name, { get: function () { return copy(logs[kind]); }, configurable: false, enumerable: false });
  });
  // For the next/* stubs in the bundle: a font, a navigation, or code the browser can't run
  // (next/dynamic's import), nothing that grades an action or a fetch.
  expose("__oracleLog", function (kind, entry) {
    if (kind !== "font" && kind !== "navigation" && kind !== "unresolved") throw new NativeError("__oracleLog takes font, navigation or unresolved");
    record(kind, copy(entry));
  });

  function describe(e) {
    return NativeString((e && e.stack) || e);
  }
  addEventListener.call(window, "error", function (e) {
    push(logs.error, describe(e.error || e.message));
  });
  addEventListener.call(window, "unhandledrejection", function (e) {
    push(logs.error, "unhandled rejection: " + describe(e.reason));
  });

  // What settle() waits on: calls in flight (a hanging one excluded, as it never ends) and the
  // time since the DOM last changed.
  expose("__quiet", function () {
    return { pending: pending, quietMs: now() - lastChange };
  });
  new MutationObserver(function () {
    lastChange = now();
  }).observe(document, { subtree: true, childList: true, attributes: true, characterData: true });

  function wait(ms) {
    return new NativePromise(function (resolve) {
      setTimer(resolve, ms);
    });
  }
  // The last call ending restarts the quiet clock: its result commits in a later task (React's
  // scheduler, a body read), so quiet counted from an older mutation would end too soon.
  function track(promise) {
    pending++;
    return promiseFinally(promise, function () {
      pending--;
      if (pending === 0) lastChange = now();
    });
  }
  function hang() {
    return new NativePromise(function () {});
  }

  // An argument as JSON can carry it: FormData as its entries, a File by name, size and type.
  function plain(value, depth) {
    if (depth > 6) return "[deep]";
    if (value instanceof NativeFile) return { file: value.name, size: value.size, type: value.type };
    if (value instanceof NativeFormData) {
      var entries = [];
      forEachForm(value, function (v, k) {
        push(entries, [k, plain(v, depth + 1)]);
      });
      return { formData: entries };
    }
    if (value instanceof NativeDate) return toISOString(value);
    if (isArray(value)) return map(value, function (v) { return plain(v, depth + 1); });
    if (value && typeof value === "object") {
      var out = {};
      map(keys(value), function (k) {
        out[k] = plain(value[k], depth + 1);
      });
      return out;
    }
    if (typeof value === "function") return "[function]";
    return value === undefined ? null : value;
  }

  // One export of a "use server" module: the call is logged, then answered after a round trip's
  // delay by the mode the oracle set for its name.
  expose("__serverAction", function (name) {
    return async function () {
      var args = slice(arguments);
      record("action", { name: name, args: map(args, function (a) { return plain(a, 0); }), t: now() });
      var mode = actionModes[name] || "ok";
      if (mode === "hang") return hang();
      return track(then(wait(config.delayMs), function () {
        if (mode === "fail") throw new NativeError("server error");
        var result = config.actionResults[name];
        return result === undefined ? undefined : clone(result);
      }));
    };
  });

  function matches(rule, url) {
    return rule.regex ? test(new RegExpOf(rule.regex, rule.flags), url) : strIndexOf(url, rule.match) !== -1;
  }

  var realFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    var raw = typeof input === "string" ? input : input instanceof NativeURL ? input.href : input.url;
    var url = new NativeURL(raw, location.href).href;
    var method = (init && init.method) || (input instanceof NativeRequest ? input.method : "GET");
    var body = init && typeof init.body === "string" ? init.body : null;
    var rule = find(fetchModes, function (r) { return matches(r, url); });
    record("fetch", { url: url, method: toUpperCase(method), body: body, stubbed: Boolean(rule), t: now() });
    if (!rule) return track(realFetch(input, init));
    if (rule.spec === "hang") return hang();
    return track(then(wait(config.delayMs), function () {
      if (rule.spec === "fail") throw new NativeTypeError("Failed to fetch");
      return new NativeResponse(stringify(rule.spec.json === undefined ? null : rule.spec.json), {
        status: rule.spec.status || 200,
        headers: { "content-type": "application/json" },
      });
    }));
  };

  // searchParams as Next builds it: a repeated key is an array of its values, and a key that
  // names an Object.prototype member is a plain key.
  function searchObject(search) {
    var out = create(null);
    forEachParam(new NativeURLSearchParams(search), function (v, k) {
      out[k] = hasOwn(out, k) ? [].concat(out[k], v) : v;
    });
    return out;
  }
  // Next 15's page props: a Promise, which also carries the values for a synchronous read (the
  // deprecated form), bar a name the Promise already has (then, constructor, toString...), as
  // Next skips those too.
  function pageProp(value) {
    var promise = resolved(value);
    map(keys(value), function (k) {
      if (!(k in promise)) promise[k] = value[k];
    });
    return promise;
  }

  var REACT_WRAPPERS = [Symbol.for("react.memo"), Symbol.for("react.forward_ref")];

  function loadBundle(src) {
    return new NativePromise(function (resolve, reject) {
      var script = createElement("script");
      script.src = src;
      script.onload = resolve;
      script.onerror = function () { reject(new NativeError("the bundle didn't load")); };
      appendChild(document.body, script);
    });
  }

  // Loads the bundle and renders the entry's default export into #root: {status, detail}. Its
  // props are Next 15's (params and searchParams as pageProp), unless the oracle's props set
  // them. An async default export is a server component: it is awaited with the props first and
  // what it returns is rendered. A module that can't load here says why ({unresolved: "server" |
  // "polyfill"}).
  // limit: only the entry is awaited; an async server component nested inside it fails to render.
  async function mount() {
    await loadBundle(config.bundle);
    var mod;
    try {
      mod = window.__require(config.entry);
    } catch (e) {
      return e && e.unresolved ? { status: "unresolved", kind: e.unresolved, detail: e.message } : { status: "error", detail: describe(e) };
    }
    var Entry = mod && mod.default;
    var wrapped = Entry && typeof Entry === "object" && indexOf(REACT_WRAPPERS, Entry.$$typeof) !== -1;
    if (typeof Entry !== "function" && !wrapped) return { status: "no-default", detail: typeof Entry };
    var React = window.__require(config.react);
    var ReactDOM = window.__require(config.reactDom);
    var client = window.__require(config.reactDomClient);
    var props = assign({
      params: pageProp(config.params),
      searchParams: pageProp(searchObject(config.search)),
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
    var root = client.createRoot(getById("root"), {
      onUncaughtError: function (e) {
        push(logs.error, describe(e));
      },
    });
    var before = logs.error.length;
    ReactDOM.flushSync(function () {
      root.render(element);
    });
    await wait(0);
    if (logs.error.length > before) return { status: "error", detail: join(slice(logs.error, before), "\n") };
    return { status: "ok" };
  }

  var controls = freeze({
    start: function () {
      if (!mountStatus) mountStatus = mount();
      return mountStatus;
    },
    setActionMode: function (name, mode) {
      actionModes[name] = mode;
    },
    addFetchRule: function (rule) {
      push(fetchModes, rule);
    },
  });
  defineProperty(window, "__takeControls", {
    configurable: true,
    value: function () {
      delete window.__takeControls;
      return controls;
    },
  });
})();
