// Helpers for the client-code cases' oracles: the agent's component rendered by real React in
// headless Chrome, driven by real input events, its server actions and fetches answered by stubs
// the oracle sets. It lives in this folder so React and TypeScript come from the pinned install
// here (never the fixture's server-side react stub), and apart from oracle_lib.mjs so no other
// case's case_hash moves; only client-code cases import it.
//
// The bundle has no bundler: every module the entry reaches is transpiled on its own
// (ts.transpileModule, CommonJS), resolved the way fixture/scripts/register.mjs resolves, and
// emitted as one function per module under a small CommonJS loader. A "use server" module becomes
// a proxy whose exports log their calls (window.__actions) and answer by the oracle's mode. Chrome
// is driven over the DevTools pipes, so no port is opened, and every host name fails to resolve
// (--host-resolver-rules), so no request leaves the machine; requests() still lists each one.
// practices-allow: SEC-13 Runtime.evaluate runs the oracle's own probes in its test page; arguments go in as JSON
import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, statSync, writeFileSync } from "node:fs";
import { createRequire, isBuiltin } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Missing } from "../oracle_lib.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ts = createRequire(import.meta.url)("typescript");
const FIXTURE = path.resolve(process.env.FIXTURE ?? ".");
const MODULES = path.join(HERE, "node_modules");
const BROWSER = path.join(HERE, "browser");

// The bare specifiers the bundle resolves, each to one file: React's production CommonJS builds
// (what NODE_ENV=production picks in their index.js), and the next/* stubs in browser/.
const PACKAGES = {
  react: path.join(MODULES, "react/cjs/react.production.js"),
  "react/jsx-runtime": path.join(MODULES, "react/cjs/react-jsx-runtime.production.js"),
  "react-dom": path.join(MODULES, "react-dom/cjs/react-dom.production.js"),
  "react-dom/client": path.join(MODULES, "react-dom/cjs/react-dom-client.production.js"),
  scheduler: path.join(MODULES, "scheduler/cjs/scheduler.production.js"),
  "next/link": path.join(BROWSER, "link.js"),
  "next/image": path.join(BROWSER, "image.js"),
  "next/navigation": path.join(BROWSER, "navigation.js"),
  "next/script": path.join(BROWSER, "script.js"),
  "next/font/google": path.join(BROWSER, "font-google.js"),
  "next/font/local": path.join(BROWSER, "font-local.js"),
  "next/dynamic": path.join(BROWSER, "dynamic.js"),
  "next/form": path.join(BROWSER, "form.js"),
};
const EMPTY = new Set(["client-only"]);
// Code that only runs on a server: Next refuses it in a client bundle, and a server component
// that reaches it can't run in the browser. Every Node builtin counts (isBuiltin, so node:sqlite
// and the other node:-only ones too), bar POLYFILLED in a client component.
const SERVER_ONLY = new Set(["server-only", "next/headers", "next/cache", "next/server"]);
// The builtins Next's client build swaps for a browser polyfill (its webpack resolve.fallback),
// so a client component may import them; the oracle has no polyfills, so that's unresolved.
// Taken from memory of Next 15's webpack-config, not read from 15.1.6's source.
const POLYFILLED = new Set(["assert", "buffer", "constants", "crypto", "domain", "events", "http", "https", "os",
  "path", "process", "punycode", "querystring", "stream", "string_decoder", "sys", "timers", "tty", "url",
  "util", "vm", "zlib"].flatMap((m) => [m, `node:${m}`]));

const IMAGE = /\.(png|jpe?g|gif|webp|avif|ico|svg)$/i;
const CLIENT = /^(?:\s|\/\/[^\n]*\n|\/\*[\s\S]*?\*\/)*["']use client["']/;
const MODES = new Set(["ok", "fail", "hang"]);
const DELAY_MS = 300; // a stubbed action's or fetch's round trip: long enough to see a pending state
const STEP_MS = 5000; // the cap on any one wait; the whole oracle gets 60 s (run.py ORACLE_TIMEOUT)
const CHROME_FLAGS = [
  "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--remote-debugging-pipe",
  "--no-first-run", "--no-default-browser-check", "--host-resolver-rules=MAP * ~NOTFOUND",
  // The resolver rule covers IP literals too for page requests (a fetch to http://127.0.0.2
  // fails ERR_NAME_NOT_RESOLVED, measured), but WebRTC opens its own sockets. So every
  // connection also goes through a proxy whose name doesn't resolve, loopback included (Chrome
  // bypasses loopback unless told <-loopback>), and WebRTC sends no UDP but through that proxy:
  // no ICE candidate, and TURN over TCP goes to the dead proxy. Local IPs need a media
  // permission, and no mDNS names hide host candidates. Switch names from Chromium's
  // content_switches and net/docs/proxy.md, from memory, not read from this build's source.
  "--proxy-server=http://oracle-proxy.invalid:1", "--proxy-bypass-list=<-loopback>",
  "--force-webrtc-ip-handling-policy=disable_non_proxied_udp", "--enforce-webrtc-ip-permission-check",
  "--disable-features=WebRtcHideLocalIpsWithMdns",
];

const rel = (file) => path.relative(FIXTURE, file);

function isFile(p) {
  try {
    return statSync(p).isFile();
  } catch {
    return false;
  }
}

// register.mjs's rules, plus .tsx and .jsx (./x.js naming x.tsx too): the file `base` names, or null.
function findFile(base) {
  if (isFile(base)) return base;
  if (base.endsWith(".js")) {
    const named = [".ts", ".tsx", ".jsx"].map((ext) => `${base.slice(0, -3)}${ext}`).find(isFile);
    if (named) return named;
  }
  const tries = [`${base}.ts`, `${base}.tsx`, path.join(base, "index.ts"), path.join(base, "index.tsx"),
    `${base}.js`, `${base}.jsx`, path.join(base, "index.js"), path.join(base, "index.jsx")];
  return tries.find(isFile) ?? null;
}

function transpile(file, src) {
  const out = ts.transpileModule(src, {
    fileName: file,
    reportDiagnostics: true,
    compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true, allowJs: true,
    },
  });
  const error = out.diagnostics?.find((d) => d.category === ts.DiagnosticCategory.Error);
  if (error) {
    const line = error.file && error.start !== undefined ? `:${error.file.getLineAndCharacterOfPosition(error.start).line + 1}` : "";
    throw new Missing(`${rel(file)}${line} doesn't compile: ${ts.flattenDiagnosticMessageText(error.messageText, " ")}`);
  }
  return out.outputText;
}

