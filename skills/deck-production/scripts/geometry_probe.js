// geometry_probe.js: measures the present reveal slide and returns plain JSON.
//
// It holds no rules. geometry.py evaluates this file once in the page (with
// Runtime.evaluate, which defines its functions globally), then calls
// geometryProbe per slide and fragment step, geometryContrast on a step's
// screenshots, and geometrySettle to wait for what a slide paints with, and
// applies geometry.rules.toml to what comes back.
//
// Every box is in canvas pixels: the client rect divided by Reveal.getScale(),
// minus the origin of the .slides element, which is the canvas. Not the
// section's origin: with `center: true` reveal shifts a short slide down, and
// the margins are the canvas's, not the section's.
//
// opts = {
//   markers: [css selectors],             // map pins and the like
//   exempt:  {ruleId: [css selectors]},   // a text item inside a match is
// }                                       // tagged with that rule id
//
// Returns {canvas, scale, origin, margin, elements, texts, markers, clipping,
// exemptHits}. `elements` is a table indexed by node id; everything else
// points into it, so geometry.py can walk ancestors without the DOM. Each
// element also carries a `uid`, stable across calls in one page: the same
// element probed at two fragment steps has the same uid, and two elements
// with identical selectors never share one.

var geometryUids = new WeakMap();
var geometryNextUid = 0;
var geometryUid = el => {
  if (!geometryUids.has(el)) geometryUids.set(el, geometryNextUid++);
  return geometryUids.get(el);
};

