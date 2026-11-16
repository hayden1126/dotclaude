"use client";

import { useEffect, useState } from "react";

// Cross-origin with cookies and a custom header: a preflight, then a credentialed response.
export default function CorsPage() {
  const [state, setState] = useState("waiting");
  useEffect(() => {
    fetch("https://api.example/me", { credentials: "include", headers: { Authorization: "Bearer x" } })
      .then((r) => r.json())
      .then((j) => setState(String(j.name)))
      .catch((e) => setState(`error ${e}`));
    fetch("https://api.example/options", { method: "OPTIONS" }).catch(() => undefined);
  }, []);
  return <p id="state">{state}</p>;
}
