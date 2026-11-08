"use client";

import "./main.css";
import hero from "./hero.png";
import icon from "./icon.svg";
import logo from "./logo.gif";

export default function AssetsPage() {
  return (
    <main>
      <img id="hero" src={hero.src} width={hero.width} height={hero.height} alt="" />
      <p id="dims">{`${hero.width}x${hero.height} ${logo.width}x${logo.height} ${icon.width}x${icon.height}`}</p>
      <div id="base" className="base">base</div>
    </main>
  );
}