function geometryProbe(opts) {
  const scale = Reveal.getScale();
  const config = Reveal.getConfig();
  const sec = Reveal.getCurrentSlide();
  const canvasEl = Reveal.getSlidesElement ? Reveal.getSlidesElement()
                                           : document.querySelector('.reveal .slides');
  const oR = canvasEl.getBoundingClientRect();
  const r2 = n => Math.round(n * 100) / 100;
  const norm = r => ({
    x: r2((r.left - oR.left) / scale), y: r2((r.top - oR.top) / scale),
    w: r2(r.width / scale), h: r2(r.height / scale),
  });
  const visibleRect = r => r.width / scale >= 0.5 && r.height / scale >= 0.5;

  // The margin token resolved by the browser, so rem, em, % and calc() all
  // come back as canvas px. Undefined token: null (geometry.py falls back).
  let margin = null;
  if (getComputedStyle(sec).getPropertyValue('--margin-slide').trim()) {
    const ruler = document.createElement('div');
    ruler.style.cssText = 'position:absolute;visibility:hidden;height:0;padding:0;border:0;' +
                          'box-sizing:content-box;width:var(--margin-slide)';
    sec.appendChild(ruler);
    margin = r2(ruler.getBoundingClientRect().width / scale);
    ruler.remove();
  }

  // A selector token per element: #id, else the first class no sibling
  // shares, else its first class (or tag) with :nth-child.
  const token = el => {
    if (el.id) return '#' + el.id;
    const parent = el.parentElement;
    const siblings = parent ? [...parent.children].filter(s => s !== el) : [];
    const classes = el.classList ? [...el.classList] : [];
    const unique = classes.find(c => !siblings.some(s => s.classList && s.classList.contains(c)));
    if (unique) return '.' + unique;
    const base = classes.length ? '.' + classes[0] : el.localName;
    const clash = siblings.some(s => classes.length ? s.classList && s.classList.contains(classes[0])
                                                    : s.localName === el.localName);
    return clash ? `${base}:nth-child(${[...parent.children].indexOf(el) + 1})` : base;
  };

  // What an element paints behind content: its own background and those of
  // its ::before/::after, as raw computed [color, image] pairs.
  const paints = el => {
    const out = [];
    const add = cs => out.push([cs.backgroundColor, cs.backgroundImage]);
    add(getComputedStyle(el));
    for (const pseudo of ['::before', '::after']) {
      const cs = getComputedStyle(el, pseudo);
      if (cs.content !== 'none' && cs.content !== 'normal' && cs.display !== 'none') add(cs);
    }
    return out;
  };

  // Is this box moved off the place its formatting context gave it, or does
  // its content spill out of it? A float, a transform (or translate, rotate,
  // scale), a relative offset, a sticky box stuck away from its place, a
  // length or percentage vertical-align (an inline raised or lowered off its
  // line), a negative margin, or content overflowing a fixed size with
  // overflow visible. Two text items whose paths up to their
  // common ancestor hold none of these are lines and boxes the layout engine
  // stacked: they cannot collide, however tight the leading (geometry.py's
  // Slide.one_flow). SVG content is placed by coordinates and never counts.
  const displaced = (el, cs) => {
    if (el instanceof SVGElement) return false;
    if (cs.float !== 'none') return true;
    if (['transform', 'translate', 'rotate', 'scale'].some(k => cs[k] && cs[k] !== 'none')) return true;
    if (cs.position === 'relative' &&
        ['top', 'right', 'bottom', 'left'].some(k => cs[k] !== 'auto' && parseFloat(cs[k]) !== 0)) return true;
    if (['marginTop', 'marginRight', 'marginBottom', 'marginLeft'].some(k => parseFloat(cs[k]) < 0)) return true;
    if (/^-?[\d.]+(px|%)$/.test(cs.verticalAlign) && parseFloat(cs.verticalAlign) !== 0) return true;
    if (cs.position === 'sticky') {
      // Stuck or not: compare with where the box sits unstuck. Sticky keeps
      // its place in flow, so switching it to static moves nothing else.
      const before = el.getBoundingClientRect();
      const style = el.getAttribute('style');
      el.style.setProperty('position', 'static', 'important');
      const after = el.getBoundingClientRect();
      if (style === null) el.removeAttribute('style'); else el.setAttribute('style', style);
      if (Math.abs(before.left - after.left) > 0.5 || Math.abs(before.top - after.top) > 0.5) return true;
    }
    if (cs.display === 'inline' || cs.display === 'contents') return false;   // no box of its own
    return (cs.overflowX === 'visible' && el.scrollWidth > el.clientWidth + 1) ||
           (cs.overflowY === 'visible' && el.scrollHeight > el.clientHeight + 1);
  };

  // The node table. Ancestors register first, so `parent` always resolves;
  // the section itself is the implicit root (parent null).
  const ids = new Map();
  const elements = [];
  const register = el => {
    if (el === sec || !sec.contains(el)) return null;
    if (ids.has(el)) return ids.get(el);
    const parent = register(el.parentElement);
    const cs = getComputedStyle(el);
    const id = elements.length;
    ids.set(el, id);
    elements.push({
      parent, uid: geometryUid(el), token: token(el), tag: el.localName, position: cs.position, display: cs.display,
      displaced: displaced(el, cs),
      fontSize: parseFloat(cs.fontSize), fontWeight: parseInt(cs.fontWeight, 10) || 400,
      paints: paints(el), box: norm(el.getBoundingClientRect()),
    });
    return id;
  };

  // Hidden things are never measured: display none, visibility hidden,
  // opacity 0 anywhere up to the section, and the speaker notes.
  const hidden = el => {
    if (el.closest('aside.notes')) return true;
    if (getComputedStyle(el).visibility !== 'visible') return true;
    for (let n = el; n && n !== sec; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.display === 'none' || parseFloat(cs.opacity) === 0) return true;
    }
    return false;
  };

  const exemptFor = el => Object.entries(opts.exempt || {})
    .filter(([, sels]) => sels.some(sel => !!el.closest(sel)))
    .map(([rule]) => rule);

  // How much of the text reaches the reader through group opacity: the
  // product of every opacity from the element up to the section. Read from
  // computed styles, not inferred from pixels, so a fragment step can be
  // chosen where the item is most visible.
  const shown = el => {
    let v = 1;
    for (let n = el; n && n !== sec.parentElement; n = n.parentElement) v *= parseFloat(getComputedStyle(n).opacity);
    return r2(v);
  };

  // The color glyphs are painted with, as sRGB [r, g, b, a], via a 1x1 canvas
  // so any color syntax (oklch, lab, color-mix) resolves the browser's way.
  // Alpha is the glyph's own (the color's, times fill-opacity in SVG); group
  // opacity and overlays above the text are measured on the screenshots
  // instead (geometryContrast). Text whose glyphs show a background
  // (background-clip: text) or no fill has no single color: null.
  const swatch = document.createElement('canvas');
  swatch.width = swatch.height = 1;
  const sctx = swatch.getContext('2d', { willReadFrequently: true });
  const textColor = el => {
    const cs = getComputedStyle(el);
    if (`${cs.backgroundClip} ${cs.webkitBackgroundClip}`.includes('text')) return null;
    const paint = el instanceof SVGElement ? cs.fill : (cs.webkitTextFillColor || cs.color);
    if (!paint || /^(url|none|context)/.test(paint)) return null;
    const svgAlpha = el instanceof SVGElement ? parseFloat(cs.fillOpacity) : 1;
    // rgb()/rgba() exactly: a canvas stores a translucent color
    // premultiplied, and reads it back up to a byte off.
    const exact = paint.match(/^rgba?\(\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\s*\)$/);
    if (exact) {
      const a = (exact[4] === undefined ? 1 : parseFloat(exact[4])) * svgAlpha;
      return a > 0 ? [+exact[1], +exact[2], +exact[3], a] : null;
    }
    sctx.clearRect(0, 0, 1, 1);
    sctx.fillStyle = '#000';
    sctx.fillStyle = paint;
    sctx.fillRect(0, 0, 1, 1);
    const d = sctx.getImageData(0, 0, 1, 1).data;
    const a = d[3] / 255 * svgAlpha;
    return a > 0 ? [d[0], d[1], d[2], r2(a)] : null;
  };

  // Text items: every element with a direct non-whitespace text node. Boxes are
  // the line rects of those text nodes, not the element box: a block's box
  // spans its container and would report overlaps that are not on screen.
  const byElement = new Map();
  const walker = document.createTreeWalker(sec, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!node.nodeValue.trim() || !node.parentElement) continue;
    const el = node.parentElement;
    if (['script', 'style', 'title'].includes(el.localName)) continue;
    if (!byElement.has(el)) byElement.set(el, []);
    byElement.get(el).push(node);
  }
  const texts = [], textEls = [];
  for (const [el, nodes] of byElement) {
    if (hidden(el)) continue;
    const lines = [];
    for (const node of nodes) {
      const range = document.createRange();
      range.selectNodeContents(node);
      for (const r of range.getClientRects()) if (visibleRect(r)) lines.push(norm(r));
    }
    if (!lines.length) continue;
    const text = el.textContent.trim().replace(/\s+/g, ' ');
    texts.push({ node: register(el), lines, exempt: exemptFor(el), color: textColor(el),
                 shown: shown(el), text: text.slice(0, 60), chars: text.length });
    textEls.push(el);
  }

  // Fit test for text in an absolutely positioned box: is its width decided
  // by this text, and does growth stop only where the room runs out? Shorten
  // the text to one character, then lengthen it by a long run of words, and
  // compare the box's layout width. A box that does not move has a declared
  // width or insets. One that moves is then compared with its room: the width
  // the same box takes stretched to fill what is available from its anchor
  // (the containing block the browser resolves, minus the insets, in every
  // growth direction, so a centered box counts both sides). A lengthened box
  // that fills its room is bounded by nothing of its own, wherever its anchor
  // sits; one that stops short has a max-width.
  const positionedRoot = el => {
    for (let n = el; n && n !== sec; n = n.parentElement) {
      const pos = getComputedStyle(n).position;
      if (pos === 'absolute' || pos === 'fixed') return n;
    }
    return null;
  };
  texts.forEach((t, i) => {
    const el = textEls[i];
    const root = positionedRoot(el);
    t.fit = null;
    if (!root || el instanceof SVGElement) return;
    const own = [...el.childNodes].filter(n => n.nodeType === Node.TEXT_NODE);
    const saved = own.map(n => n.nodeValue);
    own.forEach((n, k) => { n.nodeValue = k === 0 ? 'x' : ''; });
    const short = root.offsetWidth;
    own.forEach((n, k) => { n.nodeValue = saved[k]; });
    const extra = document.createTextNode(' ' + 'lengthen the measure '.repeat(30));
    el.appendChild(extra);
    const long = root.offsetWidth;
    const style = root.getAttribute('style');
    root.style.setProperty('width', '-webkit-fill-available', 'important');
    root.style.setProperty('max-width', 'none', 'important');
    const room = root.offsetWidth;
    if (style === null) root.removeAttribute('style'); else root.setAttribute('style', style);
    extra.remove();
    t.fit = { content: Math.abs(long - short) > 1, edge: long >= room - 2 };
  });

  const boxed = el => {
    const r = el.getBoundingClientRect();
    return visibleRect(r) && !hidden(el) ? { node: register(el), box: norm(r) } : null;
  };
  const markers = [];
  if ((opts.markers || []).length) {
    for (const el of sec.querySelectorAll(opts.markers.join(','))) {
      const item = boxed(el);
      if (item) markers.push(item);
    }
  }

  // Clipping candidates: overflow hidden/clip, content larger than the box,
  // and some text inside. The clip box is the padding box. geometry.py decides
  // whether a text line actually runs past it.
  const clipping = [];
  const clips = v => v === 'hidden' || v === 'clip';
  for (const el of sec.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    const cx = clips(cs.overflowX), cy = clips(cs.overflowY);
    if (!cx && !cy) continue;
    if (el.scrollWidth <= el.clientWidth && el.scrollHeight <= el.clientHeight) continue;
    if (!el.textContent.trim() || hidden(el)) continue;
    const r = el.getBoundingClientRect();
    clipping.push({
      node: register(el), x: cx, y: cy,
      box: { x: r2((r.left - oR.left) / scale + el.clientLeft),
             y: r2((r.top - oR.top) / scale + el.clientTop),
             w: el.clientWidth, h: el.clientHeight },
    });
  }

  // How many measured text items each exempt selector takes out of a rule,
  // so geometry.py can tell a targeted exemption from one that empties it.
  const exemptHits = {};
  for (const [rule, sels] of Object.entries(opts.exempt || {})) {
    exemptHits[rule] = {};
    for (const sel of sels) exemptHits[rule][sel] = textEls.filter(el => !!el.closest(sel)).length;
  }

  return {
    canvas: { w: config.width, h: config.height }, scale,
    origin: { x: oR.left, y: oR.top, w: oR.width, h: oR.height },
    margin, elements, texts, markers, clipping, exemptHits,
  };
}

