import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { AutoScan } from "@/components/AutoScan";
import { Providers } from "./providers";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "KALSHI-EV // SCANNER",
  description: "Live multi-book EV scanner for Kalshi player-prop markets",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`dark ${geistSans.variable} ${geistMono.variable}`}>
      <body className="antialiased">
        <Providers>
          <AutoScan />
          {children}
        </Providers>
      </body>
    </html>
  );
}
