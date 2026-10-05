// geometry_probe.js: measures the present reveal slide and returns plain JSON.
//
// It holds no rules. geometry.py evaluates this file in the page (with
// Runtime.evaluate, so it must stay self-contained: one function, no outer
// references), then applies geometry.rules.toml to what comes back.
//
// Every box is in canvas pixels: the client rect divided by Reveal.getScale(),
// minus the section's origin. A slide therefore measures the same at any
// window size, and (0, 0) is the canvas's top-left corner.
//
// opts = {
//   markers: [css selectors],             // map pins and the like
//   exempt:  {ruleId: [css selectors]},   // a text item inside a match is
// }                                       // tagged with that rule id
//
// Returns {canvas, scale, margin, elements, texts, markers, media, clipping}.
// `elements` is a table indexed by node id; everything else points into it,
// so geometry.py can walk ancestors without the DOM.

function geometryProbe(opts) {
  const scale = Reveal.getScale();
  const config = Reveal.getConfig();
  const sec = Reveal.getCurrentSlide();
  const secR = sec.getBoundingClientRect();
  const r2 = n => Math.round(n * 100) / 100;
  const norm = r => ({
    x: r2((r.left - secR.left) / scale), y: r2((r.top - secR.top) / scale),
    w: r2(r.width / scale), h: r2(r.height / scale),
  });
  const visibleRect = r => r.width / scale >= 0.5 && r.height / scale >= 0.5;

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
  // its ::before/::after, as raw computed [color, image] pairs. A scrim is
  // often a pseudo-element, and hit testing reports a pseudo as its host.
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
      parent, token: token(el), tag: el.localName,
      position: cs.position, display: cs.display, maxWidth: cs.maxWidth,
      textShadow: cs.textShadow, fontSize: parseFloat(cs.fontSize),
      fontWeight: parseInt(cs.fontWeight, 10) || 400,
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
    .filter(([, sels]) => sels.some(sel => { try { return !!el.closest(sel); } catch (e) { return false; } }))
    .map(([rule]) => rule);

  const boxed = el => {
    const r = el.getBoundingClientRect();
    return visibleRect(r) && !hidden(el) ? { node: register(el), box: norm(r) } : null;
  };

  // Media is raster: img, video, canvas, an svg that embeds an <image>, and an
  // element with a url() background. A vector svg (lines, charts, leader
  // strokes) is drawing, not a picture, and text over it stays legible.
  // `scrimmed` marks a url() background with a gradient layer painted above it.
  const media = [];
  for (const el of sec.querySelectorAll('img, video, canvas, svg')) {
    if (el.localName === 'svg' && (!el.querySelector('image') || el.parentElement.closest('svg'))) continue;
    const item = boxed(el);
    if (item) media.push({ ...item, scrimmed: false });
  }
  for (const el of sec.querySelectorAll('*')) {
    const layers = getComputedStyle(el).backgroundImage.split(/,(?![^(]*\))/).map(s => s.trim());
    const firstUrl = layers.findIndex(s => s.startsWith('url('));
    if (firstUrl < 0) continue;
    const item = boxed(el);
    if (item) media.push({ ...item, scrimmed: layers.slice(0, firstUrl).some(s => s.includes('gradient(')) });
  }

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

  // Hit testing skips pointer-events:none, which overlays and scrims usually
  // set. Lift it for the probe and restore it after.
  const lift = document.createElement('style');
  lift.textContent = '.reveal .slides section.present, .reveal .slides section.present *,' +
    '.reveal .slides section.present *::before, .reveal .slides section.present *::after' +
    '{ pointer-events: auto !important; }';
  document.head.appendChild(lift);
  const toClient = (x, y) => [secR.left + x * scale, secR.top + y * scale];
  const stackAt = (x, y) => {
    const out = [];
    for (const hit of document.elementsFromPoint(...toClient(x, y))) {
      if (hit === sec || !sec.contains(hit)) break;
      out.push(register(hit));
    }
    return out;
  };
  const overlapsMedia = line => media.some(({ box: m }) =>
    line.x < m.x + m.w && m.x < line.x + line.w && line.y < m.y + m.h && m.y < line.y + line.h);

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
    // Paint stacks (topmost first) at points along each line that sits over
    // media, so geometry.py can see what lies between the text and the media.
    const samples = [];
    for (const line of lines.filter(overlapsMedia)) {
      for (const f of [0.05, 0.25, 0.5, 0.75, 0.95]) {
        samples.push(stackAt(line.x + line.w * f, line.y + line.h / 2));
      }
    }
    const text = el.textContent.trim().replace(/\s+/g, ' ');
    texts.push({ node: register(el), lines, samples, exempt: exemptFor(el),
                 text: text.slice(0, 60), chars: text.length });
    textEls.push(el);
  }
  lift.remove();

  // Growth test: does this text's absolutely positioned box widen when the
  // text gets longer? Append a long run of words, compare the box width,
  // restore. It answers "is the width decided by content" directly, with the
  // cascade fully applied, where reading width/max-width declarations would
  // have to re-implement specificity, insets and shrink-to-fit.
  texts.forEach((t, i) => {
    const el = textEls[i];
    let root = null;
    for (let n = el; n && n !== sec; n = n.parentElement) {
      const pos = getComputedStyle(n).position;
      if (pos === 'absolute' || pos === 'fixed') { root = n; break; }
    }
    if (!root) { t.grows = null; return; }
    const before = root.getBoundingClientRect().width / scale;
    const extra = document.createTextNode(' ' + 'lengthen the measure '.repeat(30));
    el.appendChild(extra);
    const after = root.getBoundingClientRect().width / scale;
    extra.remove();
    t.grows = r2(after - before);
  });

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
      box: { x: r2((r.left - secR.left) / scale + el.clientLeft),
             y: r2((r.top - secR.top) / scale + el.clientTop),
             w: el.clientWidth, h: el.clientHeight },
    });
  }

  const margin = parseFloat(getComputedStyle(sec).getPropertyValue('--margin-slide'));
  return {
    canvas: { w: config.width, h: config.height }, scale: r2(scale),
    margin: Number.isFinite(margin) ? margin : null,
    elements, texts, markers, media, clipping,
  };
}
