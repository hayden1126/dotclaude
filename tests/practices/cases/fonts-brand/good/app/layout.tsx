import type { ReactNode } from "react";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata = { title: "Ledgerly", description: "Invoices for small studios" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body>
        <nav>
          <a href="/">Ledgerly</a> <a href="/chat">Assistant</a> <a href="/settings">Settings</a>
        </nav>
        {children}
      </body>
    </html>
  );
}
