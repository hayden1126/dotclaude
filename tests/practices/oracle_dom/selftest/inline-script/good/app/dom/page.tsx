"use client";

import { useEffect, useState } from "react";

const once = (name: string) => ({ __html: `window.${name} = (window.${name} || 0) + 1;` });

export default function Page() {
  const [later, setLater] = useState(false);

  useEffect(() => {
    const el = document.createElement("script");
    el.textContent = "window.ranEffect = (window.ranEffect || 0) + 1;";
    document.body.appendChild(el);
  }, []);

  return (
    <main>
      <script dangerouslySetInnerHTML={once("ranFirst")} />
      {later && <script dangerouslySetInnerHTML={once("ranLater")} />}
      <button type="button" onClick={() => setLater(true)}>More</button>
    </main>
  );
}
