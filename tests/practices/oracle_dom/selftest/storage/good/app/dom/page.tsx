"use client";

import { useState } from "react";

// Read at the first render: a stored consent decides whether a tracker ever loads.
export default function ConsentPage() {
  const [consent] = useState(() => localStorage.getItem("consent"));
  const [draft] = useState(() => sessionStorage.getItem("draft"));
  return (
    <div>
      <p id="consent">{String(consent)}</p>
      <p id="draft">{String(draft)}</p>
    </div>
  );
}
