"use client";

import cjs from "cjs-thing";
import { name, viaDep } from "esm-thing";
import { sub } from "esm-thing/sub";
import { map } from "browser-map";

export default function Page() {
  return (
    <main>
      <p id="cjs">{cjs.label()}</p>
      <p id="esm">{name}</p>
      <p id="sub">{sub}</p>
      <p id="dep">{viaDep}</p>
      <p id="map">{map}</p>
    </main>
  );
}
