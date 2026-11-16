"use client";

import Image from "next/image";
import lossless from "./lossless.webp";
import lossy from "./lossy.webp";
import photo from "./photo.jpg";
import progressive from "./progressive.jpg";
import sized from "./sized.svg";
import viewbox from "./viewbox.svg";

const dims = (i: { width: number; height: number }) => `${i.width}x${i.height}`;

export default function DimsPage() {
  return (
    <main>
      <Image id="photo" src={photo} alt="photo" priority />
      <p id="dims">{[photo, progressive, lossy, lossless, viewbox, sized].map(dims).join(" ")}</p>
    </main>
  );
}
