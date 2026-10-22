// Browser checks for an assembled page (the notes page, the mock page), headless Chromium.
//
//   node verify_page.mjs <page.html> <outdir> [--spy id,id,...] [--steps <steps.json>] [--views]
//
// Playwright comes from pw.mjs: $EXAM_PREP_PLAYWRIGHT, else an install it finds, else it says how
// to install one and exits 2. Run it with `allowed_domains` cdnjs.cloudflare.com,
// fonts.googleapis.com and fonts.gstatic.com: the page loads MathJax and its fonts from them, and
// Chromium gets the sandbox's proxy passed in (L21).
// A page without a doctype is wrapped in a standards-mode document first, as the artifact host
// does (L19). Then, at 390 and 1280 px wide, light and dark:
//   - MathJax loaded and finished; no math left as raw \( \) or \[ \]; no TeX error and no
//     undefined macro (MathJax draws both, in red, inside its output); no zero-size math;
//   - MathJax's ui/safe loaded, its window.MathJax pinning loader.paths.mathjax to the directory
//     of its <script id="MathJax-script">, no script loaded from anywhere else, and nothing inside
//     the math with an id or class but mjx-* or a style that positions or loads (what \class,
//     \cssId, \style and \bbox add); a MathJax failure (never loaded, never finished, rejected,
//     its components from elsewhere) ends the run there;
//   - no horizontal overflow (wide figures, tables, math and pre scroll in their own boxes), and
//     none of either inside the worked examples and the exam-day map once they are opened;
//   - every href="#id" resolves, no id repeats, no link (math's too) runs javascript:, and no
//     element carries an inline event handler (on...=);
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
//     a note. A page with no section.note (the mock page) has no default targets;
//   - with --views (the mock page, 08-practice), each view button (nav.views button[data-view]),
//     pressed in turn, shows its own #view-<name> and no other, reads as the only one pressed,
//     holds the same parts (distinct data-part values) as the first view, and has no zero-size
//     math and no horizontal overflow, its closed stems (details) opened too; fewer than two
//     buttons fail.
// Screenshots of the viewport (never full page, L23) go to <outdir>: <width>-<scheme>-top.png, one
// per spy target, one per step-through at its last frame, one per static figure (its id; one inside
// a closed worked example is shot with it opened), the first worked example opened (-wex)
// and the exam-day map opened (-map), and with --views one per view (-view-<name>). Exit 0 when every check passes, 1 on any failure, 2 on bad
// usage.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { loadChromium, launch } from './pw.mjs';

function usage(msg) {
  console.error(`verify_page: ${msg}`);
  console.error('usage: node verify_page.mjs <page.html> <outdir> [--spy id,id] [--steps <steps.json>] [--views]');
  process.exit(2);
}

const args = process.argv.slice(2);
let spyArg = null;
let stepsArg = null;
let viewsArg = false;
const pos = [];
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--spy') spyArg = args[++i];
  else if (args[i] === '--steps') stepsArg = args[++i];
  else if (args[i] === '--views') viewsArg = true;
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

const chromium = await loadChromium('verify_page', pagePath, usage);

fs.mkdirSync(outDir, { recursive: true });
const src = fs.readFileSync(pagePath, 'utf8');
const doc = /^\s*<!doctype/i.test(src) ? src
  : '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width, initial-scale=1">' + src + '</html>';
const wrapped = path.resolve(outDir, 'wrapped.html');
fs.writeFileSync(wrapped, doc);

