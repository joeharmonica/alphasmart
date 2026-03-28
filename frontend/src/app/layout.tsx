import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AlphaSMART | Backtest Explorer",
  description: "Institutional-grade algorithmic trading dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark h-full">
      <body className="min-h-full flex flex-col bg-[#101419] text-[#e0e2ea]">
        {children}
      </body>
    </html>
  );
}
