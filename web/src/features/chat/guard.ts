/**
 * 对话路由的请求检查（docs/agent-plan.md 第 10.2 节「共同的规则」）。纯函数，不读环境变量。
 * 顺序：Origin → Host → Content-Type → CSRF 头；全部通过才转发，任何一项不过都不碰 agent.serve。
 */
export interface Rejection {
  status: number;
  error: string;
}

/** Origin 必须等于站点地址（缺 Origin 也拒），Host 必须是站点自己的主机名和端口。 */
export function checkSite(headers: Headers, site: URL): Rejection | null {
  if (headers.get("origin") !== site.origin)
    return { status: 403, error: "请求来源不对" };
  if (headers.get("host") !== site.host)
    return { status: 403, error: "站点地址不对" };
  return null;
}

export function checkChat(headers: Headers, site: URL): Rejection | null {
  const wrongSite = checkSite(headers, site);
  if (wrongSite) return wrongSite;
  const type = headers.get("content-type") ?? "";
  if (type.split(";")[0].trim().toLowerCase() !== "application/json")
    return { status: 415, error: "只接受 JSON" };
  if (!headers.get("x-csrf"))
    return { status: 403, error: "页面已过期，请刷新后再问" };
  return null;
}

/** 只从请求头里的 Cookie 取会话 id；没有就是空串。 */
export function cookieValue(headers: Headers, name: string): string {
  for (const part of (headers.get("cookie") ?? "").split(";")) {
    const at = part.indexOf("=");
    if (at > 0 && part.slice(0, at).trim() === name) {
      try {
        return decodeURIComponent(part.slice(at + 1).trim());
      } catch {
        return "";
      }
    }
  }
  return "";
}
