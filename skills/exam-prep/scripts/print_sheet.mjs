// Print a cheat sheet to PDF with headless Chromium and measure its layout (07-cheatsheet).
//
//   node print_sheet.mjs <sheet.html> <out.pdf>
//
// The sheet is a full document from templates/cheatsheet.html: a doctype first (quirks mode lays
// it out differently), one .page per printed side. It refuses a sheet with no doctype, a
// {{SLOT}} left from the template, a <script> (the sheet prints with JavaScript off, so nothing on
// it may need one), or no .page. It prints with print media and the light scheme, at the size the
// sheet's own @page rule sets (preferCSSPageSize; orientation comes from CSS only, L62), once its
// fonts are ready. It must print offline: a request for anything but a local file is aborted and
// recorded, and check_pdf.py fails the sheet for it.
//
// Beside the PDF it writes <out>.layout.json, which check_pdf.py reads:
//   {"pdf_sha256": the PDF it measured, "sheet": the sheet's path relative to this file,
//    "sheet_sha256": the sheet it printed, "remote": [aborted URLs],
//    "pages": [{"id", "columns", "overflow", "wide": [...], "fill": {"col", "bottom"} or null}]}
// one entry per .page, in order. `overflow` is content the page's overflow:hidden clips, such as
// a column spilled past the last one, which the PDF's page count can't show (L60, FB-138). `wide`
// names each table, block or text run that runs past its own column's right edge, over the gap
// or the next column. `fill` is where the side's content ends: the column (1-based) of its last
// text, table or figure and how far down the page that ends (0 to 1). Font sizes are
// check_pdf.py's: it reads them from the PDF, where superscripts and SVG text print at their real
// size (L61).
//
// Playwright comes from pw.mjs. Exit 0 when the PDF and the layout file are written, 1 when the
// sheet is refused or the print fails, 2 on bad usage.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { loadChromium, launch } from './pw.mjs';

function usage(msg) {
  console.error(`print_sheet: ${msg}`);
  console.error('usage: node print_sheet.mjs <sheet.html> <out.pdf>');
  process.exit(2);
}

function refuse(msg) {
  console.error(`print_sheet: ${msg}`);
  process.exit(1);
}

const sha256 = (buf) => crypto.createHash('sha256').update(buf).digest('hex');

const args = process.argv.slice(2);
if (args.length !== 2) usage('need <sheet.html> and <out.pdf>');
const [sheetPath, outArg] = args;
if (!fs.existsSync(sheetPath)) usage(`no sheet at ${sheetPath}`);
if (!outArg.endsWith('.pdf')) usage(`${outArg}: the output must end in .pdf`);
const outPdf = path.resolve(outArg);
if (!fs.existsSync(path.dirname(outPdf))) usage(`no directory ${path.dirname(outPdf)}`);
const layoutPath = outPdf.replace(/\.pdf$/, '.layout.json');

const raw = fs.readFileSync(sheetPath);
const src = raw.toString('utf8');
if (!/^\s*<!doctype html>/i.test(src)) refuse(`${sheetPath} doesn't start with <!doctype html>: copy templates/cheatsheet.html`);
const left = src.match(/\{\{[A-Z][A-Z0-9 ]{2,}\}\}/);
if (left) refuse(`${sheetPath} still holds the slot ${left[0]}`);

