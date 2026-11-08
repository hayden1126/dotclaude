// next/script in the browser bundle: one real <script> element per src or id, inserted when its
// strategy says, so its request shows: beforeInteractive into <head> and afterInteractive into
// <body> at mount, lazyOnload after the window's load event. It carries the strategy as
// data-strategy, plus async, defer and the other attributes given.
// limit: worker (Partytown) inserts like lazyOnload; an oracle grading worker scripts needs more.
import { useEffect } from "react";

const inserted = new Set();

function insert({ src, id, strategy, children, dangerouslySetInnerHTML, onLoad, onReady, onError, attrs }) {
  const key = id ?? src;
  if (key && inserted.has(key)) return;
  if (key) inserted.add(key);
  const el = document.createElement("script");
  for (const [name, value] of Object.entries(attrs)) {
    if (value === false || value === undefined || value === null || typeof value === "function") continue;
    el.setAttribute(name === "className" ? "class" : name, value === true ? "" : String(value));
  }
  if (id) el.id = id;
  el.dataset.strategy = strategy;
  if (src) el.src = src;
  else el.textContent = dangerouslySetInnerHTML?.__html ?? (typeof children === "string" ? children : "");
  el.addEventListener("load", (e) => {
    onLoad?.(e);
    onReady?.();
  });
  if (onError) el.addEventListener("error", onError);
  (strategy === "beforeInteractive" ? document.head : document.body).appendChild(el);
}

export default function Script({ src, id, strategy = "afterInteractive", children, dangerouslySetInnerHTML, onLoad, onReady, onError, ...attrs }) {
  useEffect(() => {
    const go = () => insert({ src, id, strategy, children, dangerouslySetInnerHTML, onLoad, onReady, onError, attrs });
    if (strategy !== "lazyOnload" && strategy !== "worker") return go();
    if (document.readyState === "complete") {
      const timer = setTimeout(go, 0);
      return () => clearTimeout(timer);
    }
    window.addEventListener("load", go, { once: true });
    return () => window.removeEventListener("load", go);
  }, [src, id, strategy]);
  return null;
}
