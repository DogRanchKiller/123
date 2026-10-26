import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("next/server", () => ({ connection: async () => undefined }));

const { ApiError, apiBase, apiConfigured } = await import("./api.server");

describe("API_URL", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("未配置时是演示模式", async () => {
    vi.stubEnv("API_URL", "  ");
    expect(await apiConfigured()).toBe(false);
    expect(await apiBase()).toBeNull();
  });

  it("去掉末尾斜杠", async () => {
    vi.stubEnv("API_URL", "http://127.0.0.1:8000/");
    expect(await apiConfigured()).toBe(true);
    expect(await apiBase()).toBe("http://127.0.0.1:8000");
  });

  it("地址无效时报出 API_URL，而不是 TypeError", async () => {
    vi.stubEnv("API_URL", "127.0.0.1:8000:x");
    expect(await apiConfigured()).toBe(true);
    await expect(apiBase()).rejects.toThrow(ApiError);
    await expect(apiBase()).rejects.toThrow(/API_URL/);
  });

  it("拒绝非 http 协议", async () => {
    vi.stubEnv("API_URL", "file:///etc/passwd");
    await expect(apiBase()).rejects.toThrow(/http 或 https/);
  });
});
