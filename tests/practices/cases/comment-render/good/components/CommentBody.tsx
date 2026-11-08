"use client";

import { createElement, Fragment, useMemo, type ReactNode } from "react";

const ALLOWED = new Set(["b", "strong", "i", "em", "p", "br", "ul", "ol", "li", "a"]);

function safeHref(value: string | null): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value, "https://placeholder.invalid/");
    return url.protocol === "http:" || url.protocol === "https:" || url.protocol === "mailto:" ? value : undefined;
  } catch {
    return undefined;
  }
}

function toReact(node: ChildNode, key: number): ReactNode {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent;
  if (node.nodeType !== Node.ELEMENT_NODE) return null;
  const element = node as Element;
  const tag = element.tagName.toLowerCase();
  const children = Array.from(element.childNodes).map(toReact);
  if (!ALLOWED.has(tag)) return <Fragment key={key}>{children}</Fragment>;
  if (tag === "a") {
    const href = safeHref(element.getAttribute("href"));
    return href ? <a key={key} href={href} rel="noopener noreferrer">{children}</a> : <Fragment key={key}>{children}</Fragment>;
  }
  return createElement(tag, { key }, children.length ? children : undefined);
}

export default function CommentBody({ body }: { body: string }) {
  const content = useMemo(() => {
    const doc = new DOMParser().parseFromString(body, "text/html");
    return Array.from(doc.body.childNodes).map(toReact);
  }, [body]);
  return <div>{content}</div>;
}
