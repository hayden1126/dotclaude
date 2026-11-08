import type { ReactNode } from "react";
import Script from "next/script";

export const metadata = { title: "Ledgerly", description: "Invoices for small studios" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <nav>
          <a href="/">Ledgerly</a> <a href="/chat">Assistant</a> <a href="/settings">Settings</a>
        </nav>
        {children}
        <Script src="https://www.googletagmanager.com/gtag/js?id=G-ABC123XYZ" strategy="afterInteractive" />
        <Script id="gtag-init" strategy="afterInteractive">
          {"window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}gtag('js',new Date());gtag('config','G-ABC123XYZ');"}
        </Script>
      </body>
    </html>
  );
}
