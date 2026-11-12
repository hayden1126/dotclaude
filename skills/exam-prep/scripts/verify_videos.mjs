// Browser checks for the watch list (scripts/videos.py's practice/videos.html) that
// verify_page.mjs doesn't make: its By idea / By lecture toggle. Run verify_page.mjs on the page
// too (the rail, theme chrome, links, overflow in the default view).
//
//   node verify_videos.mjs <videos.html> <outdir>
//
// Playwright comes from pw.mjs, as for verify_page.mjs; allow cdnjs.cloudflare.com,
// fonts.googleapis.com and fonts.gstatic.com. At 390 and 1280 px wide, light and dark: the page
// opens in the by-idea view; pressing By lecture (the shown toggle: the top bar's at 900 px and
// below, the rail's above) shows #view-lecture alone, presses that button in every toggle and hides
// the by-idea rail; each lecture's rows run in timestamp order with every gap marked; neither view
// overflows sideways; the choice survives a reload; a row's link back to its idea switches to the
// by-idea view and lands on that row; By idea brings that view back. No page errors. Shots of the
// viewport go to <outdir>: <width>-<scheme>-idea.png and -lecture.png.
// Exit 0 when every check passes, 1 on any failure, 2 on bad usage.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { loadPlaywright, launch } from './pw.mjs';

function usage(msg) {
  console.error(`verify_videos: ${msg}`);
  console.error('usage: node verify_videos.mjs <videos.html> <outdir>');
  process.exit(2);
}
const pos = process.argv.slice(2);
if (pos.length !== 2) usage('need <videos.html> and <outdir>');
const [pagePath, outDir] = pos;
if (!fs.existsSync(pagePath)) usage(`no page at ${pagePath}`);
const src = fs.readFileSync(pagePath, 'utf8');
if (!/<div id="view-lecture">/.test(src)) usage('the page has no by-lecture view (no segments): nothing to check here');

const { chromium } = await loadPlaywright('verify_videos', pagePath, usage);
fs.mkdirSync(outDir, { recursive: true });
const doc = /^\s*<!doctype/i.test(src) ? src
  : '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width, initial-scale=1">' + src + '</html>';
const wrapped = path.resolve(outDir, 'wrapped.html');
fs.writeFileSync(wrapped, doc);

let failures = 0;
const fail = (m) => { failures++; console.log('  FAIL ' + m); };
const ok = (m) => console.log('  ok ' + m);

const state = () => {
  const vis = (id) => { const el = document.getElementById(id); return !!el && el.getClientRects().length > 0; };
  const se = document.scrollingElement;
  return {
    view: document.documentElement.getAttribute('data-vidview') || 'idea',
    idea: vis('view-idea'), lecture: vis('view-lecture'),
    toc: vis('toc'), tocLec: vis('toc-lec'),
    pressed: [...document.querySelectorAll('.vidtog button[data-vview]')]
      .filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.dataset.vview),
    overflow: se.scrollWidth - se.clientWidth,
  };
};

const browser = await launch(chromium);
for (const width of [390, 1280]) for (const scheme of ['light', 'dark']) {
  const tag = `${width}-${scheme}`;
  console.log(`[${tag}]`);
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: scheme, reducedMotion: 'reduce' });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto(pathToFileURL(wrapped).href, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);

  let s = await page.evaluate(state);
  if (s.view !== 'idea' || !s.idea || s.lecture || s.pressed.some((v) => v !== 'idea')) {
    fail(`${tag}: doesn't open in the by-idea view alone: ${JSON.stringify(s)}`);
  } else ok(`${tag}: opens by idea`);
  if (s.overflow > 0) fail(`${tag}: by idea overflows sideways by ${s.overflow}px`);
  await page.screenshot({ path: path.join(outDir, `${tag}-idea.png`) });

  // the shown toggle: the top bar's at 900 px and below (the rail is a closed drawer), else the rail's
  const bar = width <= 900 ? '.topbar' : '.rail';
  const pick = (v) => page.locator(`${bar} .vidtog button[data-vview="${v}"]`);
  const btn = pick('lecture');
  if (!(await btn.count())) { fail(`${tag}: no By lecture button on screen`); await ctx.close(); continue; }
  await btn.click();
  s = await page.evaluate(state);
  if (s.view !== 'lecture' || s.idea || !s.lecture || s.pressed.some((v) => v !== 'lecture') || s.toc) {
    fail(`${tag}: By lecture didn't show the lecture view alone: ${JSON.stringify(s)}`);
  } else ok(`${tag}: By lecture shows the lecture view alone`);
  if (width > 900 && !s.tocLec) fail(`${tag}: the rail's lecture list isn't shown in the lecture view`);
  if (s.overflow > 0) fail(`${tag}: by lecture overflows sideways by ${s.overflow}px`);
  const order = await page.evaluate(() => [...document.querySelectorAll('section.lect')].map((sec) => {
    const rows = [...sec.querySelectorAll('ol.lrows > li')];
    const starts = rows.filter((r) => r.classList.contains('lrow')).map((r) => Number(r.dataset.start));
    return { id: sec.id, starts, sorted: starts.every((v, i) => !i || starts[i - 1] <= v),
             gaps: rows.filter((r) => r.classList.contains('lgap')).length };
  }));
  for (const o of order) {
    if (!o.sorted) fail(`${tag}: #${o.id}'s rows aren't in timestamp order: ${o.starts.join(', ')}`);
    else ok(`${tag}: #${o.id} in timestamp order (${o.starts.join(', ')}), ${o.gaps} skipped`);
  }
  await page.screenshot({ path: path.join(outDir, `${tag}-lecture.png`) });

  await page.reload({ waitUntil: 'networkidle' });
  s = await page.evaluate(state);
  if (s.view !== 'lecture' || !s.lecture) fail(`${tag}: the lecture view didn't survive a reload: ${JSON.stringify(s)}`);
  else ok(`${tag}: the choice survives a reload`);

  const back = page.locator('section.lect a.lback').first();
  const href = await back.getAttribute('href');
  await back.click();
  await page.waitForTimeout(300);
  const landed = await page.evaluate((h) => {
    const t = document.getElementById(h.slice(1)); const r = t && t.getBoundingClientRect();
    return { view: document.documentElement.getAttribute('data-vidview') || 'idea', hash: location.hash,
             shown: !!t && t.getClientRects().length > 0, top: r ? r.top : null, h: innerHeight };
  }, href);
  if (landed.view !== 'idea' || !landed.shown || landed.hash !== href || landed.top < -2 || landed.top > landed.h - 40) {
    fail(`${tag}: the link back to ${href} didn't land on its row in the by-idea view: ${JSON.stringify(landed)}`);
  } else ok(`${tag}: the link back lands on ${href} by idea`);

  await pick('lecture').click();
  await pick('idea').click();
  s = await page.evaluate(state);
  if (s.view !== 'idea' || !s.idea || s.lecture || !s.toc) fail(`${tag}: By idea didn't bring the idea view back: ${JSON.stringify(s)}`);
  else ok(`${tag}: By idea brings it back`);
  if (errors.length) fail(`${tag}: page errors: ${errors.join(' | ')}`);
  await ctx.close();
}
await browser.close();
console.log(failures ? `${failures} FAILURES` : 'ALL VIDEO CHECKS PASS');
process.exit(failures ? 1 : 0);
