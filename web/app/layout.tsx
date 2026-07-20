import type { Metadata } from "next";
import "@fontsource/manrope/400.css";
import "@fontsource/manrope/500.css";
import "@fontsource/manrope/600.css";
import "@fontsource/manrope/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://verified-inference.vercel.app"),
  title: "Verified Inference",
  description:
    "Run private AI inference inside an AMD SEV-SNP trusted execution environment and verify the proof on Solana.",
  openGraph: {
    title: "Verified Inference",
    description: "Private execution. Public proof.",
    url: "https://verified-inference.vercel.app",
    siteName: "Verified Inference",
    type: "website",
    images: [
      {
        url: "/social-card.png",
        width: 1200,
        height: 630,
        alt: "Verified Inference — Private execution. Public proof.",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Verified Inference",
    description: "Private execution. Public proof.",
    images: ["/social-card.png"],
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
