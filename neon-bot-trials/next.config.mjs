/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  eslint: {
    dirs: ['src'],
  },
  // Every route is statically prerendered, so the app can ship as a pure
  // static export for hosting (Vercel builds with NEXT_OUTPUT=export).
  // Local `next dev` / `next start` keep the default server output.
  ...(process.env.NEXT_OUTPUT === 'export'
    ? { output: 'export', trailingSlash: true }
    : {}),
};

export default nextConfig;
