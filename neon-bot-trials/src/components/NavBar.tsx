'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const LINKS = [
  { href: '/arenas', label: 'Arenas' },
  { href: '/builder', label: 'Builder' },
  { href: '/simulate', label: 'Simulate' },
  { href: '/replays', label: 'Replays' },
  { href: '/robots', label: 'Garage' },
];

export function NavBar() {
  const pathname = usePathname();
  return (
    <nav className="app-nav sticky top-0 z-40 border-b border-white/[0.07] bg-void/80 backdrop-blur-lg">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-3 sm:px-6">
        <Link href="/" className="group flex shrink-0 items-center gap-2.5">
          <span className="relative flex h-7 w-7 items-center justify-center rounded-md border border-neon-cyan/60 bg-neon-cyan/10 shadow-neon">
            <span className="h-2 w-2 rounded-full bg-neon-cyan animate-pulse-glow" />
          </span>
          <span className="neon-heading hidden text-sm text-white transition-colors group-hover:text-cyan-200 md:inline">
            Neon Bot Trials
          </span>
        </Link>
        <div className="flex min-w-0 items-center gap-0.5 sm:gap-2">
          {LINKS.map((l) => {
            const active = pathname?.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={`rounded-md px-1.5 py-1.5 text-[11px] font-semibold uppercase tracking-wide transition-colors sm:px-3 sm:text-xs sm:tracking-wider ${
                  active
                    ? 'bg-neon-cyan/15 text-cyan-200 shadow-neon'
                    : 'text-slate-400 hover:bg-white/[0.06] hover:text-white'
                }`}
              >
                {l.label}
              </Link>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
