import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  reporter: "line",
  use: {
    baseURL: process.env.VINFER_CONSOLE_URL ??
      "http://127.0.0.1:3000",
    headless: true,
    trace: "retain-on-failure",
  },
  webServer: process.env.VINFER_CONSOLE_URL
    ? undefined
    : {
        command: "npm run dev",
        url: "http://127.0.0.1:3000",
        reuseExistingServer: true,
      },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
      },
    },
  ],
});
