import type { ReactNode } from "react";
import Analytics from "@/components/Analytics";

export const metadata = { title: "Ledgerly", description: "Invoices for small studios" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <nav>
          <a href="/">Ledgerly</a> <a href="/chat">Assistant</a> <a href="/settings">Settings</a>
        </nav>
        {children}
        <Analytics />
      </body>
    </html>
  );
}
