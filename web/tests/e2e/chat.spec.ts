import { expect, test, type Page } from "@playwright/test";
import { request as httpRequest } from "node:http";

const SITE = "http://127.0.0.1:3100";

async function chatCalls(): Promise<unknown[]> {
  const response = await fetch("http://127.0.0.1:3101/__calls");
  return ((await response.json()) as { chats: unknown[] }).chats;
}

async function login(page: Page) {
  await page.goto("/chat");
  await page.getByLabel("邀请码").fill("good-code");
  await page.getByRole("button", { name: "进入问答" }).click();
  await expect(page.getByLabel("你的问题")).toBeVisible();
}

/** 直接发原始请求，Host 和 Origin 都能随意设，模拟浏览器以外的来源。 */
function raw(method: string, headers: Record<string, string>, body = ""): Promise<number> {
  return new Promise((resolve, reject) => {
    const req = httpRequest(`${SITE}/api/chat`, { method, headers }, (res) => {
      res.resume();
      resolve(res.statusCode ?? 0);
    });
    req.on("error", reject);
    req.end(body);
  });
}

test("未登录时显示邀请码表单，页面不进搜索", async ({ page }) => {
  await page.goto("/chat");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("问一问这套预测系统。");
  await expect(page).toHaveTitle(/问答/);
  await expect(page.getByLabel("邀请码")).toBeVisible();
  await expect(page.getByRole("link", { name: "问答", exact: true })).toHaveAttribute("aria-current", "page");
  const html = await (await page.request.get("/chat")).text();
  expect(html).toContain("输入邀请码");
});

test("邀请码错误不发 Cookie；正确时 Cookie 带 HttpOnly、SameSite=Strict、Path=/ 和过期时间", async ({ page, context }) => {
  await page.goto("/chat");
  await page.getByLabel("邀请码").fill("wrong-code");
  await page.getByRole("button", { name: "进入问答" }).click();
  await expect(page.locator("#chat-login-error")).toHaveText("邀请码不对或已停用");
  expect((await context.cookies()).find((cookie) => cookie.name === "fp_chat")).toBeUndefined();

  await page.getByLabel("邀请码").fill("good-code");
  const [response] = await Promise.all([
    page.waitForResponse((r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/chat"),
    page.getByRole("button", { name: "进入问答" }).click(),
  ]);
  const header = (await response.headerValue("set-cookie")) ?? "";
  expect(header).toMatch(/^fp_chat=[0-9a-f]{32};/);
  expect(header).toMatch(/HttpOnly/i);
  expect(header).toMatch(/SameSite=Strict/i);
  expect(header).toMatch(/Path=\//);
  expect(header).toMatch(/Expires=/i);
  expect(header).not.toMatch(/Secure/i);
  const cookie = (await context.cookies()).find((item) => item.name === "fp_chat");
  expect(cookie).toMatchObject({ httpOnly: true, sameSite: "Strict", path: "/" });
  expect(cookie!.expires).toBeGreaterThan(Date.now() / 1000 + 13 * 86400);
});

test("登录后提问：流式显示进度和核对过的回答，追问沿用对话", async ({ page }) => {
  const before = (await chatCalls()).length;
  await login(page);
  await expect(page.getByText("你今日的额度")).toBeVisible();
  await page.getByLabel("你的问题").fill("Arsenal 下一场亚盘怎么看？");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.locator(".chat-output")).toHaveText("回答：Arsenal 下一场亚盘怎么看？\n（时间均为北京时间）");
  await expect(page.getByText("数字已核对")).toBeVisible();
  await page.getByLabel("你的问题").fill("那客队呢？");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.locator(".chat-output")).toHaveCount(2);
  const calls = (await chatCalls()).slice(before);
  expect(calls).toEqual([
    { question: "Arsenal 下一场亚盘怎么看？", thread_id: null },
    { question: "那客队呢？", thread_id: "abcdef123456" },
  ]);
});

test("对话路由：别的来源、缺 Origin、Host 不对、不是 JSON、缺 CSRF、GET、表单、没有 Cookie 都被拒，且不转发", async ({ page, context }) => {
  await login(page);
  const sid = (await context.cookies()).find((cookie) => cookie.name === "fp_chat")!.value;
  const before = (await chatCalls()).length;
  const ok = {
    host: "127.0.0.1:3100",
    origin: SITE,
    "content-type": "application/json",
    "x-csrf": "anything",
    cookie: `fp_chat=${sid}`,
  };
  const body = JSON.stringify({ question: "x" });
  const cases: [string, string, Record<string, string>, number][] = [
    ["别的来源", "POST", { ...ok, origin: "http://evil.example" }, 403],
    ["缺 Origin", "POST", Object.fromEntries(Object.entries(ok).filter(([k]) => k !== "origin")), 403],
    ["Host 不对", "POST", { ...ok, host: "evil.example:3100" }, 403],
    ["不是 JSON", "POST", { ...ok, "content-type": "text/plain" }, 415],
    ["表单格式", "POST", { ...ok, "content-type": "application/x-www-form-urlencoded" }, 415],
    ["缺 CSRF", "POST", Object.fromEntries(Object.entries(ok).filter(([k]) => k !== "x-csrf")), 403],
    ["没有 Cookie", "POST", Object.fromEntries(Object.entries(ok).filter(([k]) => k !== "cookie")), 401],
    ["GET", "GET", ok, 405],
  ];
  for (const [name, method, headers, status] of cases)
    expect(await raw(method, headers, method === "GET" ? "" : body), name).toBe(status);
  expect(await chatCalls()).toHaveLength(before);
  // 头都对、但 CSRF 令牌不属于这个会话：转发后由 agent.serve 拒绝。
  expect(await raw("POST", ok, body)).toBe(403);
  expect(await chatCalls()).toHaveLength(before);
});

test("退出后旧会话失效", async ({ page, context }) => {
  await login(page);
  const sid = (await context.cookies()).find((cookie) => cookie.name === "fp_chat")!.value;
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page.getByLabel("邀请码")).toBeVisible();
  expect((await context.cookies()).find((cookie) => cookie.name === "fp_chat")).toBeUndefined();
  await context.addCookies([{ name: "fp_chat", value: sid, url: SITE }]);
  await page.goto("/chat");
  await expect(page.getByLabel("邀请码")).toBeVisible();
});

for (const width of [360, 390, 768, 1440]) {
  test("问答页响应式 " + width, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const fits = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
    await page.goto("/chat");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(await fits()).toBe(true);
    await login(page);
    await page.getByLabel("你的问题").fill("一个很长的问题".repeat(30));
    await page.getByRole("button", { name: "发送" }).click();
    await expect(page.locator(".chat-output")).toBeVisible();
    expect(await fits()).toBe(true);
  });
}
