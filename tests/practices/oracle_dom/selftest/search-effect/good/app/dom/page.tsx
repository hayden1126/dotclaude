"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

// An effect keyed on the search params: it runs once unless the hook hands out a new object.
export default function SearchPage() {
  const sp = useSearchParams();
  const [runs, setRuns] = useState(0);
  useEffect(() => {
    fetch(`https://api.example/search?${sp.toString()}`);
    setRuns((n) => n + 1);
  }, [sp]);
  return <p id="runs">{runs}</p>;
}
