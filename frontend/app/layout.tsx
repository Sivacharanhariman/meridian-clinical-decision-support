import type { Metadata } from "next";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "./globals.css";
export const metadata: Metadata = { title: "Meridian | Patient Navigation & Triage", description: "Synthetic nurse-facing patient navigation and triage copilot prototype. Human-led care with validated evidence." };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en"><body>{children}</body></html>; }
