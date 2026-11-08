"use client";

import { useEffect, useState } from "react";

// Fetches on mount; offline, the request fails and the page says so.
export default function StatusPage() {
  const [state, setState] = useState("loading");

  useEffect(() => {
    fetch("https://example.com/x")
      .then((r) => setState(r.ok ? "ok" : "bad"))
      .catch(() => setState("offline"));
  }, []);

  return <p id="state">{state}</p>;
}
