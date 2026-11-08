"use client";

import Script from "next/script";
import { useEffect, useState } from "react";

const KEY = "analytics-consent";

export default function AnalyticsConsent() {
  const [choice, setChoice] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setChoice(localStorage.getItem(KEY));
    setReady(true);
  }, []);

  function decide(value: "granted" | "denied") {
    localStorage.setItem(KEY, value);
    setChoice(value);
  }

  if (!ready) return null;
  if (choice === "granted") {
    return (
      <>
        <Script src="https://www.googletagmanager.com/gtag/js?id=G-ABC123XYZ" strategy="afterInteractive" />
        <Script id="gtag-init" strategy="afterInteractive">
          {"window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}gtag('js',new Date());gtag('config','G-ABC123XYZ');"}
        </Script>
      </>
    );
  }
  if (choice === "denied") return null;
  return (
    <div role="dialog" aria-label="Cookie preferences">
      <p>We use analytics cookies to understand how Ledgerly is used.</p>
      <button type="button" onClick={() => decide("granted")}>Accept</button>
      <button type="button" onClick={() => decide("denied")}>Reject</button>
    </div>
  );
}
