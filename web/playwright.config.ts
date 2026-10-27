import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";

// 假 agent.serve 的服务令牌只用于本机测试。
const AGENT_SERVICE_TOKEN = "e2e-service-token-0123456789abcdef";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: { baseURL: "http://127.0.0.1:3100", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  webServer: [
    {
      command: "node tests/fake-agent.mjs",
      url: "http://127.0.0.1:3101/__calls",
      reuseExistingServer: false,
      timeout: 10000,
      env: { FAKE_AGENT_PORT: "3101", AGENT_SERVICE_TOKEN },
    },
    {
      command: "node tests/start-production.mjs",
      url: "http://127.0.0.1:3100/predictions",
      reuseExistingServer: false,
      timeout: 60000,
      env: {
        SITE_URL: "http://127.0.0.1:3100",
        WEB_TEST_CONTROL_FILE: resolve(".test-control.json"),
        NEXT_TELEMETRY_DISABLED: "1",
        AGENT_SERVE_URL: "http://127.0.0.1:3101",
        AGENT_SERVICE_TOKEN,
      },
    },
  ],
});