// Contrast of each text against its rendered backdrop, from five PNGs of
// the canvas, each with only the glyphs changed:
//   H         glyph fill invisible: the backdrop. Text-shadows and SVG halos
//             under the glyph stay, they are what it sits on.
//   SB, SW    each glyph painted black, then white, and stroked 4 px thick
//             in the same color: an opaque swatch exactly where, and in the
//             stacking order where, the glyph paints. Group opacity, masks
//             and anything painted above the text stay as rendered.
//   IB, IW    the glyphs alone on a black page, everything that could veil or
//             cover them taken away.
// Per pixel and channel, whatever lies between the glyph and the reader
// (group opacity, a veil, a gradient scrim, a mask fade, or nothing) maps a
// glyph color x to a*x + b, and the swatches measure that map: b = SB,
// a = (SW - SB) / 255. So the text's own color f, painted at full coverage
// and composited at its alpha fa over the backdrop it hides, reaches the
// reader as H + fa * (SB + a * f - H). That is the color judged against H,
// as WCAG means it: the declared color, not the anti-aliased one, so no
// coverage enters (a thin weight is judged at its color, and the renderer's
// per-color gamma at glyph edges cannot bias it), and a veil over half a
// caption maps that half only.
// The glyph's pixels come from the isolated pair: s = IW - IB is its shape,
// whatever covers it (anything the fill does not change, an emoji or a
// static paint, cancels). Judged pixels are its cores, s at least 0.9 of the
// item's strongest. A core where the swatch does not reach the screen
// (a < 0.1: under an opaque panel or image) is counted as hidden, not
// judged. Per item the result is {q, n, hidden}: 101 quantiles (0th..100th
// percentile) of the WCAG 2.x ratio over the n judged pixels, unrounded, so
// the percentile and any rounding stay geometry.py's; and the share of core
// pixels hidden. An item with no glyph pixels at all, or passed as null, is
// null. The PNGs are decoded by the browser into a canvas: native and fast,
// where a Python decoder would loop over every byte.
async function geometryContrast(shots, items, scale) {
  const decode = async url => {
    const img = new Image();
    img.src = url;
    await img.decode();
    const cv = document.createElement('canvas');
    cv.width = img.naturalWidth;
    cv.height = img.naturalHeight;
    const ctx = cv.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    return ctx.getImageData(0, 0, cv.width, cv.height);
  };
  const sb = (await decode(shots.swatchBlack)).data, sw = (await decode(shots.swatchWhite)).data;
  const ib = (await decode(shots.shapeBlack)).data, iw = (await decode(shots.shapeWhite)).data;
  const hidden = await decode(shots.hidden);
  const W = hidden.width, H = hidden.height, px = hidden.data;
  // In floats: the judged color is not rounded to a byte, which on a dark
  // color would move the ratio by up to a tenth.
  const lin = v => {
    const c = Math.max(0, Math.min(255, v)) / 255;
    return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  const lum = (r, g, b) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  const diff = (a, b, i) => (a[i] - b[i] + a[i + 1] - b[i + 1] + a[i + 2] - b[i + 2]) / 765;
  return items.map(item => {
    if (!item) return null;
    // Pixel-center rule: a pixel belongs to a rect when its center is inside.
    const pixels = [];
    for (const l of item.lines) {
      const x0 = Math.max(0, Math.round(l.x * scale)), y0 = Math.max(0, Math.round(l.y * scale));
      const x1 = Math.min(W, Math.round((l.x + l.w) * scale));
      const y1 = Math.min(H, Math.round((l.y + l.h) * scale));
      for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) pixels.push((y * W + x) * 4);
    }
    let top = 0;
    for (const i of pixels) top = Math.max(top, diff(iw, ib, i));
    if (top < 0.02) return null;
    const cores = pixels.filter(i => diff(iw, ib, i) >= 0.9 * top);
    const shown = cores.filter(i => diff(sw, sb, i) >= 0.1);
    const share = Math.round((cores.length - shown.length) / cores.length * 1000) / 1000;
    // No single glyph color (background-clip: text): coverage only.
    if (!item.color || !shown.length) return { q: null, n: 0, hidden: share };
    const [fr, fg, fb, fa] = item.color;
    const seen = (i, k, f) => px[i + k] + fa * (sb[i + k] + (sw[i + k] - sb[i + k]) * f / 255 - px[i + k]);
    const sorted = Float64Array.from(shown, i => {
      const tl = lum(seen(i, 0, fr), seen(i, 1, fg), seen(i, 2, fb));
      const bl = lum(px[i], px[i + 1], px[i + 2]);
      return (Math.max(tl, bl) + 0.05) / (Math.min(tl, bl) + 0.05);
    }).sort();
    const n = sorted.length;
    const q = [];
    for (let p = 0; p <= 100; p++) q.push(sorted[Math.max(1, Math.ceil(p / 100 * n)) - 1]);
    return { q, n, hidden: share };
  });
}

// Wait for a set of things a slide paints with, all started before the
// deadline, and name the ones still pending when it passes. One deadline for
// all, started once: a resource is reported slow only if it was still
// pending at the deadline, never because a later wait found no budget left.
// tasks = [[promise, what], ...]; rejections count as settled.
async function geometrySettle(tasks, budget) {
  const pending = new Map(tasks.map(([, what], i) => [i, what]));
  const done = tasks.map(([p], i) =>
    Promise.resolve(p).then(() => pending.delete(i), () => pending.delete(i)));
  let timer;
  const deadline = new Promise(r => { timer = setTimeout(r, Math.max(0, budget)); });
  await Promise.race([Promise.all(done), deadline]);
  clearTimeout(timer);
  return [...new Set(pending.values())];
}
