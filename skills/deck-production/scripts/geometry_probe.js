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

  // Specified (not computed) values. getComputedStyle resolves `width: auto`
  // and an absolute element's `left: auto` to used pixels, which hides exactly
  // what the bounded-width rule needs to know. Inline style first, then the
  // last matching style rule in document order. Specificity is not weighed:
  // good enough for deck CSS, where the slide-scoped rule also comes last.
  const styleRules = [];
  const collect = list => {
    for (const rule of list) {
      if (rule instanceof CSSStyleRule) styleRules.push(rule);
      else if (rule.cssRules && (!rule.media || matchMedia(rule.media.mediaText).matches)) {
        collect(rule.cssRules);
      }
    }
  };
  for (const sheet of document.styleSheets) {
    try { collect(sheet.cssRules); } catch (e) { /* cross-origin sheet: unreadable */ }
  }
  const specified = (el, prop) => {
    const inline = el.style ? el.style.getPropertyValue(prop) : '';
    if (inline) return inline.trim();
    let value = '';
    for (const rule of styleRules) {
      const v = rule.style.getPropertyValue(prop);
      if (!v) continue;
      try { if (el.matches(rule.selectorText)) value = v; } catch (e) { /* bad selector */ }
    }
    return (value || 'auto').trim();
  };

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

  // The node table. Ancestors register first, so `parent` always resolves;
  // the section itself is the implicit root (parent null).
  const ids = new Map();
  const elements = [];
  const register = el => {
    if (el === sec) return null;
    if (ids.has(el)) return ids.get(el);
    const parent = register(el.parentElement);
    const cs = getComputedStyle(el);
    const id = elements.length;
    ids.set(el, id);
    elements.push({
      parent, token: token(el), tag: el.localName,
      position: cs.position, display: cs.display,
      maxWidth: cs.maxWidth, width: specified(el, 'width'),
      left: specified(el, 'left'), right: specified(el, 'right'),
      textShadow: cs.textShadow, background: cs.backgroundColor,
      backgroundImage: cs.backgroundImage !== 'none',
      box: norm(el.getBoundingClientRect()),
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
  const texts = [];
  for (const [el, nodes] of byElement) {
    if (hidden(el)) continue;
    const lines = [];
    for (const node of nodes) {
      const range = document.createRange();
      range.selectNodeContents(node);
      for (const r of range.getClientRects()) if (visibleRect(r)) lines.push(norm(r));
    }
    if (!lines.length) continue;
    texts.push({ node: register(el), lines, exempt: exemptFor(el),
                 text: el.textContent.trim().replace(/\s+/g, ' ').slice(0, 60) });
  }

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

  // Media: an inline icon svg sitting in a run of text is part of the text,
  // and an svg nested in an svg is part of its parent.
  const hasDirectText = el => [...el.childNodes].some(
    n => n.nodeType === Node.TEXT_NODE && n.nodeValue.trim());
  const media = [];
  for (const el of sec.querySelectorAll('img, video, canvas, svg')) {
    if (el.localName === 'svg' && (el.parentElement.closest('svg') || hasDirectText(el.parentElement))) {
      continue;
    }
    const item = boxed(el);
    if (item) media.push(item);
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
