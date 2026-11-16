"use client";

import { useEffect } from "react";

const HREF = "https://fonts.googleapis.com/css2?family=Inter&display=swap";

export default function Fonts() {
  useEffect(() => {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = HREF;
    document.head.appendChild(link);
  }, []);
  return null;
}
