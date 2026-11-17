"use client";

import { useEffect } from "react";

// A beacon is fire-and-forget: nothing in the page waits for it.
export default function BeaconPage() {
  useEffect(() => {
    navigator.sendBeacon("https://metrics.example/hit", "x");
  }, []);
  return <p id="ok">ok</p>;
}
