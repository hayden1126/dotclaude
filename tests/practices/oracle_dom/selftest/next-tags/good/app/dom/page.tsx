"use client";

import Image from "next/image";
import Link from "next/link";
import Script from "next/script";
import { Inter } from "next/font/google";

const inter = Inter({ subsets: ["latin"] });

export default function Landing() {
  return (
    <main className={inter.className}>
      <Image src="/hero.png" alt="Hero" width={640} height={320} />
      <Image src="/logo.png" alt="Logo" width={64} height={64} priority />
      <Link href={{ pathname: "/pricing", query: { plan: "pro" } }}>Pricing</Link>
      <Script src="https://tracker.example/t.js" strategy="afterInteractive" async />
      <Script src="https://widgets.example/chat.js" strategy="lazyOnload" />
    </main>
  );
}
