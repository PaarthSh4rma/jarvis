import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  ...(process.env.JARVIS_DEMO_MODE === "true" ? { distDir: ".next-demo" } : {}),
};

export default nextConfig;
