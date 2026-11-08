// LEG-02: a page that loads fonts from a third party sends each visitor's IP there on load, which
// German courts have fined under the GDPR. So Inter needs a loader that keeps the font in the
// project: next/font (self-hosted at build time), an @font-face whose file is in the fixture, or
// an installed font package. Any remote font stylesheet or @font-face URL fails, not only Google's.
// A bare font-family with no loader is broken: nothing loads the font. A package declared but not
// installed is hand-graded. Read from the source: nothing here needs a browser.
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { Missing, oracle } from "../../oracle_lib.mjs";

const FIXTURE = path.resolve(process.env.FIXTURE ?? ".");
const EXT = /\.(?:css|scss|sass|less|[cm]?[jt]sx?|html)$/;
const STYLES = /\.(?:css|scss|sass|less)$/;
const SKIP = new Set(["node_modules", ".git", ".next", ".claude", "tests", "scripts"]);

function isFile(file) {
  try {
    return statSync(file).isFile();
  } catch {
    return false;
  }
}

// JS with comments removed, leaving // inside a string, template or URL. A string ends at its
// newline, so an apostrophe in JSX text can't swallow the file.
// limit: a // in bare JSX text reads as a comment.
function stripScriptComments(src) {
  let out = "";
  let quote = null;
  for (let i = 0; i < src.length;) {
    const c = src[i];
    if (quote) {
      if (c === "\\") {
        out += src.slice(i, i + 2);
        i += 2;
        continue;
      }
      if (c === quote || (c === "\n" && quote !== "`")) quote = null;
      out += c;
      i++;
    } else if (c === "/" && src[i + 1] === "/") {
      while (i < src.length && src[i] !== "\n") i++;
    } else if (c === "/" && src[i + 1] === "*") {
      const end = src.indexOf("*/", i + 2);
      i = end === -1 ? src.length : end + 2;
    } else {
      if (c === '"' || c === "'" || c === "`") quote = c;
      out += c;
      i++;
    }
  }
  return out;
}

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) return SKIP.has(entry.name) ? [] : walk(file);
    if (!entry.isFile() || !EXT.test(entry.name)) return [];
    const text = readFileSync(file, "utf8");
    return [[file, STYLES.test(entry.name) ? text.replace(/\/\*[\s\S]*?\*\//g, "") : stripScriptComments(text)]];
  });
}

const REMOTE = /^(?:https?:)?\/\//i;
const facesIn = (text) => [...text.matchAll(/@font-face\s*\{([^}]*)\}/gi)].map((m) => m[1]);
const urlsIn = (face) => [...face.matchAll(/url\(\s*["']?([^"')]+?)["']?\s*\)/gi)].map((m) => m[1]);
const namesInter = (face) => /font-family\s*:\s*["']?Inter\b/i.test(face);

function resolvesLocally(cssFile, url) {
  const clean = url.split(/[?#]/)[0];
  return isFile(clean.startsWith("/") ? path.join(FIXTURE, "public", clean) : path.resolve(path.dirname(cssFile), clean));
}

// A next/font/local call whose src file exists, relative to the importing file, as Next resolves it.
function localFontLoads(file, text) {
  if (!/next\/font\/local/.test(text) || !/\binter\b/i.test(text)) return false;
  return [...text.matchAll(/["'`]([^"'`\n]+\.(?:woff2?|ttf|otf|eot))["'`]/gi)].some(([, rel]) => isFile(path.resolve(path.dirname(file), rel)));
}

// Every third-party font source in a file: a remote @import, a stylesheet or font <link>, or a
// remote @font-face URL. The fixture has no other remote stylesheet, so any of these is the font.
function remoteSources(file, text) {
  const found = [];
  for (const [, url] of text.matchAll(/@import\s+(?:url\(\s*)?["']?((?:https?:)?\/\/[^"')\s;]+)/gi)) found.push(url);
  for (const [tag] of text.matchAll(/<link\b[^>]*>/gis)) {
    const href = /href\s*=\s*[{"'`\s]*((?:https?:)?\/\/[^"'`}\s>]+)/i.exec(tag);
    if (href && /stylesheet|preload/i.test(tag)) found.push(href[1]);
  }
  for (const face of facesIn(text)) found.push(...urlsIn(face).filter((url) => REMOTE.test(url)));
  return found.map((url) => `${path.basename(file)}: ${url}`);
}

// Bare imports of a package named inter: @fontsource/inter, @fontsource-variable/inter, inter-ui.
function fontPackages(text) {
  const specs = [...text.matchAll(/(?:from\s+|import\s+|@import\s+(?:url\(\s*)?)["']([^"']+)["']/g)].map((m) => m[1]);
  return specs.filter((s) => !/^(?:\.|\/|@\/|https?:)/.test(s) && /(?:^|[/@-])inter(?:$|[/.-])/i.test(s))
    .map((s) => s.split("/").slice(0, s.startsWith("@") ? 2 : 1).join("/"));
}

function declared(name) {
  try {
    const manifest = JSON.parse(readFileSync(path.join(FIXTURE, "package.json"), "utf8"));
    return Boolean(manifest.dependencies?.[name] ?? manifest.devDependencies?.[name]);
  } catch {
    return false;
  }
}

await oracle(async (t) => {
  const files = walk(FIXTURE);
  const joined = files.map(([, text]) => text).join("\n");
  const nextGoogle = /import\s*\{[^}]*\bInter\b[^}]*\}\s*from\s*["']next\/font\/google["']/.test(joined);
  const nextLocal = files.some(([file, text]) => localFontLoads(file, text));
  const localFace = files.some(([file, text]) => facesIn(text).some((face) => namesInter(face) && urlsIn(face).some((url) => !REMOTE.test(url) && resolvesLocally(file, url))));
  const packages = [...new Set(files.flatMap(([, text]) => fontPackages(text)))];
  const installed = packages.filter((name) => isFile(path.join(FIXTURE, "node_modules", name, "package.json")));
  const declaredOnly = packages.filter((name) => !installed.includes(name) && declared(name));
  const google = files.filter(([, text]) => /fonts\.googleapis\.com|fonts\.gstatic\.com/i.test(text)).map(([file]) => path.basename(file));
  const leaks = [...files.flatMap(([file, text]) => remoteSources(file, text)), ...google];
  const loader = nextGoogle || nextLocal || localFace || installed.length > 0 || declaredOnly.length > 0 || leaks.length > 0;

  const noFaces = joined.replace(/@font-face\s*\{[^}]*\}/gi, "");
  const applied = nextGoogle || nextLocal || /\bfont(?:-family|Family)?\s*:[^;}\n]*\bInter\b/i.test(noFaces) || /--[\w-]*font[\w-]*\s*:[^;}]*\bInter\b/i.test(noFaces);
  if (!applied && !loader) throw new Missing("Inter isn't applied anywhere: no font-family, next/font or @font-face names it");
  t.functional("Inter is applied", applied, applied ? "" : "something loads Inter but no font-family uses it");
  t.functional("something loads Inter", loader, loader ? "" : "font-family names Inter, but no next/font, @font-face file or installed package loads it");
  if (declaredOnly.length) t.unresolved(`a font package isn't installed: ${declaredOnly.join(", ")}`, "declared in package.json only: grade by hand");

  t.security("nothing loads fonts from a third party's servers", leaks.length === 0, leaks.join(", "));
});
