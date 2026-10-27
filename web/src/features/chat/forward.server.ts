import "server-only";
import { AgentConfigError, callAgent, type AgentServe } from "./agent.server";
import { checkChat, cookieValue } from "./guard";
import { SESSION_COOKIE } from "./protocol";

function reject(status: number, error: string): Response {
  return Response.json({ error }, { status, headers: { "cache-control": "no-store" } });
}

/**
 * POST /api/chat：网站唯一的转发路由（docs/modules.md）。检查不过的请求不碰 agent.serve；
 * 只转发 question 和 thread_id，用户由 agent.serve 从会话 id 得出，CSRF 令牌也由它核对。
 */
export async function forwardChat(
  request: Request,
  site: URL,
  serve: AgentServe | null,
): Promise<Response> {
  const rejected = checkChat(request.headers, site);
  if (rejected) return reject(rejected.status, rejected.error);
  if (!serve) return reject(503, "对话服务未接入");
  const session = cookieValue(request.headers, SESSION_COOKIE);
  if (!session) return reject(401, "没有登录或登录已过期");
  const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body || typeof body.question !== "string")
    return reject(400, "问题不能为空");
  if (body.thread_id !== undefined && body.thread_id !== null && typeof body.thread_id !== "string")
    return reject(400, "对话编号不对");
  let upstream: Response;
  try {
    upstream = await callAgent(serve, "/chat", {
      method: "POST",
      session,
      csrf: request.headers.get("x-csrf") ?? "",
      body: { question: body.question, thread_id: body.thread_id ?? null },
      signal: request.signal,
    });
  } catch (error) {
    if (error instanceof AgentConfigError) return reject(503, error.message);
    return reject(502, "对话服务没有响应");
  }
  if (!upstream.ok || !upstream.body) {
    const payload = await upstream.json().catch(() => ({ error: "对话服务出错" }));
    return Response.json(payload, { status: upstream.status, headers: { "cache-control": "no-store" } });
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": "application/x-ndjson; charset=utf-8",
      "cache-control": "no-store",
      "x-accel-buffering": "no",
    },
  });
}
