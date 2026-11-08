// UX-12: motion goes on transform and opacity, not on layout properties, and honours the user's
// reduced-motion setting. Source files are read comments-stripped; the panel's computed
// transition-property covers a `transition: all` a file scan can't resolve: all passes only if
// no layout property actually changes between open and closed.
import { Missing } from "../../oracle_lib.mjs";
import { domOracle, openDom, sourceFiles } from "../../oracle_dom/oracle_dom.mjs";

const LAYOUT = /^(left|right|top|bottom|width|height|inset|margin(-[a-z-]+)?)$/;
const LAYOUT_PROPS = ["left", "right", "top", "bottom", "width", "height", "margin-left", "margin-right", "margin-top", "margin-bottom"];
const PANEL = "nav";

const strip = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

// Property names a declaration's value mentions, for a transition shorthand or transition-property.
function transitionedLayout(source) {
  const hits = [];
  for (const [, value] of source.matchAll(/transition(?:-property|Property)?\s*[:=]\s*\{?\s*([^;}\n]+)/g)) {
    for (const part of value.replace(/\([^)]*\)/g, "").replace(/["'`]/g, " ").split(",")) {
      for (const token of part.trim().split(/\s+/)) if (LAYOUT.test(token)) hits.push(token);
    }
  }
  return hits;
}

function keyframedLayout(source) {
  const hits = [];
  for (const match of source.matchAll(/@keyframes\s+[\w-]+\s*\{/g)) {
    let depth = 1;
    let end = match.index + match[0].length;
    while (depth > 0 && end < source.length) {
      depth += source[end] === "{" ? 1 : source[end] === "}" ? -1 : 0;
      end++;
    }
    const body = source.slice(match.index + match[0].length, end);
    for (const [, prop] of body.matchAll(/([a-z-]+)\s*:/g)) if (LAYOUT.test(prop)) hits.push(prop);
  }
  return hits;
}

function motionLibLayout(source) {
  return [...source.matchAll(/animate=\{\{([^}]*)\}\}/g)].flatMap(([, body]) =>
    [...body.matchAll(/([a-zA-Z]+)\s*:/g)].map(([, prop]) => prop).filter((p) => LAYOUT.test(p) || /^margin[A-Z]/.test(p))); // practices-allow: SEC-04 body is a keyframes block read from source, no request
}

async function panelState(dom) {
  return dom.call(`(sel, props) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return {
      x: r.x, y: r.y, w: r.width, h: r.height, display: s.display, visibility: s.visibility, opacity: s.opacity,
      transitionProperty: s.transitionProperty, transitionDuration: s.transitionDuration,
      layout: Object.fromEntries(props.map((p) => [p, s.getPropertyValue(p)])),
    };
  }`, PANEL, LAYOUT_PROPS);
}

// The computed properties a panel actually transitions: those with a duration above 0.
function animated({ transitionProperty, transitionDuration }) {
  const durations = transitionDuration.split(",").map((d) => parseFloat(d));
  return transitionProperty.split(",").map((p) => p.trim()).filter((_, i) => durations[i % durations.length] > 0);
}

await domOracle(async (t) => {
  const files = sourceFiles().map(([name, text]) => [name, strip(text)]);
  const joined = files.map(([, text]) => text).join("\n");
  if (!/transition|animation|@keyframes|motion\.|AnimatePresence/i.test(joined)) throw new Missing("nothing in the project animates the sidebar");

  const dom = await openDom(t, import.meta.url, { entry: "app/shell/page.tsx" });
  if (!dom) return;
  try {
    await dom.settle();
    const menu = await dom.byText(/menu|sidebar|toggle/i, { tag: "button, [role=button]" });
    if (!menu) throw new Missing("the page has no menu button");
    const before = await panelState(dom);
    await dom.click(menu);
    await dom.settle();
    await dom.wait(800); // past the transition, so the end state reads
    const after = await panelState(dom);
    const moved = before === null || after === null
      ? before !== after
      : before.x !== after.x || before.y !== after.y || before.w !== after.w || before.h !== after.h || before.display !== after.display || before.visibility !== after.visibility || before.opacity !== after.opacity;
    t.functional("the menu button changes the panel's position or presence", moved, `before ${JSON.stringify(before)} after ${JSON.stringify(after)}`);

    const sourceHits = [...new Set(files.flatMap(([, text]) => [...transitionedLayout(text), ...keyframedLayout(text), ...motionLibLayout(text)]))];
    const seen = [before, after].filter(Boolean).flatMap(animated);
    const computedHits = [...new Set(seen.filter((p) => LAYOUT.test(p)))];
    let allHits = [];
    if (seen.includes("all") && before && after) allHits = LAYOUT_PROPS.filter((p) => before.layout[p] !== after.layout[p]);
    const hits = [...sourceHits, ...computedHits, ...allHits];
    t.security("no transition or keyframe animates a layout property", hits.length === 0, `animates: ${hits.join(", ")}`);
    t.security("the source honours reduced motion", /prefers-reduced-motion|useReducedMotion|reducedMotion/.test(joined), "no prefers-reduced-motion or useReducedMotion in the source");
  } finally {
    await dom.close();
  }
});
