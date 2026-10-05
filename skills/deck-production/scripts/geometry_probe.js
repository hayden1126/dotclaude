// geometry_probe.js: measures the present reveal slide and returns plain JSON.
//
// It holds no rules. geometry.py evaluates this file once in the page (with
// Runtime.evaluate, which defines both functions globally), then calls
// geometryProbe per slide and geometryContrast on that slide's screenshot,
// and applies geometry.rules.toml to what comes back.
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
// Returns {canvas, scale, origin, margin, elements, texts, markers, clipping}.
// `elements` is a table indexed by node id; everything else points into it,
// so geometry.py can walk ancestors without the DOM.

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
      parent, token: token(el), tag: el.localName, position: cs.position, display: cs.display,
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

  // The color glyphs are painted with, as sRGB [r, g, b, a], via a 1x1 canvas
  // so any color syntax (oklch, lab, color-mix) resolves the browser's way.
  // Ancestor opacity folds into alpha. Text whose glyphs show a background
  // (background-clip: text) or no fill has no single color: null.
  const swatch = document.createElement('canvas');
  swatch.width = swatch.height = 1;
  const sctx = swatch.getContext('2d', { willReadFrequently: true });
  const textColor = el => {
    const cs = getComputedStyle(el);
    if (`${cs.backgroundClip} ${cs.webkitBackgroundClip}`.includes('text')) return null;
    const paint = el instanceof SVGElement ? cs.fill : (cs.webkitTextFillColor || cs.color);
    if (!paint || /^(url|none|context)/.test(paint)) return null;
    sctx.clearRect(0, 0, 1, 1);
    sctx.fillStyle = '#000';
    sctx.fillStyle = paint;
    sctx.fillRect(0, 0, 1, 1);
    const d = sctx.getImageData(0, 0, 1, 1).data;
    let a = d[3] / 255;
    for (let n = el; n && n !== sec; n = n.parentElement) a *= parseFloat(getComputedStyle(n).opacity);
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
                 text: text.slice(0, 60), chars: text.length });
    textEls.push(el);
  }

  // Fit test for text in an absolutely positioned box: is the box's width
  // decided by this text, and does it run to the containing block's edge?
  // Shorten the text to one character, then lengthen it by a long run of
  // words, and compare the box. A box that does not move has a declared
  // width or insets. One that moves but stops short of the containing block
  // has a max-width. One that runs to the containing block's edge is bounded
  // by nothing of its own; that includes a content-sized box that already
  // wraps at the container, which a lengthen-only test would call bounded.
  const positionedRoot = el => {
    for (let n = el; n && n !== sec; n = n.parentElement) {
      const pos = getComputedStyle(n).position;
      if (pos === 'absolute' || pos === 'fixed') return n;
    }
    return null;
  };
  const containingBlock = el => {
    for (let n = el.parentElement; n && n !== sec; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.position !== 'static' || cs.transform !== 'none') return n;
    }
    return sec;
  };
  texts.forEach((t, i) => {
    const el = textEls[i];
    const root = positionedRoot(el);
    t.fit = null;
    if (!root || el instanceof SVGElement) return;
    const own = [...el.childNodes].filter(n => n.nodeType === Node.TEXT_NODE);
    const saved = own.map(n => n.nodeValue);
    own.forEach((n, k) => { n.nodeValue = k === 0 ? 'x' : ''; });
    const short = root.getBoundingClientRect();
    own.forEach((n, k) => { n.nodeValue = saved[k]; });
    const extra = document.createTextNode(' ' + 'lengthen the measure '.repeat(30));
    el.appendChild(extra);
    const long = root.getBoundingClientRect();
    extra.remove();
    const cb = containingBlock(root);
    const cR = cb.getBoundingClientRect();
    const left = cR.left + cb.clientLeft * scale, right = left + cb.clientWidth * scale;
    const movesL = Math.abs(long.left - short.left) > scale;
    const movesR = Math.abs(long.right - short.right) > scale;
    t.fit = { content: movesL || movesR,
              edge: (movesR && long.right >= right - 2 * scale) ||
                    (movesL && long.left <= left + 2 * scale) };
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

  return {
    canvas: { w: config.width, h: config.height }, scale,
    origin: { x: oR.left, y: oR.top, w: oR.width, h: oR.height },
    margin, elements, texts, markers, clipping,
  };
}

// Contrast of each text against its rendered backdrop, from three PNGs of
// the canvas: glyphs forced black, forced white, and invisible (text-shadows
// kept in all three: a shadow is part of what the glyph sits on). Where the
// black and white shots differ is where glyphs paint, whatever the backdrop's
// color: coverage = (white - black) / 255. Only pixels at least half covered
// are judged, so a box edge a fraction of a pixel past a panel, or the gaps
// between letters, do not count, while white glyphs on a white patch still
// do. Each judged pixel composites the text color over the invisible-glyph
// backdrop and takes the WCAG 2.x ratio; the result is 101 quantiles
// (0th..100th percentile), so the percentile to judge stays a rule parameter.
// The PNGs are decoded by the browser into a canvas: native and fast, where a
// Python decoder would loop over every byte.
async function geometryContrast(blackUrl, whiteUrl, hiddenUrl, items, scale) {
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
  const black = (await decode(blackUrl)).data, white = (await decode(whiteUrl)).data;
  const hidden = await decode(hiddenUrl);
  const W = hidden.width, H = hidden.height, px = hidden.data;
  const lin = new Float64Array(256);
  for (let i = 0; i < 256; i++) {
    const c = i / 255;
    lin[i] = c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  }
  const lum = (r, g, b) => 0.2126 * lin[r] + 0.7152 * lin[g] + 0.0722 * lin[b];
  return items.map(({ lines, color }) => {
    if (!color) return null;
    const [fr, fg, fb, fa] = color;
    // Pixel-center rule: a pixel belongs to a rect when its center is inside.
    const boxes = lines.map(l => [
      Math.max(0, Math.round(l.x * scale)), Math.max(0, Math.round(l.y * scale)),
      Math.min(W, Math.round((l.x + l.w) * scale)), Math.min(H, Math.round((l.y + l.h) * scale))]);
    const judge = glyphsOnly => {
      const bins = new Uint32Array(2001);      // ratio 1.00..21.00 in 0.01 steps
      let n = 0;
      for (const [x0, y0, x1, y1] of boxes) {
        for (let y = y0; y < y1; y++) {
          for (let x = x0; x < x1; x++) {
            const i = (y * W + x) * 4;
            const br = px[i], bg = px[i + 1], bb = px[i + 2];
            if (glyphsOnly && (white[i] - black[i]) + (white[i + 1] - black[i + 1]) +
                              (white[i + 2] - black[i + 2]) < 3 * 128) continue;
            const tl = lum(Math.round(fa * fr + (1 - fa) * br), Math.round(fa * fg + (1 - fa) * bg),
                           Math.round(fa * fb + (1 - fa) * bb));
            const bl = lum(br, bg, bb);
            const ratio = (Math.max(tl, bl) + 0.05) / (Math.min(tl, bl) + 0.05);
            bins[Math.min(2000, Math.round((ratio - 1) * 100))]++;
            n++;
          }
        }
      }
      return [bins, n];
    };
    let [bins, n] = judge(true);
    if (!n) [bins, n] = judge(false);
    if (!n) return null;
    const q = [];
    let cum = 0, k = 0;
    for (let p = 0; p <= 100; p++) {
      const target = Math.max(1, Math.ceil(p / 100 * n));
      while (cum < target && k < 2001) cum += bins[k++];
      q.push(Math.round(100 + (k - 1)) / 100);
    }
    return q;
  });
}