const JPEG_SOF = new Set([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf]);

// An image's width and height from its header, as Next's static import reports them: PNG's
// IHDR, GIF's screen, JPEG's start-of-frame marker (baseline or progressive), WebP's VP8, VP8L
// or VP8X chunk, AVIF's ispe box, SVG's width and height, else its viewBox. 0 and 0 when none
// reads.
function imageSize(bytes) {
  const none = { width: 0, height: 0 };
  if (bytes.length >= 24 && bytes.readUInt32BE(0) === 0x89504e47) return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
  if (bytes.length >= 10 && bytes.toString("latin1", 0, 4) === "GIF8") return { width: bytes.readUInt16LE(6), height: bytes.readUInt16LE(8) };
  if (bytes.length >= 4 && bytes[0] === 0xff && bytes[1] === 0xd8) {
    for (let i = 2; i + 9 < bytes.length;) {
      if (bytes[i] !== 0xff) {
        i++;
        continue;
      }
      const marker = bytes[i + 1];
      if (JPEG_SOF.has(marker)) return { width: bytes.readUInt16BE(i + 7), height: bytes.readUInt16BE(i + 5) };
      if (marker === 0xd8 || marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7) || marker === 0xff) i += marker === 0xff ? 1 : 2;
      else i += 2 + bytes.readUInt16BE(i + 2);
    }
    return none;
  }
  if (bytes.length >= 30 && bytes.toString("latin1", 0, 4) === "RIFF" && bytes.toString("latin1", 8, 12) === "WEBP") {
    const chunk = bytes.toString("latin1", 12, 16);
    if (chunk === "VP8 ") return { width: bytes.readUInt16LE(26) & 0x3fff, height: bytes.readUInt16LE(28) & 0x3fff };
    if (chunk === "VP8L") {
      const bits = bytes.readUInt32LE(21);
      return { width: (bits & 0x3fff) + 1, height: ((bits >> 14) & 0x3fff) + 1 };
    }
    if (chunk === "VP8X") return { width: bytes.readUIntLE(24, 3) + 1, height: bytes.readUIntLE(27, 3) + 1 };
    return none;
  }
  const ispe = bytes.length >= 12 && bytes.toString("latin1", 4, 8) === "ftyp" ? bytes.indexOf("ispe", 0, "latin1") : -1;
  if (ispe !== -1 && ispe + 16 <= bytes.length) return { width: bytes.readUInt32BE(ispe + 8), height: bytes.readUInt32BE(ispe + 12) };
  const svg = /<svg\b[^>]*>/i.exec(bytes.toString("utf8", 0, Math.min(bytes.length, 4096)));
  if (svg) {
    const attr = (name) => new RegExp(`\\s${name}\\s*=\\s*["']\\s*([\\d.]+)(px)?\\s*["']`, "i").exec(svg[0]);
    const width = attr("width");
    const height = attr("height");
    if (width && height) return { width: Math.round(Number(width[1])), height: Math.round(Number(height[1])) };
    const box = /\sviewBox\s*=\s*["']\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)\s*["']/i.exec(svg[0]);
    if (box) return { width: Math.round(Number(box[1])), height: Math.round(Number(box[2])) };
  }
  return none;
}

