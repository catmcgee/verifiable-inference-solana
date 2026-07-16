import type { NextConfig } from "next";

// The FastAPI server does not serve CORS headers, so the browser talks
// same-origin to /vinfer/* and Next proxies to the real server. The target
// still comes from NEXT_PUBLIC_VINFER_URL (default: local server).
const VINFER_URL =
  process.env.NEXT_PUBLIC_VINFER_URL ?? "http://127.0.0.1:8477";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/vinfer/:path*", destination: `${VINFER_URL}/:path*` }];
  },
};

export default nextConfig;
