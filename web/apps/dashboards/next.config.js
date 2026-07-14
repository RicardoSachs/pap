
// web/apps/dashboards/next.config.js
// ---------------------------------------------------------------------------
// Static export config. `output: 'export'` emits a fully static bundle to out/
// with NO Node runtime needed -- FastAPI's StaticFiles serves it on the i7 server.
//   - images.unoptimized: the default optimizer needs a Node runtime; off here.
//   - API base: pages use relative /api URLs in production (same origin as
//     FastAPI). In dev, NEXT_PUBLIC_API_BASE (see .env.development) points at
//     the uvicorn server on :8000; CORS there allows :3000.
// ---------------------------------------------------------------------------
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  images: { unoptimized: true },
  trailingSlash: true,
};

module.exports = nextConfig;

