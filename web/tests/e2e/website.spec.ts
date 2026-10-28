import { expect, test } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";

const fail = (ids: string[]) =>
  writeFileSync(
    resolve(".test-control.json"),
    JSON.stringify({ failIds: ids }),
  );
test.afterEach(() => fail([]));

test("首屏 HTML、metadata、全站禁止收录与未知 ID 404", async ({ request }) => {
  for (const path of [
    "/predictions",
    "/following",
    "/review",
    "/predictions/demo-arsenal-chelsea",
  ]) {
    const response = await request.get(path);
    expect(response.status()).toBe(200);
    expect(response.headers()["x-robots-tag"]).toContain("noindex");
    const html = await response.text();
    expect(html).toContain('lang="zh-CN"');
    expect(html).toMatch(/<title>.+<\/title>/);
    expect(html).toMatch(/<meta name="description" content="[^"]+"/);
    expect(html).toContain('rel="canonical"');
    expect(html).toContain('content="noindex, nofollow"');
    expect(html).toContain("演示数据");
    if (path === "/review") {
      expect(html).toContain("对比基准");
      expect(html).toContain("对收盘赔率（参照）");
    }
    if (path.includes("demo-")) {
      const documentOnly = html.replace(
        /<script\b[^>]*>[\s\S]*?<\/script>/g,
        "",
      );
      expect(documentOnly).toMatch(/<h1[^>]*>阿森纳/);
    }
  }
  const missing = await request.get("/predictions/not-a-match");
  expect(missing.status()).toBe(404);
  expect(await missing.text()).toContain("找不到这场比赛");
  expect((await request.get("/robots.txt")).status()).toBe(200);
  expect(await (await request.get("/robots.txt")).text()).toContain(
    "Disallow: /",
  );
  expect((await request.get("/sitemap.xml")).status()).toBe(404);
  expect((await request.get("/api/predictions")).status()).toBe(404);
});

test("首次读取失败是 5xx，恢复后成功；有旧数据时保留原时间", async ({
  request,
  page,
}) => {
  const path = "/predictions/demo-madrid-betis";
  fail(["demo-madrid-betis"]);
  const error = await request.get(path);
  expect(error.status()).toBeGreaterThanOrEqual(500);
  expect(error.headers()["cache-control"]).toContain("no-store");
  const errorDocument = (await error.text()).replace(
    /<script\b[^>]*>[\s\S]*?<\/script>/g,
    "",
  );
  expect(errorDocument).not.toContain("找不到这场比赛");
  const failedNavigation = await page.goto(path);
  expect(failedNavigation?.status()).toBeGreaterThanOrEqual(500);
  await expect(page.getByRole("heading", { name: "数据暂时无法读取" })).toBeVisible();
  fail([]);
  await page.getByRole("button", { name: "重新读取" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("皇家马德里 对 皇家贝蒂斯");
  const recovered = await request.get(path);
  expect(recovered.status()).toBe(200);
  expect(await recovered.text()).toContain("皇家马德里");
  fail(["demo-madrid-betis"]);
  const delayed = await request.get(path);
  expect(delayed.status()).toBe(200);
  const html = await delayed.text();
  expect(html).toContain("更新延迟");
  expect(html).toContain("10/25 18:02");
  fail([]);
  expect(await (await request.get(path)).text()).not.toContain("更新延迟：");
});

test("滚动恢复与主题变量", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 780 });
  await page.goto("/predictions");
  await page.getByLabel("筛选联赛").selectOption("SP1");
  await page.evaluate(() => window.scrollTo(0, 600));
  await expect.poll(() => page.evaluate(() => JSON.parse(sessionStorage.getItem("football.predictions.view.v1") ?? "{}").scrollY)).toBe(600);
  await page.reload();
  await expect(page.getByLabel("筛选联赛")).toHaveValue("SP1");
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(600);
  const detailLink = page.getByRole("link", { name: "查看皇家马德里对皇家贝蒂斯详情" });
  await detailLink.scrollIntoViewIfNeeded();
  const savedY = await page.evaluate(() => window.scrollY);
  await expect.poll(() => page.evaluate(() => JSON.parse(sessionStorage.getItem("football.predictions.view.v1") ?? "{}").scrollY)).toBe(savedY);
  await detailLink.click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("皇家马德里 对 皇家贝蒂斯");
  expect(await page.evaluate(() => JSON.parse(sessionStorage.getItem("football.predictions.view.v1") ?? "{}").scrollY)).toBe(savedY);
  await page.getByRole("link", { name: "← 返回比赛列表" }).click();
  await expect(page.getByLabel("筛选联赛")).toHaveValue("SP1");
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(savedY);
  await page.evaluate(() => document.documentElement.style.setProperty("--background", "rgb(230, 240, 250)"));
  await expect(page.locator("body")).toHaveCSS("background-color", "rgb(230, 240, 250)");
});

test("关注保存、筛选恢复、前进后退及无水合错误", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/predictions");
  await page
    .getByRole("button", { name: "关注阿森纳对切尔西", exact: true })
    .first()
    .click();
  await page.reload();
  await expect(
    page
      .getByRole("button", { name: "取消关注阿森纳对切尔西", exact: true })
      .first(),
  ).toBeVisible();
  await page.getByLabel("筛选联赛").selectOption("SP1");
  await page.getByLabel("筛选比赛状态").selectOption("upcoming");
  await page.reload();
  await expect(page.getByLabel("筛选联赛")).toHaveValue("SP1");
  await expect(page.getByLabel("筛选比赛状态")).toHaveValue("upcoming");
  expect(new URL(page.url()).search).toBe("");
  await page
    .getByRole("link", { name: "查看皇家马德里对皇家贝蒂斯详情" })
    .click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "皇家马德里 对 皇家贝蒂斯",
  );
  await page.goBack();
  await expect(page.getByLabel("筛选联赛")).toHaveValue("SP1");
  await page.goForward();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "皇家马德里",
  );
  await page.goto("/following");
  await expect(
    page.getByRole("article", { name: "阿森纳对切尔西" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "取消关注阿森纳对切尔西", exact: true })
    .click();
  await expect(page.getByText("还没有关注的比赛")).toBeVisible();
  expect(errors).toEqual([]);
});

for (const width of [360, 390, 768, 1023, 1024, 1440]) {
  test("响应式布局 " + width, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    for (const path of [
      "/predictions",
      "/predictions/demo-arsenal-chelsea",
      "/review",
      "/following",
    ]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
    }
    if (width <= 1023) {
      await page.getByRole("button", { name: "展开导航" }).click();
      await expect(page.getByRole("navigation")).toBeVisible();
      await expect
        .poll(() => page.locator(".nav-link").evaluateAll((links) => links.map((link) => Math.round(link.getBoundingClientRect().height))))
        .toEqual([44, 44, 44, 44, 44]);
      await page.getByRole("link", { name: "比赛预测", exact: true }).click();
      await expect(page.getByRole("navigation")).not.toBeVisible();
    } else {
      await expect(page.getByRole("button", { name: "展开导航" })).not.toBeVisible();
    }
    await page.goto("/predictions");
    await page.screenshot({
      path: "test-results/predictions-" + width + ".png",
      fullPage: true,
    });
  });
}
