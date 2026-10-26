import { expect, test } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";

const control = (entry?: string) => writeFileSync(resolve(".test-control.json"), JSON.stringify({entry}));
test.afterEach(() => control());

test("首页200、SSR、metadata和单层错误壳", async ({ request, page }) => {
  const response=await request.get("/");
  expect(response.status()).toBe(200);
  expect(response.headers()["x-robots-tag"]).toContain("noindex");
  const html=(await response.text()).replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,"");
  expect(html).toContain("从数据中，"); expect(html).toContain("阿森纳");
  expect(html).toContain('rel="canonical"'); expect(html).toContain('name="description"');
  expect(html).toContain('content="noindex, nofollow"');
  for(const path of ["/", "/predictions/not-a-match", "/unknown-page"]) {
    await page.goto(path);
    await expect(page.locator("header")).toHaveCount(1);
    await expect(page.locator("main#main-content")).toHaveCount(1);
    await expect(page.getByRole("link",{name:"绿茵观察首页"}).last()).toHaveAttribute("href","/");
  }
  await page.goto("/");
  expect(new URL(page.url()).pathname).toBe("/");
  await page.getByRole("link",{name:"查看今日预测"}).click();
  await expect(page).toHaveURL(/\/predictions$/);
});

for (const width of [360,390,768,1023,1024,1440]) {
  test(`首页布局与静态降级 ${width}`, async ({page}) => {
    await page.emulateMedia({reducedMotion:"reduce"});
    await page.setViewportSize({width,height:900});
    await page.goto("/");
    await expect(page.getByRole("heading",{level:1})).toBeVisible();
    await expect(page.getByRole("button",{name:"开启动画"})).toBeVisible();
    await expect(page.locator("canvas")).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.getByTestId("entry-probability-0")).toHaveText("64%");
    if (width <= 1023) {
      await expect(page.getByRole("button", { name: "展开导航" })).toBeVisible();
      await page.getByRole("button", { name: "展开导航" }).click();
      await expect(page.getByRole("navigation")).toBeVisible();
      await page.getByRole("button", { name: "收起导航" }).click();
      await expect(page.getByRole("navigation")).not.toBeVisible();
    } else {
      await expect(page.getByRole("button", { name: "展开导航" })).not.toBeVisible();
      await expect(page.getByRole("navigation")).toBeVisible();
    }
    await page.screenshot({path:`test-results/entry-${width}.png`,fullPage:true});
  });
}

test("登录注册校验、焦点限制与退出恢复，不建立认证", async ({page}) => {
  await page.emulateMedia({reducedMotion:"reduce"}); await page.goto("/");
  const trigger=page.getByRole("button",{name:"登录 / 注册"});
  await trigger.click(); const dialog=page.getByRole("dialog"); await expect(dialog).toBeVisible();
  for(let i=0;i<16;i++) { await page.keyboard.press("Tab"); expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true); }
  await dialog.getByRole("button",{name:"注册",exact:true}).first().click();
  await dialog.getByLabel("邮箱",{exact:true}).fill("invalid");
  await dialog.getByLabel("密码",{exact:true}).fill("abcdefgh");
  await dialog.getByLabel("确认密码",{exact:true}).fill("different");
  await dialog.getByRole("button",{name:"注册",exact:true}).last().click();
  expect(await dialog.getByLabel("邮箱",{exact:true}).evaluate(el => (el as HTMLInputElement).validity.valid)).toBe(false);
  await dialog.getByLabel("邮箱",{exact:true}).fill("preview@example.com");
  await dialog.getByRole("button",{name:"注册",exact:true}).last().click();
  await expect(dialog.getByRole("status")).toContainText("两次输入的密码不一致");
  await dialog.getByLabel("确认密码",{exact:true}).fill("abcdefgh");
  await dialog.getByRole("button",{name:"注册",exact:true}).last().click();
  await expect(dialog.getByRole("status")).toContainText("账号服务尚未接入");
  await dialog.getByRole("button",{name:"手机验证码",exact:true}).click();
  await dialog.getByLabel("手机号").fill("123");
  expect(await dialog.getByLabel("手机号").evaluate(el => (el as HTMLInputElement).validity.valid)).toBe(false);
  await dialog.getByRole("button",{name:"获取验证码"}).click();
  await expect(dialog.getByRole("status")).toContainText("短信服务尚未接入");
  await page.keyboard.press("Escape"); await expect(dialog).not.toBeVisible(); await expect(trigger).toBeFocused();
  expect(await page.context().cookies()).toEqual([]);
  expect(await page.evaluate(() => Object.values(localStorage).join("")+Object.values(sessionStorage).join(""))).not.toContain("abcdefgh");
  await trigger.click(); await expect(dialog.getByLabel("手机号")).toHaveValue("");
});

test("真实刷新保留旧值、换场、空候选、恢复且Canvas不重挂", async ({page}) => {
  test.setTimeout(90_000);
  const errors:string[]=[]; page.on("pageerror",e=>errors.push(e.message));
  await page.clock.install();
  await page.setViewportSize({width:1440,height:900}); await page.goto("/");
  await expect(page.locator(".entry-pitch")).toHaveAttribute("data-scene-state","ready",{timeout:30_000});
  const canvas=await page.locator("canvas").elementHandle();
  const number=await page.getByTestId("entry-probability-0").elementHandle();
  await page.screenshot({path:"test-results/entry-3d.png",fullPage:true});
  async function refresh(mode?: string) {
    control(mode);
    const before=await page.locator(".entry-screen").getAttribute("data-read-at");
    const response=page.waitForResponse(r=>r.url().includes("_rsc=") && r.status()===200);
    await page.clock.fastForward(60_000); await response;
    await expect(page.locator(".entry-screen")).not.toHaveAttribute("data-read-at",before!);
    await page.clock.runFor(100);
  }
  await refresh();
  expect(await number!.evaluate(el=>el === document.querySelector('[data-testid="entry-probability-0"]'))).toBe(true);
  await refresh("fail"); await expect(page.getByRole("status")).toContainText("更新延迟");
  await expect(page.getByTestId("entry-probability-0")).toHaveText("64%");
  await refresh("second"); await expect(page.getByTestId("entry-probability-0")).toHaveText("68%");
  await expect(page.getByRole("status")).toHaveCount(0);
  await refresh("empty"); await expect(page.getByTestId("entry-probability-0")).toHaveCount(0);
  await refresh(); await expect(page.getByTestId("entry-probability-0")).toHaveText("64%");
  expect(await canvas!.evaluate(el=>el === document.querySelector("canvas"))).toBe(true);
  expect(errors).toEqual([]);
});

test("首次读取失败与WebGL失败仍可访问首页", async ({page}) => {
  control("fail");
  await page.clock.install();
  await page.addInitScript(() => {
    const original=HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext=function(this: HTMLCanvasElement, ...args: Parameters<typeof original>) {
      if(String(args[0]).startsWith("webgl")) return null;
      return original.apply(this,args);
    } as typeof original;
  });
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText("更新延迟");
  await expect(page.getByTestId("entry-probability-0")).toHaveCount(0);
  await expect(page.locator(".entry-poster")).toBeVisible();
  await expect(page.getByRole("button",{name:"静态球场"})).toBeDisabled();
  control(); await page.clock.fastForward(60_000);
  await expect(page.getByTestId("entry-probability-0")).toHaveText("64%");
});
