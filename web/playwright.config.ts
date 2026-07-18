import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  reporter: "line",
  use: {
    baseURL: process.env.VINFER_CONSOLE_URL ??
      "https://console.213.239.141.40.sslip.io",
    headless: true,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: {
          args: [
            "--host-resolver-rules=MAP console.213.239.141.40.sslip.io 213.239.141.40",
          ],
        },
      },
    },
  ],
});
