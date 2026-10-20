// Browser checks for an assembled page (the notes page, the mock page), headless Chromium.
//
//   node verify_page.mjs <page.html> <outdir> [--spy id,id,...] [--steps <steps.json>]
//
// Playwright is imported from an absolute path, since an ES module ignores NODE_PATH (L22): the
// package directory in $EXAM_PREP_PLAYWRIGHT, else the first install found in node_modules/
// beside the page, in the working directory's _build/node_modules/ or node_modules/, then in npm's
// global root (`npm root -g`). With none, it says how to install one and exits 2. Run
// it with `allowed_domains` cdnjs.cloudflare.com, fonts.googleapis.com and fonts.gstatic.com: the
// page loads MathJax and its fonts from them, and Chromium gets the sandbox's proxy passed in (L21).
// A page without a doctype is wrapped in a standards-mode document first, as the artifact host
// does (L19). Then, at 390 and 1280 px wide, light and dark:
//   - MathJax loaded and finished; no math left as raw \( \) or \[ \]; no TeX error and no
//     undefined macro (MathJax draws both, in red, inside its output); no zero-size math;
//   - no horizontal overflow (wide figures, tables, math and pre scroll in their own boxes), and
//     none of either inside the worked examples and the exam-day map once they are opened;
//   - every href="#id" resolves, and no id repeats;
//   - the fonts the chassis declares (--f-display, --f-body, --f-mono) loaded (L24);
//   - every worked example is closed by default (FB-116);
//   - each step-through (a figure with .fig-controls) has its window.NotesFig handler and a status
//     line ([aria-live]), and every run --steps lists for it (06-site, step 2:
//     {"<fig-id>": [{"act"?, "frames", "final"}]}) starts without `final` in its status line,
//     reaches its last frame in exactly `frames` presses of Next, shows `final` there, comes back
//     to its first frame in as many presses of Prev, and throws nothing; a step-through --steps
//     doesn't list, and a mode button no run presses, fail (FB-117);
//   - no page errors;
//   - scroll-spy marks each --spy target when it is scrolled to (default: the first section, a
//     middle subsection and the last subsection the page can scroll to the spy line), after the
//     scroll settles (L18). A target too near the page's end to reach that line is skipped, with
//     a note.
// Screenshots of the viewport (never full page, L23) go to <outdir>: <width>-<scheme>-top.png, one
// per spy target, one per step-through at its last frame, the first worked example opened (-wex)
// and the exam-day map opened (-map). Exit 0 when every check passes, 1 on any failure, 2 on bad
// usage.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

function usage(msg) {
  console.error(`verify_page: ${msg}`);
  console.error('usage: node verify_page.mjs <page.html> <outdir> [--spy id,id] [--steps <steps.json>]');
  process.exit(2);
}

const args = process.argv.slice(2);
let spyArg = null;
let stepsArg = null;
const pos = [];
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--spy') spyArg = args[++i];
  else if (args[i] === '--steps') stepsArg = args[++i];
  else pos.push(args[i]);
}
if (pos.length !== 2) usage('need <page.html> and <outdir>');
const [pagePath, outDir] = pos;
if (!fs.existsSync(pagePath)) usage(`no page at ${pagePath}`);
const norm = (t) => String(t).replace(/\s+/g, ' ').trim();
let steps = {};
if (stepsArg) {
  try {
    steps = JSON.parse(fs.readFileSync(stepsArg, 'utf8'));
  } catch (e) {
    usage(`--steps ${stepsArg}: ${e.message}`);
  }
  const runOk = (r) => r && typeof r === 'object' && Number.isInteger(r.frames) && r.frames >= 1 &&
    typeof r.final === 'string' && norm(r.final) && (r.act === undefined || typeof r.act === 'string');
  if (!steps || typeof steps !== 'object' || Array.isArray(steps) ||
      !Object.values(steps).every((runs) => Array.isArray(runs) && runs.length && runs.every(runOk))) {
    usage(`--steps ${stepsArg}: want {"<fig-id>": [{"act"?: string, "frames": int >= 1, "final": string}]}`);
  }
}

function findPlaywright() {
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
  console.error('verify_page: no Playwright found. Looked in:');
  for (const d of unique) console.error(`  ${d}`);
  console.error('Install it once in the hub\'s _build/ (its node_modules/ is gitignored):');
  console.error('  cd _build && npm install playwright && npx playwright install chromium');
  console.error('or set EXAM_PREP_PLAYWRIGHT to an existing node_modules/playwright directory.');
  process.exit(2);
}

