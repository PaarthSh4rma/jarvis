import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./demo",
  testMatch: "jarvis-demo.spec.ts",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  outputDir: "demo-output/playwright",
  reporter: "line",
  use: {
    baseURL: "http://localhost:3100",
    viewport: { width: 1280, height: 720 },
    colorScheme: "dark",
    video: { mode: "on", size: { width: 1280, height: 720 } },
  },
  webServer: [
    {
      command: "npm run demo:setup && npm run demo:api",
      url: "http://localhost:8100/health",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "npm run demo:web",
      url: "http://localhost:3100",
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
