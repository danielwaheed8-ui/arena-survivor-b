import type { Metadata, Viewport } from 'next';
import { NavBar } from '@/components/NavBar';
import './globals.css';

export const metadata: Metadata = {
  title: 'Neon Bot Trials — Robot Parkour Lab',
  description:
    'Design modular robots, tune their motors, and put them through physics-driven neon obstacle courses.',
};

export const viewport: Viewport = {
  themeColor: '#05060f',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen antialiased">
        <NavBar />
        <main>{children}</main>
      </body>
    </html>
  );
}
