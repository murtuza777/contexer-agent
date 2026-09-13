import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Contexer | Autonomous Engineering Agent",
  description:
    "Contexer turns your intent into an engineering plan, executes work through coding agents, observes the running application, verifies the result, and fixes what doesn't work.",
  keywords: [
    "autonomous agent",
    "coding agent",
    "software engineering agent",
    "developer tools",
    "runtime verification",
    "self-repair",
    "Playwright verification",
    "OpenCode adapter",
    "CLI developer tools",
  ],
  authors: [{ name: "Contexer Team" }],
  creator: "Contexer",
  metadataBase: new URL("https://contexer.dev"),
  openGraph: {
    type: "website",
    locale: "en_US",
    url: "https://contexer.dev",
    siteName: "Contexer",
    title: "Contexer | Autonomous Engineering Agent",
    description:
      "Tell Contexer what you want built. It plans, builds, tests, observes, and fixes it.",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
        alt: "Contexer Autonomous Engineering Agent",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Contexer | Autonomous Engineering Agent",
    description:
      "Tell Contexer what you want built. It plans, builds, tests, observes, and fixes it.",
    images: ["/og-image.png"],
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} dark antialiased h-full`}
    >
      <body className="min-h-full flex flex-col bg-[#08090d] text-[#f4f4f5] selection:bg-cyan-500/20 selection:text-cyan-300">
        {children}
      </body>
    </html>
  );
}
