"use server";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { siteUrl } from "@/lib/site.server";
import { AgentConfigError, agentServe, callAgent } from "./agent.server";
import { checkSite } from "./guard";
import { SESSION_COOKIE } from "./protocol";

export interface LoginState {
  error: string | null;
}

/**
 * 登录：邀请码交给 agent.serve 核对，通过后发会话 Cookie（HttpOnly、SameSite=Strict、Path=/、带过期时间）。
 * 站点走 Tailscale 的 http，只有 SITE_URL 是 https 时才加 Secure（docs/agent-plan.md 第 10.2 节）。
 * Server Action 自带 Origin 与 Host 的比对；这里再按 SITE_URL 查一遍，和对话路由一致。
 */
export async function login(_: LoginState, form: FormData): Promise<LoginState> {
  if (checkSite(await headers(), siteUrl)) return { error: "请求来源不对，请从站点地址打开本页" };
  const code = String(form.get("code") ?? "").trim();
  if (!code) return { error: "请输入邀请码" };
  if (code.length > 200) return { error: "邀请码不对或已停用" };
  const serve = agentServe();
  if (!serve) return { error: "对话服务未接入" };
  let response: Response;
  try {
    response = await callAgent(serve, "/login", { method: "POST", body: { code } });
  } catch (error) {
    return { error: error instanceof AgentConfigError ? error.message : "对话服务没有响应，请稍后再试" };
  }
  if (response.status === 401) return { error: "邀请码不对或已停用" };
  if (!response.ok) return { error: "登录没有成功，请稍后再试" };
  const { session, expires } = (await response.json()) as { session: string; expires: number };
  (await cookies()).set(SESSION_COOKIE, session, {
    httpOnly: true,
    sameSite: "strict",
    path: "/",
    secure: siteUrl.protocol === "https:",
    expires: new Date(expires * 1000),
  });
  redirect("/chat");
}

/** 退出：在 agent.serve 里吊销这个会话，再删 Cookie。服务不通时也删 Cookie。 */
export async function logout(): Promise<void> {
  if (checkSite(await headers(), siteUrl)) return;
  const jar = await cookies();
  const session = jar.get(SESSION_COOKIE)?.value;
  const serve = agentServe();
  if (session && serve)
    await callAgent(serve, "/logout", { method: "POST", session }).catch(() => undefined);
  jar.delete({ name: SESSION_COOKIE, path: "/" });
  redirect("/chat");
}
