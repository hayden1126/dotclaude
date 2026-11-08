"use client";

import { useEffect, useState } from "react";

const PNG = "iVBORw0KGgoAAAANSUhEUgAAAAMAAAACCAIAAAASFvFNAAAAEElEQVR4nGP4z8DAwMDAAAAK/gH/rCh9VAAAAABJRU5ErkJggg==";

// The standard Next calls: a relative fetch with a stub, one without, and a blob: image preview.
export default function SameOriginPage() {
  const [saved, setSaved] = useState("waiting");
  const [missing, setMissing] = useState("waiting");
  const [preview, setPreview] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/save", { method: "POST", body: "x" })
      .then((r) => r.json())
      .then((j) => setSaved(String(j.ok)))
      .catch((e) => setSaved(`error ${e}`));
    fetch("/api/none")
      .then((r) => setMissing(`status ${r.status}`))
      .catch(() => setMissing("failed"));
    const bytes = Uint8Array.from(atob(PNG), (c) => c.charCodeAt(0));
    setPreview(URL.createObjectURL(new Blob([bytes], { type: "image/png" })));
  }, []);

  return (
    <div>
      <p id="saved">{saved}</p>
      <p id="missing">{missing}</p>
      {preview && <img id="preview" src={preview} alt="preview" />}
    </div>
  );
}