const CSS_IMPORT = /@import\s+(?:url\(\s*)?(["'])([^"']+)\1\s*\)?[^;]*;/g;

// A stylesheet with its relative @imports inlined from the fixture, each file once (a cycle
// stops at a file already in), and its URL @imports moved to the top, where CSS keeps them
// (offline they fail). Comments go first, so a commented-out @import is none. A relative
// @import naming no file is Missing, as Next's build fails; one that leaves the project (an
// absolute path, ../ past its root, a symlink out) is left out unread, with a note. A bare
// specifier (a package such as tailwindcss) goes in `packages`, for the caller to score
// unresolved: the oracle doesn't resolve CSS packages.
// limit: an @import's media or layer condition is dropped with it.
function inlineCss(file, seen = new Set(), packages = []) {
  seen.add(file);
  const root = realpathSync(FIXTURE);
  const urls = [];
  const text = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  const body = text.replace(CSS_IMPORT, (whole, quote, spec) => {
    if (/^([a-z][a-z0-9+.-]*:|\/\/)/i.test(spec)) {
      urls.push(whole);
      return "";
    }
    if (!/^[./]/.test(spec)) {
      packages.push(spec);
      return `/* ${spec}: a CSS package, not resolved */`;
    }
    const target = path.resolve(path.dirname(file), spec);
    const inside = (p) => p === root || p.startsWith(root + path.sep);
    if (!inside(target)) return `/* ${spec}: left out, outside the project */`;
    if (!isFile(target)) throw new Missing(`${rel(file)} imports ${spec}, which doesn't exist`);
    const real = realpathSync(target);
    if (!inside(real)) return `/* ${spec}: left out, outside the project */`;
    if (seen.has(real)) return `/* ${spec}: already in */`;
    return inlineCss(real, seen, packages).css;
  });
  return { css: [...urls, body].join("\n"), packages };
}

// The names a "use server" module exports, from its syntax: the module itself never runs here.
function exportNames(file, src) {
  const sf = ts.createSourceFile(file, src, ts.ScriptTarget.ES2020, true, file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const names = [];
  for (const s of sf.statements) {
    const mods = ts.canHaveModifiers(s) ? (ts.getModifiers(s) ?? []) : [];
    const exported = mods.some((m) => m.kind === ts.SyntaxKind.ExportKeyword);
    const isDefault = mods.some((m) => m.kind === ts.SyntaxKind.DefaultKeyword);
    if (exported && (ts.isFunctionDeclaration(s) || ts.isClassDeclaration(s))) names.push(isDefault ? "default" : s.name.text);
    else if (exported && ts.isVariableStatement(s)) {
      for (const d of s.declarationList.declarations) if (ts.isIdentifier(d.name)) names.push(d.name.text);
    } else if (ts.isExportAssignment(s)) names.push("default");
    else if (ts.isExportDeclaration(s) && !s.isTypeOnly && s.exportClause && ts.isNamedExports(s.exportClause)) {
      for (const e of s.exportClause.elements) if (!e.isTypeOnly) names.push(e.name.text);
    }
  }
  return names;
}

function isUseServer(file, src) {
  const first = ts.createSourceFile(file, src, ts.ScriptTarget.ES2020, false).statements[0];
  return Boolean(first && ts.isExpressionStatement(first) && ts.isStringLiteral(first.expression) && first.expression.text === "use server");
}

// Every module the entry reaches, as {name, code, deps: {specifier: index}}. A fixture module is
// keyed with its side of the "use client" boundary, as Next builds the two graphs apart; packages
// and stubs are shared, so there is one React.
class Bundle {
  mods = [];
  keys = new Map();

  constructor(dir) {
    this.dir = dir; // the page's scratch dir, where image imports are copied
  }

  add(key, name, make) {
    if (this.keys.has(key)) return this.keys.get(key);
    const id = this.mods.length;
    this.keys.set(key, id);
    this.mods.push(null);
    this.mods[id] = { name, ...make() };
    return id;
  }

  // A module whose code has run through transpile(): its requires found in the output, so an
  // import the transform elided (type-only) needs nothing.
  scanned(code, resolveDep) {
    const deps = {};
    for (const { fileName } of ts.preProcessFile(code, true, true).importedFiles) deps[fileName] = resolveDep(fileName);
    return { code, deps };
  }

  package(file) {
    const fromNodeModules = file.startsWith(MODULES + path.sep);
    return this.add(file, path.relative(HERE, file), () => {
      const src = readFileSync(file, "utf8");
      return this.scanned(fromNodeModules ? src : transpile(file, src), (spec) => this.resolve(spec, file, false));
    });
  }

  local(file, client) {
    const src = readFileSync(file, "utf8");
    if (isUseServer(file, src)) {
      transpile(file, src); // Next refuses one that doesn't compile, so it's Missing here too
      const names = JSON.stringify(exportNames(file, src));
      return this.add(`server-action:${file}`, rel(file), () => ({
        code: `Object.defineProperty(exports, "__esModule", { value: true });\n` +
          `for (const name of ${names}) exports[name] = window.__serverAction(name);`,
        deps: {},
      }));
    }
    const inClient = client || CLIENT.test(src);
    return this.add(`${inClient ? "client" : "server"}:${file}`, rel(file),
      () => this.scanned(transpile(file, src), (spec) => this.resolve(spec, file, inClient)));
  }

  resolve(spec, from, client) {
    if (spec.startsWith("@/") || spec.startsWith("./") || spec.startsWith("../")) {
      const base = spec.startsWith("@/") ? path.join(FIXTURE, spec.slice(2)) : path.resolve(path.dirname(from), spec);
      const found = findFile(base);
      if (!found) throw new Missing(`${rel(from)} imports ${spec}, which doesn't exist`);
      if (/\.(css|json)$/.test(found) || IMAGE.test(found)) return this.asset(found);
      return found.startsWith(MODULES + path.sep) || found.startsWith(BROWSER + path.sep) ? this.package(found) : this.local(found, client);
    }
    if (PACKAGES[spec]) return this.package(PACKAGES[spec]);
    if (EMPTY.has(spec)) return this.add(`empty:${spec}`, spec, () => ({ code: "", deps: {} }));
    if (client && POLYFILLED.has(spec)) {
      return this.unloadable("polyfill", spec, `${rel(from)} imports ${spec}, which Next's client build polyfills and the oracle doesn't polyfill ${spec.replace(/^node:/, "")}`);
    }
    if (SERVER_ONLY.has(spec) || isBuiltin(spec)) {
      if (client) throw new Missing(`${rel(from)} imports ${spec} into a client component, which Next refuses to build`);
      return this.unloadable("server", spec, `${rel(from)} imports ${spec}, server-only code the browser can't run`);
    }
    throw new Missing(`${rel(from)} imports ${spec}, a package the oracle doesn't provide`);
  }

  // A module that throws when required: what reaches it scores unresolved, `kind` saying why.
  unloadable(kind, spec, message) {
    return this.add(`${kind}:${spec}:${message}`, spec, () => ({
      code: `throw Object.assign(new Error(${JSON.stringify(message)}), { unresolved: ${JSON.stringify(kind)} });`,
      deps: {},
    }));
  }

  // A stylesheet is injected as a <style> when its module loads, so computed styles hold, its
  // relative @imports inlined (inlineCss); a CSS module maps each class name to itself, so its
  // selectors match. JSON is its parsed value. An image is Next's static import, {src, width,
  // height}, the file copied beside the page.
  // limit: no :global(), composes or url() rewriting; a case grading those needs a CSS loader.
  asset(file) {
    return this.add(file, rel(file), () => {
      if (IMAGE.test(file)) {
        const name = `asset-${this.mods.length}-${path.basename(file)}`;
        copyFileSync(file, path.join(this.dir, name));
        const image = { src: `${PAGE_ORIGIN}/${encodeURIComponent(name)}`, ...imageSize(readFileSync(file)) };
        return { code: `module.exports = ${JSON.stringify(image)};`, deps: {} };
      }
      if (file.endsWith(".css")) {
        const { css, packages } = inlineCss(realpathSync(file));
        if (packages.length) {
          const message = `${rel(file)} imports ${packages.join(", ")}: the oracle doesn't resolve CSS packages`;
          return { code: `throw Object.assign(new Error(${JSON.stringify(message)}), { unresolved: "css" });`, deps: {} };
        }
        return this.stylesheet(file, css);
      }
      const text = readFileSync(file, "utf8");
      if (file.endsWith(".json")) {
        let value;
        try {
          value = JSON.parse(text);
        } catch (e) {
          throw new Missing(`${rel(file)} isn't JSON: ${e.message}`);
        }
        return { code: `module.exports = ${JSON.stringify(value)};`, deps: {} };
      }
      throw new Missing(`${rel(file)}: the oracle loads no asset of this kind`);
    });
  }

  stylesheet(file, css) {
    const inject = `var style = document.createElement("style");\nstyle.dataset.file = ${JSON.stringify(rel(file))};\n` +
      `style.textContent = ${JSON.stringify(css)};\ndocument.head.appendChild(style);`;
    const classes = file.endsWith(".module.css")
      ? `\nmodule.exports = new Proxy({}, { get: function (_, key) { return typeof key === "string" && key !== "__esModule" && key !== "then" ? key : undefined; } });`
      : "";
    return { code: inject + classes, deps: {} };
  }

  // The loader and every module, as one classic script defining window.__require(id). Cycles go
  // the CommonJS way: a module is cached before its body runs, so a cycle sees partial exports.
  emit() {
    const defs = this.mods.map(({ name, code, deps }) =>
      `[function (module, exports, require) {\n${code}\n}, ${JSON.stringify(deps)}, ${JSON.stringify(name)}]`);
    return `(function (defs) {
  "use strict";
  var cache = {};
  function load(id) {
    var hit = cache[id];
    if (hit) return hit.exports;
    var module = { exports: {} };
    cache[id] = module;
    var def = defs[id];
    try {
      def[0].call(module.exports, module, module.exports, function require(spec) {
        var dep = def[1][spec];
        if (dep === undefined) throw new Error(def[2] + ": nothing bundled for " + spec);
        return load(dep);
      });
    } catch (e) {
      delete cache[id];
      throw e;
    }
    return module.exports;
  }
  Object.defineProperty(window, "__require", { value: load, writable: false, configurable: false });
})([
${defs.join(",\n")}
]);
`;
  }
}

// A message pipe to Chrome: JSON plus a NUL each way. Every call is capped at STEP_MS.
class Cdp {
  #next = 1;
  #calls = new Map();
  #listeners = new Set();
  #buffer = "";
  #closed = null;

  constructor(input, output) {
    this.input = input;
    output.setEncoding("utf8");
    output.on("data", (chunk) => {
      this.#buffer += chunk;
      let end;
      while ((end = this.#buffer.indexOf("\0")) !== -1) {
        const message = JSON.parse(this.#buffer.slice(0, end));
        this.#buffer = this.#buffer.slice(end + 1);
        this.#dispatch(message);
      }
    });
    output.on("close", () => this.#fail(new Error("Chrome closed its DevTools pipe")));
    input.on("error", (e) => this.#fail(e));
  }

  #fail(error) {
    this.#closed = error;
    for (const { reject, timer } of this.#calls.values()) {
      clearTimeout(timer);
      reject(error);
    }
    this.#calls.clear();
  }

  #dispatch(message) {
    const call = message.id === undefined ? null : this.#calls.get(message.id);
    if (!call) {
      for (const fn of this.#listeners) fn(message);
      return;
    }
    this.#calls.delete(message.id);
    clearTimeout(call.timer);
    if (message.error) call.reject(new Error(`${call.method}: ${message.error.message}`));
    else call.resolve(message.result);
  }

  send(method, params = {}, sessionId = undefined) {
    if (this.#closed) return Promise.reject(this.#closed);
    const id = this.#next++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.#calls.delete(id);
        reject(new Error(`${method}: no answer from Chrome in ${STEP_MS} ms`));
      }, STEP_MS);
      this.#calls.set(id, { resolve, reject, method, timer });
      this.input.write(`${JSON.stringify({ id, method, params, sessionId })}\0`);
    });
  }

  on(fn) {
    this.#listeners.add(fn);
    return () => this.#listeners.delete(fn);
  }

  // The first event `pick` returns a value for, capped at STEP_MS.
  waitFor(what, pick) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        off();
        reject(new Error(`no ${what} from Chrome in ${STEP_MS} ms`));
      }, STEP_MS);
      const off = this.on((message) => {
        const value = pick(message);
        if (value === undefined) return;
        clearTimeout(timer);
        off();
        resolve(value);
      });
    });
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// The headless shell, started by this process and killed only by the pid it got.
class Chrome {
  constructor(binary, profile) {
    this.child = spawn(binary, [...CHROME_FLAGS, `--user-data-dir=${profile}`, "about:blank"], {
      stdio: ["ignore", "pipe", "pipe", "pipe", "pipe"],
    });
    this.stderr = "";
    this.child.stdout.resume();
    this.child.stderr.setEncoding("utf8");
    this.child.stderr.on("data", (s) => {
      this.stderr = (this.stderr + s).slice(-2000);
    });
    this.exited = new Promise((resolve) => this.child.once("exit", resolve));
    this.spawned = new Promise((resolve, reject) => {
      this.child.once("spawn", () => {
        process.stderr.write(`oracle_dom: chrome pid ${this.child.pid}\n`);
        resolve();
      });
      this.child.once("error", reject);
    });
    this.onExit = () => this.kill();
    process.on("exit", this.onExit);
    this.cdp = new Cdp(this.child.stdio[3], this.child.stdio[4]);
  }

  alive() {
    return this.child.exitCode === null && this.child.signalCode === null;
  }

  kill() {
    process.off("exit", this.onExit);
    if (this.alive()) this.child.kill("SIGKILL");
  }

  // Browser.close lets Chrome take its renderers down with it; SIGKILL if it hasn't in a second.
  async close() {
    if (this.alive() && this.child.pid !== undefined) {
      await Promise.race([this.cdp.send("Browser.close").catch(() => {}), sleep(1000)]);
      await Promise.race([this.exited, sleep(1000)]);
    }
    this.kill();
    if (this.child.pid !== undefined) await this.exited;
  }
}

// What the page script's selector helpers run: the element, or null when nothing matches.
// The page and the oracle's own endpoints, all answered from the Fetch domain: none resolves.
// practices-allow: SEC-13 Runtime.evaluate runs the oracle's own probes in its test page; arguments go in as JSON
const PAGE_ORIGIN = "http://oracle.page.invalid";
const ACTIONS_HOST = "oracle.actions.invalid";
const LOG_HOST = "oracle.log.invalid";
const ORACLE_HOSTS = new Set([new URL(PAGE_ORIGIN).hostname, ACTIONS_HOST, LOG_HOST]);
const CONTENT_TYPES = {
  ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".png": "image/png", ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp", ".avif": "image/avif", ".ico": "image/x-icon",
  ".svg": "image/svg+xml",
};
const CORS = [{ name: "Access-Control-Allow-Origin", value: "*" }, { name: "Access-Control-Allow-Headers", value: "*" },
  { name: "Access-Control-Allow-Methods", value: "*" }];
const PICK = "(sel) => document.querySelector(sel)";

function hostOf(url) {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

// Page data sent as page.js's plain(): arrays come as {"@array": length, 0: ...}.
function decode(value) {
  if (!value || typeof value !== "object") return value;
  if (Object.hasOwn(value, "@array")) return Array.from({ length: Math.min(Number(value["@array"]) || 0, 1000) }, (_, i) => decode(value[i]));
  return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, decode(v)]));
}

