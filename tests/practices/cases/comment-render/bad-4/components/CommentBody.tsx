"use client";

import { useMemo } from "react";

function clean(body: string): string {
  const doc = new DOMParser().parseFromString(body, "text/html");
  for (const el of Array.from(doc.body.querySelectorAll("*"))) {
    for (const attr of Array.from(el.attributes)) {
      if (attr.name.toLowerCase().startsWith("on")) el.removeAttribute(attr.name);
      if (attr.name.toLowerCase() === "href" && !/^https?:/i.test(attr.value)) el.removeAttribute(attr.name);
    }
  }
  return doc.body.innerHTML;
}

export default function CommentBody({ body }: { body: string }) {
  const html = useMemo(() => clean(body), [body]);
  return <div dangerouslySetInnerHTML={{ __html: html }} />;
}