const chromium = await loadChromium('print_sheet', sheetPath, usage);
const browser = await launch(chromium);
let failed = false;
try {
  const page = await browser.newPage({ javaScriptEnabled: false });
  const remote = [];
  await page.route(/^(?!file:|data:|blob:|about:)/, (route) => {
    remote.push(route.request().url());
    return route.abort();
  });
  await page.emulateMedia({ media: 'print', colorScheme: 'light' });
  await page.goto(pathToFileURL(path.resolve(sheetPath)).href, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  if (await page.evaluate(() => document.querySelector('script') !== null)) {
    throw new Error(`${sheetPath} holds a <script>: the sheet prints with JavaScript off, so remove it`);
  }

  const pages = await page.evaluate(() => {
    // What spans every column (the header strip, a .span row) sits above the columns; the page's
    // own overflow covers it.
    function spansAll(el, root) {
      for (let e = el; e && e !== root; e = e.parentElement) {
        if (getComputedStyle(e).columnSpan === 'all') return true;
      }
      return false;
    }
    const brief = (el, text) => `${el.localName}${el.classList.length ? `.${el.classList[0]}` : ''} "${
      text.replace(/\s+/g, ' ').trim().slice(0, 40)}"`;
    // Every printed piece of content in the side's columns: each non-blank text run's line boxes,
    // each table and pre block, and each figure or image as a whole (an SVG's insides are drawn
    // inside its own box). A block the columns break apart gives one box per piece: its bounding
    // box would span from one column into the next.
    function contentBoxes(root) {
      const out = [];
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const el = n.nodeType === Node.TEXT_NODE ? n.parentElement : n;
        if (el.closest('svg') && n.localName !== 'svg') continue;
        if (spansAll(el, root)) continue;
        if (n.nodeType === Node.TEXT_NODE) {
          if (!n.nodeValue.trim()) continue;
          const range = document.createRange();
          range.selectNodeContents(n);
          for (const b of range.getClientRects()) out.push({ b, what: brief(el, n.nodeValue) });
        } else if (['svg', 'img', 'canvas', 'table', 'pre'].includes(n.localName)) {
          const what = brief(n, n.textContent || n.getAttribute('aria-label') || '');
          for (const b of n.getClientRects()) out.push({ b, what });
        }
      }
      return out.filter(({ b }) => b.width > 0 && b.height > 0);
    }
    return [...document.querySelectorAll('.page')].map((p, i) => {
      const r = p.getBoundingClientRect();
      const style = getComputedStyle(p);
      const columns = parseInt(style.columnCount, 10) || 1;
      const gap = parseFloat(style.columnGap) || 0;
      const colWidth = (r.width - (columns - 1) * gap) / columns;
      const overflow = p.scrollWidth > p.clientWidth + 1 || p.scrollHeight > p.clientHeight + 1;
      // Column k starts at (k - 1) * (colWidth + gap), so this floor names it; a box past the last
      // column (clipped) gets a number above `columns`.
      let fill = null;
      const wide = new Set();
      for (const { b, what } of contentBoxes(p)) {
        const col = Math.floor((b.left - r.left + 0.5) / (r.width / columns)) + 1;
        const bottom = Math.round(((b.bottom - r.top) / r.height) * 100) / 100;
        if (!fill || col > fill.col || (col === fill.col && bottom > fill.bottom)) fill = { col, bottom };
        const right = r.left + (col - 1) * (colWidth + gap) + colWidth;
        if (col <= columns && b.right > right + 1 && wide.size < 10) wide.add(`column ${col}: ${what}`);
      }
      return { id: p.id || `page-${i + 1}`, columns, overflow, wide: [...wide], fill };
    });
  });
  if (!pages.length) throw new Error(`${sheetPath} has no .page element: one per printed side`);

  await page.pdf({ path: outPdf, printBackground: true, preferCSSPageSize: true });
  const layout = {
    pdf_sha256: sha256(fs.readFileSync(outPdf)),
    sheet: path.relative(path.dirname(layoutPath), path.resolve(sheetPath)),
    sheet_sha256: sha256(raw),
    remote,
    pages,
  };
  fs.writeFileSync(layoutPath, `${JSON.stringify(layout, null, 1)}\n`);
  console.log(`wrote ${outPdf}`);
  console.log(`wrote ${layoutPath}`);
  for (const p of pages) {
    const where = p.fill ? `ends in column ${p.fill.col} of ${p.columns}, ${p.fill.bottom} down` : 'empty';
    console.log(`  ${p.id}: ${where}${p.overflow ? ', OVERFLOW (clipped)' : ''}`);
    // The box's own text, which may hold the student's name, waits for check_pdf.py to mask it.
    for (const w of p.wide) console.log(`    WIDER THAN ITS COLUMN: ${w.split(' "')[0]}`);
  }
  for (const u of remote) console.log(`  REMOTE request aborted, to ${new URL(u).host}`);
} catch (e) {
  console.error(`print_sheet: ${e.message}`);
  failed = true;
} finally {
  await browser.close();
}
process.exit(failed ? 1 : 0);
