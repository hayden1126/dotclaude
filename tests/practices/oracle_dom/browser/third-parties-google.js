// @next/third-parties/google in the browser bundle: GoogleAnalytics and GoogleTagManager insert
// Google's real script when they mount, so its request shows in requests(), as the real
// components do through next/script. Once each per id. sendGAEvent and sendGTMEvent push to the
// data layer.
import { useEffect } from "react";

const inserted = new Set();

function insert(src) {
  if (inserted.has(src)) return;
  inserted.add(src);
  const el = document.createElement("script");
  el.async = true;
  el.src = src;
  document.head.appendChild(el);
}

export function GoogleAnalytics({ gaId, dataLayerName = "dataLayer" }) {
  useEffect(() => {
    window[dataLayerName] = window[dataLayerName] || [];
    insert(`https://www.googletagmanager.com/gtag/js?id=${gaId}${dataLayerName === "dataLayer" ? "" : `&l=${dataLayerName}`}`);
  }, [gaId, dataLayerName]);
  return null;
}

export function GoogleTagManager({ gtmId, dataLayerName = "dataLayer" }) {
  useEffect(() => {
    window[dataLayerName] = window[dataLayerName] || [];
    insert(`https://www.googletagmanager.com/gtm.js?id=${gtmId}${dataLayerName === "dataLayer" ? "" : `&l=${dataLayerName}`}`);
  }, [gtmId, dataLayerName]);
  return null;
}

export function sendGAEvent(...args) {
  (window.dataLayer = window.dataLayer || []).push(args);
}

export function sendGTMEvent(data) {
  (window.dataLayer = window.dataLayer || []).push(data);
}
