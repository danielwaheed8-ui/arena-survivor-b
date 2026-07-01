import Link from 'next/link';
import { HeroSim } from '@/components/HeroSim';
import { LinkButton } from '@/components/ui';
import { ARENAS } from '@/lib/arenas';

const FEATURES = [
  {
    title: 'Modular Builder',
    body: 'Assemble bots from wheels, piston legs, shock springs, gyros, thrusters and sensors. Every part is tunable.',
    icon: '⬡',
  },
  {
    title: 'Real Physics',
    body: 'Rigid bodies, joints, motors, springs, wind and low-gravity cells — every run is simulated, never animated.',
    icon: '∿',
  },
  {
    title: 'Six Trial Arenas',
    body: 'From a flat calibration strip to the Neon Gauntlet: ramps, gaps, tilting planks, gusts and lift platforms.',
    icon: '⌬',
  },
  {
    title: 'Replay & Ranking',
    body: 'Every run is scored on time, stability and energy. Save the best, scrub the replay, beat your record.',
    icon: '◍',
  },
];

export default function LandingPage() {
  return (
    <div className="mx-auto max-w-7xl px-4 pb-20 sm:px-6">
      {/* Hero */}
      <section className="relative mt-6 overflow-hidden rounded-2xl border border-white/10 shadow-neon">
        <HeroSim className="h-[420px] w-full sm:h-[520px]" />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-void via-void/40 to-transparent" />
        <div className="absolute inset-x-0 bottom-0 p-6 sm:p-10">
          <p className="hud-label mb-2 text-neon-cyan" data-testid="hero-kicker">
            Robotics Proving Grounds · Live Simulation
          </p>
          <h1 className="neon-heading max-w-3xl text-3xl leading-tight text-white sm:text-5xl">
            Build a bot.
            <br />
            Survive the <span className="text-neon-cyan">trials</span>.
          </h1>
          <p className="mt-3 max-w-xl text-sm leading-relaxed text-slate-300 sm:text-base">
            A physics-driven parkour lab for modular robots. Design, tune, launch — then watch
            your machine earn its score across six neon test courses.
          </p>
          <div className="pointer-events-auto mt-6 flex flex-wrap gap-3">
            <LinkButton href="/simulate" size="lg" data-testid="cta-simulate">
              ▶ Start Simulation
            </LinkButton>
            <LinkButton href="/builder" variant="accent" size="lg">
              ⬡ Robot Builder
            </LinkButton>
            <LinkButton href="/arenas" variant="ghost" size="lg">
              Select Arena
            </LinkButton>
          </div>
        </div>
      </section>

      {/* Feature grid */}
      <section className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {FEATURES.map((f, i) => (
          <div
            key={f.title}
            className="glass-panel animate-fade-up p-5"
            style={{ animationDelay: `${i * 80}ms` }}
          >
            <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-lg border border-neon-cyan/40 bg-neon-cyan/10 text-lg text-neon-cyan shadow-neon">
              {f.icon}
            </div>
            <h3 className="text-sm font-semibold uppercase tracking-wider text-white">{f.title}</h3>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{f.body}</p>
          </div>
        ))}
      </section>

      {/* Arena strip */}
      <section className="mt-12">
        <div className="mb-4 flex items-end justify-between">
          <div>
            <p className="hud-label text-neon-magenta">Certification Track</p>
            <h2 className="neon-heading mt-1 text-xl text-white">The Six Trials</h2>
          </div>
          <LinkButton href="/arenas" variant="ghost" size="sm">
            View all →
          </LinkButton>
        </div>
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {ARENAS.map((a, i) => (
            <Link
              key={a.id}
              href={`/simulate?arena=${a.id}`}
              className="glass-panel group p-4 transition-all hover:border-neon-cyan/40 hover:shadow-neon"
            >
              <span className="mono-value text-[10px] text-slate-500">
                {String(i + 1).padStart(2, '0')}
              </span>
              <h3 className="mt-1 text-sm font-semibold text-white group-hover:text-cyan-200">
                {a.name}
              </h3>
              <p className="mt-1 text-[11px] leading-snug text-slate-500">{a.tagline}</p>
            </Link>
          ))}
        </div>
      </section>

      <footer className="mt-16 border-t border-white/[0.06] pt-6 text-center text-[11px] text-slate-600">
        Neon Bot Trials — a fictional physics sandbox. All robots are imaginary; no real-world
        hardware instructions inside.
      </footer>
    </div>
  );
}
