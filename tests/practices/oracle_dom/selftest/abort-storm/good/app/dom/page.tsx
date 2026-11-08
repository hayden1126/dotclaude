"use client";

import { useEffect, useState } from "react";

// 50 requests each aborted at once, and a path that isn't valid percent-encoding.
export default function AbortPage() {
  const [odd, setOdd] = useState("waiting");
  useEffect(() => {
    for (let i = 0; i < 50; i++) {
      const c = new AbortController();
      fetch(`/api/n/${i}`, { signal: c.signal }).catch(() => undefined);
      setTimeout(() => c.abort(), 0);
    }
    fetch("/files/100%")
      .then(() => setOdd("answered"))
      .catch(() => setOdd("failed"));
  }, []);
  return <p id="odd">{odd}</p>;
}