const pwDir = findPlaywright();
console.log(`playwright: ${pwDir}`);
const { chromium } = await import(pathToFileURL(path.join(pwDir, 'index.mjs')).href);

function launch() {
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

fs.mkdirSync(outDir, { recursive: true });
const src = fs.readFileSync(pagePath, 'utf8');
const doc = /^\s*<!doctype/i.test(src) ? src
  : '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width, initial-scale=1">' + src + '</html>';
const wrapped = path.resolve(outDir, 'wrapped.html');
fs.writeFileSync(wrapped, doc);

const browser = await launch();
let failures = 0;
const fail = (m) => { failures++; console.log('  FAIL ' + m); };

for (const width of [390, 1280]) {
  for (const scheme of ['light', 'dark']) {
    const tag = `${width}-${scheme}`;
    console.log(`[${tag}]`);
    const ctx = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: scheme, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.goto(pathToFileURL(wrapped).href, { waitUntil: 'networkidle' });
    try {
      await page.waitForFunction(() => window.MathJax && MathJax.startup && MathJax.startup.promise, null, { timeout: 30000 });
      await page.evaluate(() => MathJax.startup.promise);
    } catch (e) {
      fail('MathJax never loaded: run with allowed_domains for cdnjs.cloudflare.com (L21)');
      await ctx.close();
      continue;
    }
    await page.evaluate(() => document.fonts.ready);
    const r = await page.evaluate(() => {
      const main = document.getElementById('main') || document.body;
      const mj = [...document.querySelectorAll('mjx-container')];
      const zero = mj.filter((m) => m.offsetParent !== null)
        .filter((m) => { const b = m.getBoundingClientRect(); return b.width === 0 || b.height === 0; });
      const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
      const raw = [];
      while (walker.nextNode()) {
        const t = walker.currentNode.nodeValue;
        const p = walker.currentNode.parentElement;
        if (p && p.closest('script,code,pre,svg')) continue;
        if (/\\\(|\\\)|\\\[|\\\]/.test(t)) raw.push(t.trim().slice(0, 80));
      }
      const all = [...document.querySelectorAll('[id]')].map((e) => e.id);
      const ids = new Set(all);
      const dup = [...new Set(all.filter((id, i) => all.indexOf(id) !== i))];
      const hrefs = [...document.querySelectorAll('a[href^="#"]')].map((a) => decodeURIComponent(a.getAttribute('href').slice(1)));
      const broken = [...new Set(hrefs.filter((h) => h && !ids.has(h)))];
      const cw = document.documentElement.clientWidth;
      const sw = document.documentElement.scrollWidth;
      const wide = [...main.querySelectorAll('*')].filter((e) => {
        const b = e.getBoundingClientRect();
        return b.right > cw + 1 && !e.closest('.figbox,.tbl-wrap,mjx-container,pre,.rail');
      }).slice(0, 5).map((e) => e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className : ''));
      const style = getComputedStyle(document.documentElement);
      const fonts = ['--f-display', '--f-body', '--f-mono'].map((v) => {
        const fam = style.getPropertyValue(v).split(',')[0].trim().replace(/^["']|["']$/g, '');
        const loaded = [...document.fonts].some((f) => f.family.replace(/^["']|["']$/g, '') === fam && f.status === 'loaded');
        return { v, fam, loaded };
      }).filter((f) => f.fam);
      const openWex = document.querySelectorAll('details.wex[open]').length;
      // MathJax typesets a TeX error as an merror node and an undefined macro as red text that
      // starts with a backslash; both sit inside its output, where the raw-TeX walk can't see them.
      const texErr = [];
      for (const item of MathJax.startup.document.math) {
        item.root.walkTree((n) => {
          if (n.isKind('merror')) texErr.push(n.attributes.get('data-mjx-error') || 'error');
          else if (n.isKind('mtext') && n.attributes.getExplicit('mathcolor') === 'red') {
            const t = n.childNodes.map((c) => (c.getText ? c.getText() : '')).join('');
            if (t.startsWith('\\')) texErr.push('undefined ' + t);
          }
        });
      }
      return { mj: mj.length, zero: zero.length, raw, links: hrefs.length, broken, dup, sw, cw, wide, fonts, openWex,
        texErr, bg: getComputedStyle(document.body).backgroundColor };
    });
    console.log(`  mjx=${r.mj} zero=${r.zero} raw=${r.raw.length} links=${r.links} broken=${r.broken.length} dup=${r.dup.length} scrollW=${r.sw}/${r.cw} bg=${r.bg}`);
    if (r.zero) fail(`${r.zero} zero-size math`);
    if (r.raw.length) fail(`math left as raw TeX: ${JSON.stringify(r.raw.slice(0, 3))}`);
    if (r.texErr.length) fail(`TeX errors: ${JSON.stringify(r.texErr.slice(0, 3))}`);
    if (r.broken.length) fail('broken links: ' + r.broken.join(', '));
    if (r.dup.length) fail('duplicate ids: ' + r.dup.join(', '));
    if (r.sw > r.cw + 1) fail(`horizontal overflow ${r.sw} > ${r.cw}: ${r.wide.join(' ')}`);
    for (const f of r.fonts) if (!f.loaded) fail(`font ${f.fam} (${f.v}) never loaded: the Google Fonts link, or allowed_domains (L24)`);
    if (r.openWex) fail(`${r.openWex} worked examples open by default`);
    if (errors.length) fail('page errors: ' + errors.join(' | '));

    await page.screenshot({ path: path.join(outDir, `${tag}-top.png`) });
    // The chassis's scroll-spy marks the last heading above a line 130 px from the top, so a
    // heading in the page's final screen can never reach it.
    await page.evaluate(() => {
      window.__spyReachable = (el) => el.getBoundingClientRect().top + window.scrollY
        <= document.documentElement.scrollHeight - window.innerHeight + 120;
    });
    const spy = spyArg ? spyArg.split(',').filter(Boolean) : await page.evaluate(() => {
      const secs = [...document.querySelectorAll('section.note[id]')];
      const subs = [...document.querySelectorAll('section.note h3[id]')].filter(window.__spyReachable);
      return [secs[0] && secs[0].id, subs[Math.floor(subs.length / 2)] && subs[Math.floor(subs.length / 2)].id,
        subs[subs.length - 1] && subs[subs.length - 1].id].filter((v, i, a) => v && a.indexOf(v) === i);
    });
    for (const id of spy) {
      const where = await page.evaluate((i) => {
        const el = document.getElementById(i);
        if (!el) return 'missing';
        if (!window.__spyReachable(el)) return 'end';
        el.scrollIntoView({ block: 'start' });
        return 'ok';
      }, id);
      if (where === 'missing') { fail(`scroll-spy target #${id} not on the page`); continue; }
      if (where === 'end') { console.log(`  spy skip #${id}: too near the page's end to reach the spy line`); continue; }
      await page.waitForTimeout(400);
      await page.evaluate(() => window.dispatchEvent(new Event('scroll')));
      await page.waitForTimeout(200);
      const active = await page.evaluate(() => { const a = document.querySelector('.toc a.active'); return a ? a.dataset.target : null; });
      if (active !== id) fail(`scroll-spy at #${id} marks ${active}`);
      else console.log(`  spy ok #${id}`);
      await page.screenshot({ path: path.join(outDir, `${tag}-${id}.png`) });
    }

    const figs = await page.evaluate(() => [...document.querySelectorAll('figure')]
      .filter((f) => f.querySelector('.fig-controls'))
      .map((f) => ({ id: f.id, handler: typeof (window.NotesFig || {})[f.id] === 'function' })));
    for (const id of Object.keys(steps)) {
      if (!figs.some((f) => f.id === id)) fail(`--steps lists #${id}, which is no step-through on the page`);
    }
    for (const f of figs) {
      if (!f.handler) { fail(`step-through #${f.id}: no window.NotesFig['${f.id}'] handler`); continue; }
      if (!steps[f.id]) { fail(`step-through #${f.id}: no expected run in --steps (06-site, step 2)`); continue; }
      const modes = await page.evaluate((id) => [...document.getElementById(id)
        .querySelectorAll('.fig-controls button[data-act]')].map((b) => b.dataset.act)
        .filter((a) => a !== 'prev' && a !== 'next'), f.id);
      for (const m of modes) {
        if (!steps[f.id].some((run) => run.act === m)) fail(`step-through #${f.id}: no run in --steps presses mode "${m}"`);
      }
      for (const run of steps[f.id]) {
        const before = errors.length;
        const out = await page.evaluate(({ id, act, cap }) => {
          const fig = document.getElementById(id);
          const status = fig.querySelector('[aria-live]');
          if (!status) return { missing: 'status' };
          const btn = (a) => [...fig.querySelectorAll('.fig-controls button[data-act]')].find((b) => b.dataset.act === a);
          if (act) { if (!btn(act)) return { missing: act }; btn(act).click(); }
          const next = btn('next');
          const prev = btn('prev');
          if (!next || !prev) return { missing: next ? 'prev' : 'next' };
          const start = status.textContent;
          let n = 0;
          while (!next.disabled && n < cap) { next.click(); n++; }
          const ended = next.disabled;
          const end = status.textContent;
          let back = 0;
          while (!prev.disabled && back < cap) { prev.click(); back++; }
          return { n, ended, start, end, back, again: status.textContent };
        }, { id: f.id, act: run.act || null, cap: run.frames + 20 });
        const label = `step-through #${f.id}${run.act ? ` (${run.act})` : ''}`;
        if (out.missing === 'status') { fail(`${label}: no status line ([aria-live])`); continue; }
        if (out.missing) { fail(`${label}: no button data-act="${out.missing}"`); continue; }
        const final = norm(run.final);
        let ok = true;
        const bad = (m) => { ok = false; fail(`${label}: ${m}`); };
        if (norm(out.start).includes(final)) bad(`its status line shows ${JSON.stringify(run.final)} before any press`);
        if (!out.ended) bad(`Next never disabled after ${out.n} presses`);
        else if (out.n !== run.frames) bad(`${out.n} frames, --steps says ${run.frames}`);
        if (!norm(out.end).includes(final)) bad(`last frame doesn't show ${JSON.stringify(run.final)}`);
        if (out.back !== out.n) bad(`Prev took ${out.back} presses back, Next took ${out.n}`);
        else if (norm(out.again) !== norm(out.start)) bad('Prev doesn\'t return to the first frame');
        if (errors.length > before) bad(`errors while stepping: ${errors.slice(before).join(' | ')}`);
        if (ok) console.log(`  ${label} ok: ${out.n} frames, forward and back`);
      }
      await page.evaluate((id) => {
        const next = document.getElementById(id).querySelector('.fig-controls button[data-act="next"]');
        for (let n = 0; next && !next.disabled && n < 500; n++) next.click();
      }, f.id);
      await page.evaluate((i) => document.getElementById(i).scrollIntoView({ block: 'center' }), f.id);
      await page.waitForTimeout(200);
      await page.screenshot({ path: path.join(outDir, `${tag}-${f.id}.png`) });
    }

    // A closed worked example or exam-day map has no layout, so its math and width are measured
    // again with each opened.
    const opened = await page.evaluate(() => {
      const ds = [...document.querySelectorAll('details.wex, details.examnav')];
      ds.forEach((d) => { d.open = true; });
      return ds.length;
    });
    if (opened) {
      await page.waitForTimeout(300);
      const o = await page.evaluate(() => {
        const cw = document.documentElement.clientWidth;
        const inside = [...document.querySelectorAll('details.wex *, details.examnav *')];
        const zero = inside.filter((m) => m.tagName === 'MJX-CONTAINER' && m.offsetParent !== null)
          .filter((m) => { const b = m.getBoundingClientRect(); return b.width === 0 || b.height === 0; }).length;
        const wide = inside.filter((e) => e.getBoundingClientRect().right > cw + 1 &&
          !e.closest('.figbox,.tbl-wrap,mjx-container,pre')).slice(0, 5).map((e) => e.tagName.toLowerCase());
        return { zero, wide, sw: document.documentElement.scrollWidth, cw };
      });
      if (o.zero) fail(`${o.zero} zero-size math in the opened worked examples or map`);
      if (o.sw > o.cw + 1) fail(`horizontal overflow with the worked examples and map open ${o.sw} > ${o.cw}: ${o.wide.join(' ')}`);
      else console.log(`  ${opened} worked examples and maps opened: no overflow`);
      for (const [sel, name] of [['details.wex', 'wex'], ['details.examnav', 'map']]) {
        if (!(await page.evaluate((q) => !!document.querySelector(q), sel))) continue;
        // Scroll back past the sticky top bar, so the opened summary shows too.
        await page.evaluate((q) => { document.querySelector(q).scrollIntoView({ block: 'start' }); window.scrollBy(0, -90); }, sel);
        await page.waitForTimeout(200);
        await page.screenshot({ path: path.join(outDir, `${tag}-${name}.png`) });
      }
    }
    await ctx.close();
  }
}
await browser.close();
console.log(failures ? `${failures} FAILURES` : 'ALL CHECKS PASS');
process.exit(failures ? 1 : 0);
