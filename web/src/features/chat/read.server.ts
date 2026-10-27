import "server-only";
import { cookies } from "next/headers";
import { AgentConfigError, agentServe, callAgent } from "./agent.server";
import { SESSION_COOKIE, type Quota } from "./protocol";

export type ChatState =
  | { kind: "unconfigured" }
  | { kind: "unavailable"; reason: string }
  | { kind: "anonymous" }
  | { kind: "ready"; user: string; /** UTC 秒 */ expires: number; csrf: string; quota: Quota[] };

/** 对话页的初始状态：服务是否接入、会话是否有效；有效时带 CSRF 令牌（放在页面里，请求头带回）。 */
export async function readChatState(): Promise<ChatState> {
  const serve = agentServe();
  if (!serve) return { kind: "unconfigured" };
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) return { kind: "anonymous" };
  try {
    const response = await callAgent(serve, "/session", { session });
    // 会话过期或已吊销：按未登录显示，重新登录时会覆盖旧 Cookie。
    if (response.status === 401) return { kind: "anonymous" };
    if (!response.ok) return { kind: "unavailable", reason: "对话服务出错" };
    const body = (await response.json()) as Omit<Extract<ChatState, { kind: "ready" }>, "kind">;
    return { kind: "ready", ...body };
  } catch (error) {
    if (error instanceof AgentConfigError) return { kind: "unavailable", reason: error.message };
    return { kind: "unavailable", reason: "对话服务没有响应" };
  }
}
