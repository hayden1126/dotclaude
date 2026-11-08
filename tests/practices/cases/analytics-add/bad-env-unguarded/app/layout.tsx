import type { ReactNode } from "react";
import Script from "next/script";

const id = process.env.NEXT_PUBLIC_GA_ID;

export const metadata = { title: "Ledgerly", description: "Invoices for small studios" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <nav>
          <a href="/">Ledgerly</a> <a href="/chat">Assistant</a> <a href="/settings">Settings</a>
        </nav>
        {children}
        <Script src={`https://www.googletagmanager.com/gtag/js?id=${id}`} strategy="afterInteractive" />
      </body>
    </html>
  );
}
