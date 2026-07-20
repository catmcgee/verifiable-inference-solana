import type { NextConfig } from "next";

// The FastAPI server does not serve CORS headers, so the browser talks
// same-origin to /vinfer/* and Next proxies to the real server. The target
// is server-only so the origin is not embedded in the browser bundle.
const VINFER_URL =
  process.env.VINFER_ORIGIN_URL ?? "http://127.0.0.1:8477";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/vinfer/:path*", destination: `${VINFER_URL}/:path*` },
      {
        source: "/vinfer-a/:path*",
        destination: `${VINFER_URL}/vinfer-a/:path*`,
      },
      {
        source: "/vinfer-c/:path*",
        destination: `${VINFER_URL}/vinfer-c/:path*`,
      },
    ];
  },
};

export default nextConfig;
