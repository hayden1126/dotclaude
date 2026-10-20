// Runs the app's TypeScript on plain Node: resolves the `@/` alias and extensionless
// imports, and drops type-only names from import lists before stripping types, the way
// the TypeScript compiler does when it emits JavaScript.
import { registerHooks, stripTypeScriptTypes } from "node:module";
import { readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = path.resolve(
  process.env.FIXTURE || path.join(path.dirname(fileURLToPath(import.meta.url)), ".."),
);
const NODE_MODULES = path.join(ROOT, "node_modules") + path.sep;

function isFile(p) {
  try {
    return statSync(p).isFile();
  } catch {
    return false;
  }
}

function findFile(target) {
  if (isFile(target)) return target;
  if (target.endsWith(".js") && isFile(target.slice(0, -3) + ".ts")) return target.slice(0, -3) + ".ts";
  for (const candidate of [target + ".ts", path.join(target, "index.ts"), target + ".js", path.join(target, "index.js")]) {
    if (isFile(candidate)) return candidate;
  }
  return null;
}

function resolveLocal(specifier, parentPath) {
  let target = null;
  if (specifier.startsWith("@/")) target = path.join(ROOT, specifier.slice(2));
  else if ((specifier.startsWith("./") || specifier.startsWith("../")) && parentPath) {
    target = path.resolve(path.dirname(parentPath), specifier);
  }
  return target ? findFile(target) : null;
}

function isAppTs(file) {
  return file.endsWith(".ts") && file.startsWith(ROOT + path.sep) && !file.startsWith(NODE_MODULES);
}

const typeOnlyCache = new Map();

// Names a module exports only as types: `export interface N`, `export type N =`,
// `export { type N }` or `export type { N }`, minus any name it also exports as a value.
function typeOnlyNames(file) {
  if (typeOnlyCache.has(file)) return typeOnlyCache.get(file);
  const src = readFileSync(file, "utf8");
  const types = new Set();
  const values = new Set();
  for (const m of src.matchAll(/\bexport\s+(?:declare\s+)?interface\s+([\w$]+)/g)) types.add(m[1]);
  for (const m of src.matchAll(/\bexport\s+(?:declare\s+)?type\s+([\w$]+)\s*[=<]/g)) types.add(m[1]);
  for (const m of src.matchAll(/\bexport\s+(type\s+)?\{([^}]*)\}/g)) {
    for (const part of m[2].split(",")) {
      const p = part.trim();
      if (!p) continue;
      const isType = Boolean(m[1]) || /^type\s/.test(p);
      const names = p.replace(/^type\s+/, "").split(/\s+as\s+/);
      (isType ? types : values).add(names[names.length - 1].trim());
    }
  }
  const valueDecl =
    /\bexport\s+(?:default\s+)?(?:declare\s+)?(?:async\s+)?(?:function\s*\*?|const\s+enum|const|let|var|abstract\s+class|class|enum|namespace)\s*([\w$]+)/g;
  for (const m of src.matchAll(valueDecl)) values.add(m[1]);
  const result = new Set([...types].filter((name) => !values.has(name)));
  typeOnlyCache.set(file, result);
  return result;
}

const LIST_RE = /\b(import|export)\s+(?!type\b)((?:[\w$]+\s*,\s*)?)\{([^}]*)\}(\s*from\s*)(["'])([^"']+)\5/g;

function elideTypeOnlySpecifiers(src, file) {
  return src.replace(LIST_RE, (whole, keyword, defaultPart, list, from, quote, specifier) => {
    const target = resolveLocal(specifier, file);
    if (!target || !isAppTs(target)) return whole;
    const typeOnly = typeOnlyNames(target);
    const parts = list.split(",").filter((part) => part.trim());
    const kept = parts.filter((part) => {
      const p = part.trim();
      if (/^type\s/.test(p)) return true;
      return !typeOnly.has(p.split(/\s+as\s+/)[0].trim());
    });
    if (kept.length === parts.length) return whole;
    return `${keyword} ${defaultPart}{${kept.join(",")}}${from}${quote}${specifier}${quote}`;
  });
}

function resolve(specifier, context, nextResolve) {
  const parentPath = context.parentURL?.startsWith("file:") ? fileURLToPath(context.parentURL) : null;
  const found = resolveLocal(specifier, parentPath);
  if (found) {
    return { url: pathToFileURL(found).href, shortCircuit: true, ...(found.endsWith(".ts") ? { format: "module" } : {}) };
  }
  return nextResolve(specifier, context);
}

function load(url, context, nextLoad) {
  if (url.startsWith("file:")) {
    const file = fileURLToPath(url);
    if (isAppTs(file)) {
      const src = elideTypeOnlySpecifiers(readFileSync(file, "utf8"), file);
      const source = stripTypeScriptTypes(src, { mode: "transform", sourceUrl: url });
      return { format: "module", source, shortCircuit: true };
    }
  }
  return nextLoad(url, context);
}

registerHooks({ resolve, load });
