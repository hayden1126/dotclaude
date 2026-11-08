"use client";

import { useEffect } from "react";

export default function Analytics() {
  useEffect(() => {
    const script = document.createElement("script");
    script.async = true;
    script.src = "https://www.googletagmanager.com/gtag/js?id=G-ABC123XYZ";
    document.head.appendChild(script);
  }, []);
  return null;
}
