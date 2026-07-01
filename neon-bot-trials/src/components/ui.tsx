'use client';

import Link from 'next/link';
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

/** Small design-system primitives shared across every screen. */

export function Panel({
  children,
  className = '',
  title,
  action,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
  action?: ReactNode;
}) {
  return (
    <section className={`glass-panel ${className}`}>
      {title !== undefined && (
        <header className="flex items-center justify-between border-b border-white/[0.07] px-4 py-2.5">
          <h2 className="hud-label text-neon-cyan/90">{title}</h2>
          {action}
        </header>
      )}
      <div className={title !== undefined ? 'p-4' : ''}>{children}</div>
    </section>
  );
}

type ButtonVariant = 'primary' | 'ghost' | 'danger' | 'accent';

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    'bg-neon-cyan/15 border-neon-cyan/50 text-cyan-100 hover:bg-neon-cyan/25 hover:shadow-neon',
  accent:
    'bg-neon-magenta/15 border-neon-magenta/50 text-fuchsia-100 hover:bg-neon-magenta/25 hover:shadow-neon-pink',
  ghost: 'bg-white/[0.04] border-white/15 text-slate-300 hover:bg-white/[0.09] hover:text-white',
  danger: 'bg-rose-500/10 border-rose-500/40 text-rose-200 hover:bg-rose-500/20',
};

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: 'sm' | 'md' | 'lg' }
>(function Button({ variant = 'primary', size = 'md', className = '', ...props }, ref) {
  const sizeCls =
    size === 'sm' ? 'px-2.5 py-1 text-xs' : size === 'lg' ? 'px-6 py-3 text-base' : 'px-4 py-1.5 text-sm';
  return (
    <button
      ref={ref}
      {...props}
      className={`inline-flex items-center justify-center gap-2 rounded-lg border font-semibold uppercase tracking-wider transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-40 ${sizeCls} ${VARIANT_CLASSES[variant]} ${className}`}
    />
  );
});

export function LinkButton({
  href,
  children,
  variant = 'primary',
  size = 'md',
  className = '',
  ...rest
}: {
  href: string;
  children: ReactNode;
  variant?: ButtonVariant;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
} & Record<`data-${string}`, string>) {
  const sizeCls =
    size === 'sm' ? 'px-2.5 py-1 text-xs' : size === 'lg' ? 'px-6 py-3 text-base' : 'px-4 py-1.5 text-sm';
  return (
    <Link
      href={href}
      {...rest}
      className={`inline-flex items-center justify-center gap-2 rounded-lg border font-semibold uppercase tracking-wider transition-all duration-150 ${sizeCls} ${VARIANT_CLASSES[variant]} ${className}`}
    >
      {children}
    </Link>
  );
}

export function Stat({
  label,
  value,
  unit,
  tone = 'default',
  className = '',
}: {
  label: string;
  value: string | number;
  unit?: string;
  tone?: 'default' | 'good' | 'warn' | 'bad';
  className?: string;
}) {
  const toneCls =
    tone === 'good'
      ? 'text-emerald-300'
      : tone === 'warn'
        ? 'text-amber-300'
        : tone === 'bad'
          ? 'text-rose-300'
          : 'text-slate-100';
  return (
    <div className={`flex flex-col gap-0.5 ${className}`}>
      <span className="hud-label">{label}</span>
      <span className={`mono-value text-lg font-semibold leading-none ${toneCls}`}>
        {value}
        {unit && <span className="ml-1 text-[11px] font-normal text-slate-400">{unit}</span>}
      </span>
    </div>
  );
}

export function Slider({
  label,
  value,
  min,
  max,
  step,
  unit,
  hint,
  onChange,
  disabled,
  format,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit?: string;
  hint?: string;
  onChange: (v: number) => void;
  disabled?: boolean;
  format?: (v: number) => string;
}) {
  const fill = max > min ? (((value - min) / (max - min)) * 100).toFixed(1) : '0';
  return (
    <label className="block" title={hint}>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-xs font-medium text-slate-300">{label}</span>
        <span className="mono-value text-xs text-cyan-200">
          {format ? format(value) : +value.toFixed(2)}
          {unit && <span className="ml-0.5 text-slate-500">{unit}</span>}
        </span>
      </div>
      <input
        type="range"
        className="w-full"
        style={{ ['--fill' as string]: `${fill}%` }}
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      {hint && <p className="mt-1 text-[10px] leading-snug text-slate-500">{hint}</p>}
    </label>
  );
}

export function DifficultyDots({ level }: { level: number }) {
  return (
    <span className="inline-flex items-center gap-1" aria-label={`Difficulty ${level} of 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <span
          key={i}
          className={`h-1.5 w-1.5 rounded-full ${
            i <= level ? 'bg-neon-magenta shadow-neon-pink' : 'bg-white/15'
          }`}
        />
      ))}
    </span>
  );
}

export function Meter({ value, className = '' }: { value: number; className?: string }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  const color = pct > 60 ? 'bg-neon-cyan' : pct > 25 ? 'bg-amber-400' : 'bg-rose-400';
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-white/10 ${className}`}>
      <div
        className={`h-full rounded-full ${color} transition-[width] duration-150`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function Badge({ children, tone = 'cyan' }: { children: ReactNode; tone?: 'cyan' | 'magenta' | 'lime' | 'amber' | 'rose' }) {
  const cls = {
    cyan: 'border-cyan-400/40 bg-cyan-400/10 text-cyan-200',
    magenta: 'border-fuchsia-400/40 bg-fuchsia-400/10 text-fuchsia-200',
    lime: 'border-lime-400/40 bg-lime-400/10 text-lime-200',
    amber: 'border-amber-400/40 bg-amber-400/10 text-amber-200',
    rose: 'border-rose-400/40 bg-rose-400/10 text-rose-200',
  }[tone];
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${cls}`}>
      {children}
    </span>
  );
}
