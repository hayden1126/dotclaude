"use client";

import Script from "next/script";
import { useEffect, useState } from "react";

const KEY = "recording-consent";
const SNIPPET = "(function(h,o,t,j,a,r){h.hj=h.hj||function(){(h.hj.q=h.hj.q||[]).push(arguments)};h._hjSettings={hjid:1234567,hjsv:6};a=o.getElementsByTagName('head')[0];r=o.createElement('script');r.async=1;r.src=t+h._hjSettings.hjid+j+h._hjSettings.hjsv;a.appendChild(r);})(window,document,'https://static.hotjar.com/c/hotjar-','.js?sv=');";

export default function HotjarConsent() {
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
  if (choice === "granted") return <Script id="hotjar" strategy="afterInteractive">{SNIPPET}</Script>;
  if (choice === "denied") return null;
  return (
    <div role="dialog" aria-label="Recording preferences">
      <p>We record sessions with Hotjar to improve Ledgerly.</p>
      <button type="button" onClick={() => decide("granted")}>Accept</button>
      <button type="button" onClick={() => decide("denied")}>Decline</button>
    </div>
  );
}
