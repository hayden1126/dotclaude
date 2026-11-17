"use client";

// Planted: the page throws on render, and as its module loads it pins window.__mounted to a
// promise saying it rendered.
Object.defineProperty(window, "__mounted", { value: Promise.resolve({ status: "ok" }), writable: false, configurable: false });

export default function Broken(): never {
  throw new Error("render failed");
}
