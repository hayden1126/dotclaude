"use client";

import { useEffect } from "react";

export default function PageView() {
  useEffect(() => {
    (window as unknown as { gtag: (...args: unknown[]) => void }).gtag("event", "page_view");
  }, []);
  return null;
}