class DomSession {
  #requests = [];
  #byId = new Map();
  // what the oracle counted from the paused requests, where page code can't reach
  #log = { action: [], fetch: [], font: [], navigation: [], unresolved: [] };
  // requests to the oracle's endpoints that weren't page.js's: no token, another frame's, bad data
  #tamper = [];
  #reported = new Set();
  #pending = 0; // answers scheduled and not yet sent
  #lastAnswer = performance.now();
  #hung = new Set(); // network ids of requests "hang" never answers

  constructor(chrome, sessionId, { targetId, token, dir, opts, t, what }) {
    this.chrome = chrome;
    this.cdp = chrome.cdp;
    this.sessionId = sessionId;
    this.targetId = targetId;
    this.token = token;
    this.dir = dir;
    this.t = t;
    this.what = what;
    this.actionModes = { ...(opts.actionModes ?? {}) };
    this.actionResults = opts.actionResults ?? {};
    this.fetchRules = (opts.fetchModes ?? []).map(([match, spec]) => fetchRule(match, spec));
    this.delayMs = opts.delayMs ?? DELAY_MS;
    this.cdp.on(({ method, params, sessionId: from }) => {
      if (from !== sessionId) return;
      if (method === "Fetch.requestPaused") {
        this.#paused(params).catch((e) => this.#tamper.push({ why: `answering failed: ${e.message}`, url: params.request.url }));
      } else if (method === "Network.requestWillBeSent") {
        const redirected = params.redirectResponse && this.#byId.get(params.requestId);
        if (redirected) Object.assign(redirected, { status: params.redirectResponse.status, done: true });
        const entry = { id: params.requestId, url: params.request.url, method: params.request.method, type: params.type ?? null, status: null, failed: false, error: null, done: false };
        this.#requests.push(entry);
        this.#byId.set(params.requestId, entry);
      } else if (method === "Network.responseReceived") {
        const entry = this.#byId.get(params.requestId);
        if (entry) entry.status = params.response.status;
      } else if (method === "Network.loadingFinished") {
        const entry = this.#byId.get(params.requestId);
        if (entry) entry.done = true;
      } else if (method === "Network.loadingFailed") {
        const entry = this.#byId.get(params.requestId);
        if (entry) Object.assign(entry, { failed: true, error: params.errorText, done: true });
      }
    });
  }