// MathJax loads its components from a root it takes off document.currentScript unless the
// page's config pins loader.paths.mathjax, and an element named currentScript replaces that
// (DOM clobbering): the root must be pinned to its own script's directory. Only <script> tags
// count, which no fragment holds.
const scriptTags = [...doc.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)];
const mjTag = scriptTags.find((m) => /\bid=["']MathJax-script["']/.test(m[1]));
const mjSrc = mjTag && (mjTag[1].match(/\bsrc=["']([^"']+)["']/) || [])[1];
const mjRoot = mjSrc ? mjSrc.replace(/\/[^/]*$/, '') : null;
const pins = scriptTags.filter((m) => !/\bsrc=/.test(m[1]))
  .map((m) => (m[2].match(/\bpaths\s*:\s*\{\s*mathjax\s*:\s*['"]([^'"]+)['"]/) || [])[1]).filter(Boolean);

const browser = await launch(chromium);
let failures = 0;
const fail = (m) => { failures++; console.log('  FAIL ' + m); };
if (!mjRoot) fail('no <script id="MathJax-script" src="..."> in the page (the templates have it)');
else if (!pins.includes(mjRoot)) {
  fail(`window.MathJax doesn't pin loader.paths.mathjax to ${mjRoot} (the templates do): unpinned, an element ` +
       'named currentScript chooses the host MathJax loads its components from');
}

let mathjaxDown = false;
for (const width of [390, 1280]) {
  if (mathjaxDown) break;
  for (const scheme of ['light', 'dark']) {
    const tag = `${width}-${scheme}`;
    console.log(`[${tag}]`);
    const ctx = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: scheme, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    const scripts = [];
    page.on('request', (q) => { if (q.resourceType() === 'script') scripts.push(q.url()); });
    await page.goto(pathToFileURL(wrapped).href, { waitUntil: 'networkidle' });
    // Checked again once MathJax finishes: it autoloads extensions while it typesets.
    const outside = () => {
      const foreign = scripts.filter((u) => !mjRoot || !u.startsWith(mjRoot + '/'));
      return foreign.length ? `scripts loaded from outside MathJax's own directory: ${foreign.slice(0, 3).join(', ')}` : '';
    };
    let down = outside();
    if (!down) {
      try {
        // A boolean: waitForFunction awaits a promise the predicate returns, so returning the
        // startup promise itself would wait out a hang here and call it never loaded.
        await page.waitForFunction(() => !!(window.MathJax && MathJax.startup && MathJax.startup.promise), null, { timeout: 30000 });
      } catch (e) {
        down = 'MathJax never loaded: run with allowed_domains for cdnjs.cloudflare.com (L21)';
      }
    }
    // A component that never arrives (ui/safe among them) leaves the promise pending forever; one
    // that fails to load rejects it.
    const started = down ? '' : await page.evaluate(() => Promise.race([
      MathJax.startup.promise.then(() => 'ok', () => 'rejected'),
      new Promise((res) => setTimeout(() => res('timeout'), 20000))]));
    if (started === 'timeout') down = 'MathJax never finished typesetting (a component it never got, or a startup that hangs)';
    else if (started === 'rejected') down = 'MathJax failed while starting (a component that failed to load)';
    // The root MathJax actually used: the pin in the page's text could sit in a comment.
    const root = down ? '' : await page.evaluate(() => MathJax.config.loader.paths.mathjax);
    if (!down) down = outside();
    if (!down && root !== mjRoot) down = `MathJax loaded its components from ${root}, not its own directory ${mjRoot}`;
    if (down) {
      fail(down + '; nothing else checked');
      mathjaxDown = true;
      await ctx.close();
      break;
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
      // A browser drops leading spaces and control characters and ignores case in a scheme, so
      // " JavaScript:" runs too; MathJax's \\href puts its link inside the math's SVG.
      const jsLinks = [...document.querySelectorAll('*')].filter((e) => {
        const h = e.getAttribute('href') || e.getAttributeNS('http://www.w3.org/1999/xlink', 'href') || '';
        return /^javascript:/i.test(h.replace(/[\u0000-\u0020]/g, ''));
      }).length;
      // The page's own scripts bind no inline handler, so any on...= is markup the build let
      // through (a figure tag left open reads on into the page as an <img onerror>).
      const onAttrs = [...document.querySelectorAll('*')].filter((e) => [...e.attributes].some((a) => /^on/i.test(a.name)))
        .map((e) => e.tagName.toLowerCase());
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
      // ui/safe filters the links, classes, ids and styles MathJax's own parse of \\href, \\class,
      // \\cssId, \\style and \\bbox would add, whatever text the build's checks read.
      const safe = !!(MathJax._ && MathJax._.ui && MathJax._.ui.safe);
      // Should it miss one: MathJax's own output carries no class or id inside its container but
      // mjx-* (an equation label's id, with tags on, as ui/safe's own pattern allows) and no
      // positioned style, so any of those came from a macro.
      const mathAttrs = [...document.querySelectorAll('mjx-container *')].filter((e) => (e.id && !e.id.startsWith('mjx-'))
        || (e.getAttribute('class') || '').split(/\s+/).some((c) => c && !c.startsWith('mjx-'))
        || /position|url\(|image-set/i.test(e.getAttribute('style') || '')).length;
      return { mj: mj.length, zero: zero.length, raw, links: hrefs.length, broken, dup, sw, cw, wide, fonts, openWex, jsLinks,
        onAttrs, texErr, safe, mathAttrs, bg: getComputedStyle(document.body).backgroundColor };
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
    if (!r.safe) fail("MathJax's ui/safe isn't loaded: the page's window.MathJax lacks load:['ui/safe'] in its loader (the templates have it)");
    if (r.mathAttrs) fail(`${r.mathAttrs} elements inside math with a class, id or style MathJax's own output never has (a \\class, \\cssId, \\style or \\bbox)`);
    if (r.jsLinks) fail(`${r.jsLinks} javascript: links (a MathJax \\href or \\mmlToken the build let through)`);
    if (r.onAttrs.length) fail(`${r.onAttrs.length} elements with an inline event handler: ${[...new Set(r.onAttrs)].join(', ')}`);
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

    // Every static figure too: only a look catches an edge drawn through a node or a label on a line.
    const statics = await page.evaluate(() => [...document.querySelectorAll('figure[id]')]
      .filter((f) => !f.querySelector('.fig-controls')).map((f) => f.id));
    for (const id of statics) {
      await page.evaluate((i) => {
        const fig = document.getElementById(i);
        for (let d = fig.closest('details'); d; d = d.parentElement.closest('details')) {
          if (!d.open) { d.open = true; d.dataset.vpShot = '1'; }
        }
        fig.scrollIntoView({ block: 'center' });
      }, id);
      await page.waitForTimeout(200);
      // A shot of the wrong place would still get the figure's name, so it must be on screen.
      const seen = await page.evaluate((i) => {
        const r = document.getElementById(i).getBoundingClientRect();
        return r.width > 0 && r.height > 0 && r.top < innerHeight && r.bottom > 0;
      }, id);
      if (!seen) fail(`${tag}: static figure #${id} not visible for its shot`);
      await page.screenshot({ path: path.join(outDir, `${tag}-${id}.png`) });
      await page.evaluate(() => document.querySelectorAll('details[data-vp-shot]').forEach((d) => {
        d.open = false;
        delete d.dataset.vpShot;
      }));
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
    if (viewsArg) {
      const views = await page.evaluate(() => [...document.querySelectorAll('nav.views button[data-view]')]
        .map((b) => b.dataset.view));
      if (views.length < 2) fail(`--views: ${views.length} view buttons (nav.views button[data-view]); want two or more`);
      let first = null;
      for (const v of views) {
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.click(`nav.views button[data-view="${v}"]`);
        await page.waitForTimeout(250);
        await page.screenshot({ path: path.join(outDir, `${tag}-view-${v}.png`) });
        const s = await page.evaluate((name) => {
          const pane = document.getElementById('view-' + name);
          const shown = [...document.querySelectorAll('[id^="view-"]')]
            .filter((p) => !p.hidden && p.offsetParent !== null).map((p) => p.id);
          const pressed = [...document.querySelectorAll('nav.views button[data-view]')]
            .filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.dataset.view);
          if (!pane) return { pane: false, shown, pressed };
          pane.querySelectorAll('details').forEach((d) => { d.open = true; });
          const parts = [...new Set([...pane.querySelectorAll('[data-part]')].map((e) => e.dataset.part))].sort();
          const zero = [...pane.querySelectorAll('mjx-container')]
            .filter((m) => { const b = m.getBoundingClientRect(); return b.width === 0 || b.height === 0; }).length;
          const cw = document.documentElement.clientWidth;
          const wide = [...pane.querySelectorAll('*')].filter((e) => e.getBoundingClientRect().right > cw + 1 &&
            !e.closest('.figbox,.tbl-wrap,mjx-container,pre')).slice(0, 5)
            .map((e) => e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className : ''));
          return { pane: true, shown, pressed, parts, zero, wide, sw: document.documentElement.scrollWidth, cw };
        }, v);
        if (!s.pane) { fail(`view ${v}: no #view-${v} for its button`); continue; }
        if (s.shown.join() !== `view-${v}`) fail(`view ${v}: shows ${s.shown.join(', ') || 'nothing'}`);
        if (s.pressed.join() !== v) fail(`view ${v}: pressed buttons ${s.pressed.join(', ') || 'none'}`);
        if (!s.parts.length) fail(`view ${v}: no parts (data-part)`);
        if (first === null) first = { v, parts: s.parts };
        else {
          const missing = first.parts.filter((p) => !s.parts.includes(p));
          const extra = s.parts.filter((p) => !first.parts.includes(p));
          if (missing.length) fail(`view ${v}: lacks ${missing.join(', ')}, which view ${first.v} holds`);
          if (extra.length) fail(`view ${v}: holds ${extra.join(', ')}, which view ${first.v} lacks`);
        }
        if (s.zero) fail(`view ${v}: ${s.zero} zero-size math`);
        if (s.sw > s.cw + 1) fail(`view ${v}: horizontal overflow ${s.sw} > ${s.cw}: ${s.wide.join(' ')}`);
        console.log(`  view ${v}: ${s.parts.length} parts`);
      }
    }
    await ctx.close();
  }
}
await browser.close();
console.log(failures ? `${failures} FAILURES` : 'ALL CHECKS PASS');
process.exit(failures ? 1 : 0);
