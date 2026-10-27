import "server-only";

/**
 * 转发到 agent.serve（agent/serve.py，只听 127.0.0.1）。地址和服务令牌只在服务端读环境变量，
 * 不进前端代码；两者都设了才算接入。浏览器不直接访问 agent.serve。
 */
export interface AgentServe {
  base: string;
  token: string;
}

export function agentServe(): AgentServe | null {
  const base = process.env.AGENT_SERVE_URL?.trim().replace(/\/+$/, "");
  const token = process.env.AGENT_SERVICE_TOKEN?.trim();
  return base && token ? { base, token } : null;
}

/** 服务令牌不对时 agent.serve 回 401 且 reason=service_token，和"没登录"分开处理。 */
export class AgentConfigError extends Error {}

export async function callAgent(
  serve: AgentServe,
  path: string,
  init: { method?: string; session?: string; csrf?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<Response> {
  const headers: Record<string, string> = { "x-service-token": serve.token };
  if (init.session) headers["x-session"] = init.session;
  if (init.csrf) headers["x-csrf"] = init.csrf;
  if (init.body !== undefined) headers["content-type"] = "application/json";
  const response = await fetch(`${serve.base}${path}`, {
    method: init.method ?? "GET",
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    cache: "no-store",
    signal: init.signal,
  });
  if (response.status === 401) {
    const body = (await response.clone().json().catch(() => null)) as { reason?: string } | null;
    if (body?.reason === "service_token") throw new AgentConfigError("对话服务的令牌配置不对");
  }
  return response;
}
