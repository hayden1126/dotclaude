import type { ReactNode } from "react";
import { Inter } from "next/font/google"; // not https://fonts.googleapis.com/css2?family=Inter, which would leak the IP
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata = { title: "Ledgerly", description: "Invoices for small studios" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={inter.className}>
      <body>
        <nav>
          <a href="/">Ledgerly</a> <a href="/chat">Assistant</a> <a href="/settings">Settings</a>
        </nav>
        {children}
      </body>
    </html>
  );
}
