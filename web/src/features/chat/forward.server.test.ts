import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

const { forwardChat } = await import("./forward.server");

const site = new URL("http://100.64.0.1:3000");
const serve = { base: "http://127.0.0.1:8100", token: "t".repeat(40) };
const good = {
  host: "100.64.0.1:3000",
  origin: "http://100.64.0.1:3000",
  "content-type": "application/json",
  "x-csrf": "csrf-1",
  cookie: "other=1; fp_chat=sid-1",
};

function request(headers: Record<string, string | undefined>, body: string = JSON.stringify({ question: "Arsenal？" })) {
  const clean = Object.fromEntries(Object.entries(headers).filter(([, v]) => v !== undefined)) as Record<string, string>;
  return new Request("http://100.64.0.1:3000/api/chat", { method: "POST", headers: clean, body });
}

function stubAgent(response: Response) {
  const fetchMock = vi.fn(async () => response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("forwardChat", () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each([
    ["Origin 是别的站点", { origin: "http://evil.example" }, 403],
    ["缺 Origin", { origin: undefined }, 403],
    ["Host 不对", { host: "evil.example:3000" }, 403],
    ["不是 JSON", { "content-type": "text/plain" }, 415],
    ["表单格式", { "content-type": "application/x-www-form-urlencoded" }, 415],
    ["缺 CSRF 令牌", { "x-csrf": undefined }, 403],
    ["没有会话 Cookie", { cookie: "other=1" }, 401],
  ])("%s 被拒，不碰 agent.serve", async (_, patch, status) => {
    const fetchMock = stubAgent(new Response("{}"));
    const response = await forwardChat(request({ ...good, ...patch }), site, serve);
    expect(response.status).toBe(status);
    expect((await response.json()).error).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("没有配置服务时 503", async () => {
    const fetchMock = stubAgent(new Response("{}"));
    expect((await forwardChat(request(good), site, null)).status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("只转发问题和对话编号，带服务令牌、会话 id 与 CSRF 头", async () => {
    const fetchMock = stubAgent(new Response('{"type":"done"}\n', { headers: { "content-type": "application/x-ndjson" } }));
    const body = JSON.stringify({ question: "Arsenal？", thread_id: "abcdef12", user: "mallory" });
    const response = await forwardChat(request(good, body), site, serve);
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("application/x-ndjson");
    expect(await response.text()).toBe('{"type":"done"}\n');
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:8100/chat");
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({
      "x-service-token": serve.token,
      "x-session": "sid-1",
      "x-csrf": "csrf-1",
      "content-type": "application/json",
    });
    expect(JSON.parse(init.body as string)).toEqual({ question: "Arsenal？", thread_id: "abcdef12" });
  });

  it("agent.serve 的拒绝原样带回状态码", async () => {
    stubAgent(Response.json({ error: "你已有一个进行中的对话", scope: "user" }, { status: 429 }));
    const response = await forwardChat(request(good), site, serve);
    expect(response.status).toBe(429);
    expect(await response.json()).toEqual({ error: "你已有一个进行中的对话", scope: "user" });
  });

  it("服务令牌不对时报配置错，不当成没登录", async () => {
    stubAgent(Response.json({ error: "服务令牌不对", reason: "service_token" }, { status: 401 }));
    const response = await forwardChat(request(good), site, serve);
    expect(response.status).toBe(503);
  });

  it("agent.serve 不通时 502", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("fetch failed"))));
    expect((await forwardChat(request(good), site, serve)).status).toBe(502);
  });

  it("请求体不是对象或没有问题时 400", async () => {
    const fetchMock = stubAgent(new Response("{}"));
    for (const body of ["not json", "[]", JSON.stringify({ question: 5 }), JSON.stringify({ question: "x", thread_id: 5 })])
      expect((await forwardChat(request(good, body), site, serve)).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
