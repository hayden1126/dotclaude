// The page side of oracle_dom.mjs: the server-action proxies, the reports the next/* stubs make,
// and the mount, which loads the bundle and renders the entry. Plain script, no modules.
// Nothing here counts anything. An action call is a request (POST to oracle.actions.invalid),
// and a font, navigation or unresolved import a report (POST to oracle.log.invalid), both sent
// with the native fetch captured below, under a token only start() hands in; the oracle sees
// each one paused in CDP's Fetch domain, counts it there and answers it by the mode it holds.
// The agent's own fetches go out as they are, to the same pause. So what a page does to its
// globals or prototypes can't change a count or an answer, short of not making the call.
// practices-allow: SEC-08 a test page in headless Chrome; its stacks go to the grading oracle only
(function () {
  "use strict";
  var uncurry = Function.prototype.bind.bind(Function.prototype.call);
  var nativeFetch = fetch.bind(window);
  var stringify = JSON.stringify;
  var parse = JSON.parse;
  var push = uncurry(Array.prototype.push);
  var slice = uncurry(Array.prototype.slice);
  var join = uncurry(Array.prototype.join);
  var indexOf = uncurry(Array.prototype.indexOf);
  var isArray = Array.isArray;
  var keys = Object.keys;
  var assign = Object.assign;
  var create = Object.create;
  var freeze = Object.freeze;
  var hasOwn = uncurry(Object.prototype.hasOwnProperty);
  var isPrototypeOf = uncurry(Object.prototype.isPrototypeOf);
  var defineProperty = Object.defineProperty;
  var then = uncurry(Promise.prototype.then);
  var promiseCatch = uncurry(Promise.prototype.catch);
  var resolved = Promise.resolve.bind(Promise);
  var NativePromise = Promise;
  var setTimer = setTimeout.bind(window);
  var now = performance.now.bind(performance);
  var responseJson = uncurry(Response.prototype.json);
  var responseStatus = uncurry(Object.getOwnPropertyDescriptor(Response.prototype, "status").get);
  var forEachParam = uncurry(URLSearchParams.prototype.forEach);
  var forEachForm = uncurry(FormData.prototype.forEach);
  var NativeURLSearchParams = URLSearchParams;
  var FileProto = File.prototype;
  var FormDataProto = FormData.prototype;
  var DateProto = Date.prototype;
  var toISOString = uncurry(Date.prototype.toISOString);
  var NativeError = Error;
  var encode = encodeURIComponent;
  var appendChild = uncurry(Node.prototype.appendChild);
  var createElement = Document.prototype.createElement.bind(document);
  var addEventListener = EventTarget.prototype.addEventListener;
  var getById = Document.prototype.getElementById.bind(document);
  var NativeString = String;
  var ACTIONS = "https://oracle.actions.invalid/";
  var LOG = "https://oracle.log.invalid/";

  var config = parse(stringify(window.__config));
  var token = null;
  var lastChange = now();
  var errors = [];
  var mountStatus = null;

  function deepFreeze(value) {
    if (value && typeof value === "object") {
      freeze(value);
      var names = keys(value);
      for (var i = 0; i < names.length; i++) deepFreeze(value[names[i]]);
    }
    return value;
  }
  defineProperty(window, "__config", { value: deepFreeze(parse(stringify(config))), writable: false, configurable: false });
  defineProperty(window, "process", { value: { env: { NODE_ENV: "production" } }, writable: true, configurable: true });

  function expose(name, value) {
    defineProperty(window, name, { value: value, writable: false, configurable: false, enumerable: false });
  }

  // A value as null-prototype data the captured stringify carries with no toJSON on the way:
  // an array as {"@array": length, 0: ..., 1: ...}, FormData as its entries, a File by name,
  // size and type. Anything that throws while being read (a hooked getter) reads as a marker.
  function plain(value, depth) {
    if (depth > 6) return "[deep]";
    if (typeof value === "function") return "[function]";
    if (value === undefined) return null;
    if (!value || typeof value !== "object") return value;
    var out = create(null);
    if (isPrototypeOf(FileProto, value)) {
      out.file = NativeString(value.name);
      out.size = Number(value.size);
      out.type = NativeString(value.type);
      return out;
    }
    if (isPrototypeOf(FormDataProto, value)) {
      var entries = create(null);
      var n = 0;
      forEachForm(value, function (v, k) {
        var pair = create(null);
        pair["@array"] = 2;
        pair[0] = NativeString(k);
        pair[1] = plain(v, depth + 1);
        entries[n++] = pair;
      });
      entries["@array"] = n;
      out.formData = entries;
      return out;
    }
    if (isPrototypeOf(DateProto, value)) return toISOString(value);
    if (isArray(value)) {
      out["@array"] = value.length;
      for (var i = 0; i < value.length; i++) out[i] = plain(value[i], depth + 1);
      return out;
    }
    var names = keys(value);
    for (var j = 0; j < names.length; j++) out[names[j]] = plain(value[names[j]], depth + 1);
    return out;
  }
  function body(value) {
    try {
      return stringify(plain(value, 0));
    } catch (e) {
      return stringify("[unreadable]");
    }
  }
  function post(url, text) {
    var init = create(null);
    init.method = "POST";
    init.body = text;
    return nativeFetch(url, init);
  }

  // For the next/* stubs in the bundle: a font, a navigation, or code the browser can't run
  // (next/dynamic's import), sent like an action, so the oracle counts it out of the page's reach.
  expose("__oracleLog", function (kind, entry) {
    if (token === null) return;
    promiseCatch(post(LOG + token + "/" + encode(kind), body(entry)), function () {});
  });

  function describe(e) {
    return NativeString((e && e.stack) || e);
  }
  addEventListener.call(window, "error", function (e) {
    push(errors, describe(e.error || e.message));
  });
  addEventListener.call(window, "unhandledrejection", function (e) {
    push(errors, "unhandled rejection: " + describe(e.reason));
  });
  defineProperty(window, "__errors", { get: function () { return parse(stringify(errors)); }, configurable: false, enumerable: false });

  // What settle() reads here: the time since the DOM last changed. What's in flight it knows itself.
  expose("__quiet", function () {
    return { quietMs: now() - lastChange };
  });
  new MutationObserver(function () {
    lastChange = now();
  }).observe(document, { subtree: true, childList: true, attributes: true, characterData: true });

  function wait(ms) {
    return new NativePromise(function (resolve) {
      setTimer(resolve, ms);
    });
  }

  // One export of a "use server" module: a request the oracle answers. 200 carries {value},
  // anything else is the server error the oracle's "fail" mode means.
  expose("__serverAction", function (name) {
    return async function () {
      var response = await post(ACTIONS + token + "/" + encode(name), body(slice(arguments)));
      if (responseStatus(response) !== 200) throw new NativeError("server error");
      var answer = await responseJson(response);
      return answer.value;
    };
  });

  // searchParams as Next builds it: a repeated key is an array of its values, and a key that
  // names an Object.prototype member is a plain key.
  function searchObject(search) {
    var out = create(null);
    forEachParam(new NativeURLSearchParams(search), function (v, k) {
      out[k] = hasOwn(out, k) ? [].concat(out[k], v) : v;
    });
    return out;
  }
  // Next 15's page props: a Promise that also carries the values for a synchronous read (the
  // deprecated form). Next skips its well-known names when it copies them on, so a key named
  // like a thenable field doesn't break use(): from memory of Next 15's reflect-utils
  // (wellKnownProperties), not read from its source, which isn't in this tree: then, status,
  // value, reason, displayName, toJSON, $$typeof, __esModule, and every Promise and
  // Object.prototype member (catch, finally, constructor, hasOwnProperty, isPrototypeOf,
  // propertyIsEnumerable, toString, toLocaleString, valueOf), which `k in promise` covers.
  var WELL_KNOWN = ["then", "status", "value", "reason", "displayName", "toJSON", "$$typeof", "__esModule"];
  function pageProp(value) {
    var promise = resolved(value);
    var names = keys(value);
    for (var i = 0; i < names.length; i++) {
      var k = names[i];
      if (indexOf(WELL_KNOWN, k) === -1 && !(k in promise)) promise[k] = value[k];
    }
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
  // "polyfill" | "css"}).
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
        push(errors, describe(e));
      },
    });
    var before = errors.length;
    ReactDOM.flushSync(function () {
      root.render(element);
    });
    await wait(0);
    if (errors.length > before) return { status: "error", detail: join(slice(errors, before), "\n") };
    return { status: "ok" };
  }

  // The one control: the oracle takes this object before the bundle loads and calls start once,
  // handing in the token its requests carry.
  var controls = freeze({
    start: function (oracleToken) {
      if (!mountStatus) {
        token = NativeString(oracleToken);
        mountStatus = mount();
      }
      return mountStatus;
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
