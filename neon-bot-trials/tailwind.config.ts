import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        void: '#05060f',
        panel: '#0b0e1e',
        'panel-2': '#101430',
        neon: {
          cyan: '#22d3ee',
          magenta: '#e879f9',
          lime: '#a3e635',
          amber: '#fbbf24',
          blue: '#60a5fa',
        },
      },
      fontFamily: {
        display: ['var(--font-display)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        neon: '0 0 12px rgba(34, 211, 238, 0.45), 0 0 32px rgba(34, 211, 238, 0.12)',
        'neon-pink': '0 0 12px rgba(232, 121, 249, 0.45), 0 0 32px rgba(232, 121, 249, 0.12)',
        'panel-inset': 'inset 0 1px 0 rgba(255,255,255,0.06)',
      },
      keyframes: {
        'pulse-glow': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.55' },
        },
        'scan': {
          '0%': { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(100%)' },
        },
      },
      animation: {
        'pulse-glow': 'pulse-glow 2.4s ease-in-out infinite',
        scan: 'scan 7s linear infinite',
      },
    },
  },
  plugins: [],
};

export default config;
