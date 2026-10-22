// Playwright for the skill's browser scripts (verify_page.mjs, print_sheet.mjs): where it comes
// from, and a Chromium launch that goes through the sandbox's proxy (L21).
//
// An ES module ignores NODE_PATH (L22), so Playwright is imported from an absolute path: the
// package directory in $EXAM_PREP_PLAYWRIGHT, else the first install found in node_modules/ beside
// the page, in the working directory's _build/node_modules/ or node_modules/, then in npm's global
// root (`npm root -g`). With none, it says how to install one and exits 2.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

function findPlaywright(name, pagePath, usage) {
  const env = process.env.EXAM_PREP_PLAYWRIGHT;
  if (env) {
    if (!fs.existsSync(path.join(env, 'index.mjs'))) usage(`EXAM_PREP_PLAYWRIGHT=${env} has no index.mjs`);
    return env;
  }
  const tried = [
    path.join(path.dirname(path.resolve(pagePath)), 'node_modules', 'playwright'),
    path.resolve('_build', 'node_modules', 'playwright'),
    path.resolve('node_modules', 'playwright'),
  ];
  try {
    const root = execFileSync('npm', ['root', '-g'], { encoding: 'utf8', timeout: 20000, stdio: ['ignore', 'pipe', 'ignore'] }).trim();
    if (root) tried.push(path.join(root, 'playwright'));
  } catch { /* no npm: the local candidates only */ }
  const unique = [...new Set(tried)];
  const found = unique.find((d) => fs.existsSync(path.join(d, 'index.mjs')));
  if (found) return found;
  console.error(`${name}: no Playwright found. Looked in:`);
  for (const d of unique) console.error(`  ${d}`);
  console.error('Install it once in the hub\'s _build/ (its node_modules/ is gitignored):');
  console.error('  cd _build && npm install playwright && npx playwright install chromium');
  console.error('or set EXAM_PREP_PLAYWRIGHT to an existing node_modules/playwright directory.');
  process.exit(2);
}

// The chromium object of the Playwright found for pagePath; `name` prefixes messages and `usage`
// reports a bad EXAM_PREP_PLAYWRIGHT (it exits 2).
export async function loadChromium(name, pagePath, usage) {
  const dir = findPlaywright(name, pagePath, usage);
  console.log(`playwright: ${dir}`);
  return (await import(pathToFileURL(path.join(dir, 'index.mjs')).href)).chromium;
}

export function launch(chromium) {
  const raw = process.env.HTTPS_PROXY || process.env.https_proxy;
  if (!raw) return chromium.launch();
  const u = new URL(raw);
  return chromium.launch({
    proxy: {
      server: `${u.protocol}//${u.host}`,
      username: decodeURIComponent(u.username),
      password: decodeURIComponent(u.password),
      bypass: 'localhost,127.0.0.1',
    },
  });
}
