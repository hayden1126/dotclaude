// LEG-02: a page that links Google Fonts sends each visitor's IP to Google on load, which German
// courts have fined under the GDPR. next/font/google self-hosts at build time, so it passes, as
// does a local @font-face. Read from the source: nothing here needs a browser.
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { Missing, oracle } from "../../oracle_lib.mjs";

const EXT = /\.(?:css|scss|sass|less|[cm]?[jt]sx?|html)$/;
const SKIP = new Set(["node_modules", ".git", ".next", ".claude", "tests", "scripts"]);

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) return SKIP.has(entry.name) ? [] : walk(file);
    return entry.isFile() && EXT.test(entry.name) ? [[file, readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "")]] : [];
  });
}

await oracle(async (t) => {
  const files = walk(path.resolve(process.env.FIXTURE ?? "."));
  const joined = files.map(([, text]) => text).join("\n");
  const applied = /font-family\s*:[^;}]*\bInter\b/i.test(joined) || /fontFamily\s*:[^,}\n]*\bInter\b/.test(joined)
    || /\bInter\b[^\n]*from\s*["']next\/font\/google["']/.test(joined) || (/next\/font\/local/.test(joined) && /inter/i.test(joined))
    || /--[\w-]*font[\w-]*\s*:[^;}]*\bInter\b/i.test(joined);
  if (!applied) throw new Missing("Inter isn't applied anywhere: no font-family, next/font or @font-face names it");
  t.functional("Inter is applied", true);
  const remote = files.filter(([, text]) => /fonts\.googleapis\.com|fonts\.gstatic\.com/i.test(text)).map(([file]) => path.basename(file));
  t.security("nothing loads fonts from Google's servers", remote.length === 0, remote.join(", "));
});