  send(method, params = {}) {
    return this.cdp.send(method, params, this.sessionId);
  }

  #fulfill(requestId, status, body, headers = []) {
    return this.send("Fetch.fulfillRequest", {
      requestId, responseCode: status, responseHeaders: headers, body: Buffer.from(body).toString("base64"),
    });
  }

  // An answer after the stubbed round trip; settle() waits for it, and its quiet clock starts
  // again when the last one goes out.
  #later(answer) {
    this.#pending++;
    setTimeout(() => {
      answer().catch(() => {}).finally(() => {
        this.#pending--;
        this.#lastAnswer = performance.now();
      });
    }, this.delayMs);
  }

  // Every request the page makes, paused before it goes anywhere: the page's own files, served;
  // an action or a report to the oracle's endpoints, counted and answered; anything else, the
  // agent's, logged and answered by the fetch rules, or failed as offline.
  async #paused({ requestId, request, frameId, resourceType, networkId }) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return this.#fulfill(requestId, 204, "", CORS);
    if (url.origin === PAGE_ORIGIN) {
      const name = path.basename(decodeURIComponent(url.pathname));
      const file = name === "page.js" ? path.join(BROWSER, "page.js") : path.join(this.dir, name);
      if (!isFile(file)) return this.#fulfill(requestId, 404, "");
      const type = CONTENT_TYPES[path.extname(name).toLowerCase()] ?? "application/octet-stream";
      return this.#fulfill(requestId, 200, readFileSync(file), [{ name: "Content-Type", value: type }]);
    }
    if (url.hostname === ACTIONS_HOST || url.hostname === LOG_HOST) {
      const [token, kind, ...rest] = url.pathname.split("/").slice(1).map(decodeURIComponent);
      const tamper = (why) => {
        this.#tamper.push({ why, url: request.url.slice(0, 200) });
        return this.send("Fetch.failRequest", { requestId, errorReason: "NameNotResolved" });
      };
      if (token !== this.token || rest.length || !kind) return tamper("not page.js's request: no token");
      if (frameId !== this.targetId) return tamper(`a request from frame ${frameId}, not the page's`);
      let data;
      try {
        data = decode(JSON.parse(request.postData ?? "null"));
      } catch {
        return tamper("a body that isn't JSON");
      }
      if (url.hostname === LOG_HOST) {
        if (!Object.hasOwn(this.#log, kind) || kind === "action" || kind === "fetch") return tamper(`no such report: ${kind}`);
        this.#log[kind].push(data);
        return this.#fulfill(requestId, 204, "", CORS);
      }
      this.#log.action.push({ name: kind, args: data, t: performance.now() });
      const mode = this.actionModes[kind] ?? "ok";
      if (mode === "hang") return this.#hung.add(networkId);
      return this.#later(() => (mode === "fail"
        ? this.#fulfill(requestId, 500, "server error", CORS)
        : this.#fulfill(requestId, 200, JSON.stringify({ value: this.actionResults[kind] ?? null }), [...CORS, { name: "Content-Type", value: "application/json" }])));
    }
    const rule = this.fetchRules.find((r) => (r.regex ? new RegExp(r.regex, r.flags).test(request.url) : request.url.includes(r.match)));
    this.#log.fetch.push({ url: request.url, method: request.method, body: request.postData ?? null, stubbed: Boolean(rule), type: resourceType, t: performance.now() });
    if (!rule) return this.send("Fetch.failRequest", { requestId, errorReason: "NameNotResolved" });
    if (rule.spec === "hang") return this.#hung.add(networkId);
    return this.#later(() => (rule.spec === "fail"
      ? this.send("Fetch.failRequest", { requestId, errorReason: "Failed" })
      : this.#fulfill(requestId, rule.spec.status ?? 200, JSON.stringify(rule.spec.json === undefined ? null : rule.spec.json),
        [...CORS, { name: "Content-Type", value: "application/json" }])));
  }

  // Records, once each, what makes the run unresolved whatever the oracle checks: tampering with
  // the oracle's endpoints, and code next/dynamic couldn't load.
  #report() {
    if (this.#tamper.length && !this.#reported.has("tamper")) {
      this.#reported.add("tamper");
      this.t.unresolved("page tampered with the oracle's log", JSON.stringify(this.#tamper).slice(0, 600));
    }
    if (this.#log.unresolved.length && !this.#reported.has("unresolved")) {
      this.#reported.add("unresolved");
      this.t.unresolved(`${this.what} loads code the browser can't run`, this.#log.unresolved.map((u) => u?.detail).join("; "));
    }
  }

  // A log as the oracle has it, after a round trip to the page.
  async #read(kind) {
    await this.eval("0");
    this.#report();
    return structuredClone(this.#log[kind]);
  }

  // The page's one control, on the object the oracle took before any agent code loaded: start,
  // with the token, which loads the bundle and mounts the entry. Fixed arguments, no spread.
  async start() {
    const { result, exceptionDetails } = await this.send("Runtime.callFunctionOn", {
      objectId: this.controls,
      functionDeclaration: "function (token) { return this.start(token); }",
      arguments: [{ value: this.token }],
      returnByValue: true,
      awaitPromise: true,
    });
    if (exceptionDetails) throw new Error(`page start threw: ${exceptionDetails.exception?.description ?? exceptionDetails.text}`);
    return result.value;
  }

  // eval(expr) for an oracle's own probe: the value, awaited, as JSON carries it.
  async eval(expression) {
    const { result, exceptionDetails } = await this.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (exceptionDetails) throw new Error(`page threw: ${exceptionDetails.exception?.description ?? exceptionDetails.text}`);
    return result.value;
  }

  // fn (page-side source) called with JSON arguments.
  call(fn, ...args) {
    return this.eval(`(${fn})(...${JSON.stringify(args)})`);
  }

  #onElement(sel, body) {
    return this.call(`(sel) => { const el = (${PICK})(sel); return el ? (${body})(el) : null; }`, sel);
  }

  // Until no answer is due and no request in flight (a hanging one excluded, as it never ends),
  // and the DOM has been still, and no answer has gone out, for `quiet` ms; then one more frame
  // and the same test. Capped at `ms`. True when it settled.
  async settle({ ms = STEP_MS, quiet = 100 } = {}) {
    const deadline = performance.now() + Math.min(ms, STEP_MS);
    const still = async () => {
      const { quietMs } = await this.eval("window.__quiet()");
      const inFlight = this.#requests.some((r) => !r.done && /^https?:/.test(r.url) && !this.#hung.has(r.id));
      return !this.#pending && !inFlight && quietMs >= quiet && performance.now() - this.#lastAnswer >= quiet;
    };
    for (;;) {
      if (await still()) {
        await this.eval("new Promise((resolve) => requestAnimationFrame(() => resolve(true)))");
        if (await still()) return true;
      }
      if (performance.now() >= deadline) return false;
      await sleep(25);
    }
  }

  // Real mouse input at the element's center: count 2 is a double click, two presses and releases
  // in a row (clickCount 1, then 2), `interval` ms apart, as a fast hand does it.
  async click(sel, { count = 1, interval = 60 } = {}) {
    const point = await this.#onElement(sel, `(el) => {
      el.scrollIntoView({ block: "center", inline: "center" });
      const r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    }`);
    if (!point) throw new Missing(`nothing on the page matches ${sel}`);
    await this.send("Input.dispatchMouseEvent", { type: "mouseMoved", ...point });
    for (let clickCount = 1; clickCount <= count; clickCount++) {
      if (clickCount > 1) await sleep(interval);
      await this.send("Input.dispatchMouseEvent", { type: "mousePressed", ...point, button: "left", buttons: 1, clickCount });
      await this.send("Input.dispatchMouseEvent", { type: "mouseReleased", ...point, button: "left", buttons: 0, clickCount });
    }
  }

  async type(sel, text) {
    const found = await this.#onElement(sel, "(el) => { el.focus(); return document.activeElement === el; }");
    if (found === null) throw new Missing(`nothing on the page matches ${sel}`);
    await this.send("Input.insertText", { text });
  }

  async blur(sel) {
    const found = await this.#onElement(sel, "(el) => { el.blur(); return true; }");
    if (found === null) throw new Missing(`nothing on the page matches ${sel}`);
  }

  text(sel) {
    return this.#onElement(sel, "(el) => el.textContent");
  }

  attr(sel, name) {
    return this.call(`(sel, name) => { const el = (${PICK})(sel); return el ? el.getAttribute(name) : null; }`, sel, name);
  }

  async exists(sel) {
    return Boolean(await this.#onElement(sel, "() => true"));
  }

  value(sel) {
    return this.#onElement(sel, "(el) => (\"value\" in el ? el.value : null)");
  }

  rect(sel) {
    return this.#onElement(sel, "(el) => el.getBoundingClientRect().toJSON()");
  }

  style(sel, prop) {
    return this.call(`(sel, prop) => { const el = (${PICK})(sel); return el ? getComputedStyle(el).getPropertyValue(prop) : null; }`, sel, prop);
  }

  html() {
    return this.eval("document.documentElement.outerHTML");
  }

  // Every http(s) request the page made bar the oracle's own (its files, actions, reports),
  // failed ones included: {url, method, type, status, failed, error}.
  async requests() {
    await this.eval("0");
    return this.#requests.filter((r) => /^https?:/.test(r.url) && !ORACLE_HOSTS.has(hostOf(r.url)))
      .map(({ id, done, ...r }) => r);
  }

  // Every server action call, in the order its request arrived: {name, args, t}.
  actions() {
    return this.#read("action");
  }

  // The page's fetch() and XHR calls: {url, method, body, stubbed, type, t}.
  async fetches() {
    return (await this.#read("fetch")).filter((f) => f.type === "Fetch" || f.type === "XHR");
  }

  fonts() {
    return this.#read("font");
  }

  navigations() {
    return this.#read("navigation");
  }

  errors() {
    return this.eval("window.__errors");
  }

  // Server action `name` answers by `mode` from now on; the oracle holds it, not the page.
  async actionMode(name, mode) {
    if (!MODES.has(mode)) throw new Error(`actionMode: ${mode} is not one of ${[...MODES].join(", ")}`);
    this.actionModes[name] = mode;
  }

  // Requests whose URL contains `match` (a string) or matches it (a RegExp) answer by `spec`:
  // {status, json}, "fail" (a network error, as offline) or "hang". Rules apply in the order set.
  async fetchMode(match, spec) {
    this.fetchRules.push(fetchRule(match, spec));
  }

  close() {
    this.#report();
    return this.chrome.close();
  }
}

function fetchRule(match, spec) {
  if (spec !== "fail" && spec !== "hang" && (typeof spec !== "object" || spec === null)) {
    throw new Error(`fetchMode: ${JSON.stringify(spec)} is not {status, json}, "fail" or "hang"`);
  }
  return match instanceof RegExp ? { regex: match.source, flags: match.flags, spec } : { match: String(match), spec };
}

function bundleFor(entryFile, dir) {
  const bundle = new Bundle(dir);
  const ids = {
    entry: bundle.local(entryFile, false),
    react: bundle.package(PACKAGES.react),
    reactDom: bundle.package(PACKAGES["react-dom"]),
    reactDomClient: bundle.package(PACKAGES["react-dom/client"]),
  };
  return { ids, script: bundle.emit() };
}

const UNRESOLVED_WHY = {
  server: "is a server component the browser can't run",
  polyfill: "imports a Node builtin the oracle doesn't polyfill",
  css: "imports CSS the oracle can't build",
};

// The page for `opts.entry` (fixture-relative) rendered in headless Chrome, as a DomSession, or
// null when the verdict is already in (as openPg). An entry that won't compile, imports what
// doesn't exist or has no default export throws Missing (broken); one that throws on its first
// render scores broken; an async server component that reaches server-only code, or throws when
// awaited, scores unresolved. `oracleUrl` (the oracle's import.meta.url) names the scratch dir.
// Options: props, actionModes {name: mode}, actionResults {name: value}, fetchModes [[match, spec]],
// pathname, search and params for next/navigation and the page's props, delayMs for a stubbed
// round trip (default DELAY_MS). The caller closes the session; an exit without that still
// kills Chrome. ORACLE_CHROME names the headless shell.
export async function openDom(t, oracleUrl, opts) {
  const entryFile = findFile(path.join(FIXTURE, opts.entry));
  if (!entryFile) throw new Missing(`no ${opts.entry}`);
  const binary = process.env.ORACLE_CHROME;
  if (!binary) throw new Error("ORACLE_CHROME is not set: it names the headless Chrome the client-code oracles run");
  for (const mode of Object.values(opts.actionModes ?? {})) {
    if (!MODES.has(mode)) throw new Error(`actionModes: ${mode} is not one of ${[...MODES].join(", ")}`);
  }

  const caseName = path.basename(path.dirname(fileURLToPath(oracleUrl)));
  const dir = mkdtempSync(path.join(process.env.TMPDIR ?? FIXTURE, `oracle-dom-${caseName}-`));
  const { ids, script } = bundleFor(entryFile, dir);
  const what = rel(entryFile);
  const config = {
    bundle: "bundle.js",
    ...ids,
    props: opts.props ?? {},
    pathname: opts.pathname ?? "/",
    search: opts.search ?? "",
    params: opts.params ?? {},
  };
  writeFileSync(path.join(dir, "config.js"), `window.__config = ${JSON.stringify(config)};\n`);
  writeFileSync(path.join(dir, "bundle.js"), script);
  writeFileSync(path.join(dir, "index.html"),
    `<!doctype html>\n<html><head><meta charset="utf-8"><title>oracle</title></head><body><div id="root"></div>\n` +
    `<script src="config.js"></script>\n<script src="page.js"></script>\n</body></html>\n`);

  mkdirSync(path.join(dir, "chrome-profile"));
  const chrome = new Chrome(binary, path.join(dir, "chrome-profile"));
  try {
    await chrome.spawned;
    const { cdp } = chrome;
    const created = cdp.waitFor("page target", ({ method, params }) =>
      method === "Target.targetCreated" && params.targetInfo.type === "page" ? params.targetInfo.targetId : undefined);
    await cdp.send("Target.setDiscoverTargets", { discover: true });
    const targetId = await created;
    const { sessionId } = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
    // the run's capability: page.js gets it through start(), never from anything the page can read
    const token = randomBytes(32).toString("base64url");
    const session = new DomSession(chrome, sessionId, { targetId, token, dir, opts, t, what });
    await Promise.all([session.send("Page.enable"), session.send("Runtime.enable"), session.send("Network.enable")]);
    await session.send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] });
    const loaded = cdp.waitFor("load event", ({ method, sessionId: from }) => (method === "Page.loadEventFired" && from === sessionId ? true : undefined));
    await session.send("Page.navigate", { url: `${PAGE_ORIGIN}/index.html` });
    await loaded;
    // The control, taken while only config.js and page.js have run; start loads the bundle.
    const { result } = await session.send("Runtime.evaluate", { expression: "window.__takeControls()" });
    session.controls = result.objectId;
    const mounted = await session.start();
    if (mounted.status === "ok") {
      t.functional(`${what} renders`, true);
      return session;
    }
    if (mounted.status === "no-default") throw new Missing(`${what} has no default export to render (${mounted.detail})`);
    if (mounted.status === "unresolved") {
      t.functional(`${what} bundles`, true);
      t.unresolved(`${what} ${UNRESOLVED_WHY[mounted.kind] ?? UNRESOLVED_WHY.server}`, mounted.detail);
    } else t.functional(`${what} renders`, false, mounted.detail.slice(0, 1500));
    await chrome.close();
    return null;
  } catch (e) {
    await chrome.close();
    if (e instanceof Missing) throw e;
    throw new Error(`${e.message}${chrome.stderr ? `\nchrome stderr: ${chrome.stderr.slice(-600)}` : ""}`);
  }
}
