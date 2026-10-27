// 端到端测试用的假 agent.serve（agent/serve.py 的协议），只听 127.0.0.1，不调模型、不花钱。
// /__calls 只给测试看收到了哪些对话请求，正式的 agent.serve 没有这个路由。
import { createServer } from "node:http";
import { randomBytes } from "node:crypto";

const PORT = Number(process.env.FAKE_AGENT_PORT ?? 3101);
const TOKEN = process.env.AGENT_SERVICE_TOKEN ?? "";
const CODE = "good-code";
const sessions = new Map();
const chats = [];

function send(res, status, body) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(body === undefined ? "" : JSON.stringify(body));
}

async function readJson(req) {
  let text = "";
  for await (const chunk of req) text += chunk;
  if (!(req.headers["content-type"] ?? "").startsWith("application/json")) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function sessionOf(req) {
  const s = sessions.get(req.headers["x-session"] ?? "");
  return s && !s.revoked ? s : null;
}

const quota = () => [
  { name: "你今日的额度", used: chats.length * 0.0123, cap: 2 },
  { name: "全站今日额度", used: chats.length * 0.0123, cap: 10 },
  { name: "全站本月额度", used: chats.length * 0.0123, cap: 100 },
];

createServer(async (req, res) => {
  if (req.url === "/__calls") return send(res, 200, { chats });
  if (req.headers["x-service-token"] !== TOKEN)
    return send(res, 401, { error: "服务令牌不对", reason: "service_token" });
  if (req.method === "POST" && req.url === "/login") {
    const body = await readJson(req);
    if (!body) return send(res, 415, { error: "只接受 JSON" });
    if (body.code !== CODE) return send(res, 401, { error: "邀请码不对或已停用" });
    const sid = randomBytes(16).toString("hex");
    const s = { user: "alice", expires: Date.now() / 1000 + 14 * 86400, csrf: randomBytes(8).toString("hex") };
    sessions.set(sid, s);
    return send(res, 200, { session: sid, ...s });
  }
  if (req.method === "GET" && req.url === "/session") {
    const s = sessionOf(req);
    return s ? send(res, 200, { ...s, quota: quota() }) : send(res, 401, { error: "没有登录或登录已过期" });
  }
  if (req.method === "POST" && req.url === "/logout") {
    const s = sessions.get(req.headers["x-session"] ?? "");
    if (s) s.revoked = true;
    return send(res, 204);
  }
  if (req.method === "POST" && req.url === "/chat") {
    const s = sessionOf(req);
    if (!s) return send(res, 401, { error: "没有登录或登录已过期" });
    if (req.headers["x-csrf"] !== s.csrf) return send(res, 403, { error: "页面已过期，请刷新后再问" });
    const body = await readJson(req);
    if (!body) return send(res, 415, { error: "只接受 JSON" });
    chats.push(body);
    res.writeHead(200, { "content-type": "application/x-ndjson" });
    res.write(JSON.stringify({ type: "step", node: "tools", label: "查数据", tools: ["list_upcoming"] }) + "\n");
    await new Promise((resolve) => setTimeout(resolve, 150));
    res.end(
      JSON.stringify({
        type: "done",
        thread_id: body.thread_id ?? "abcdef123456",
        output: `回答：${body.question}\n（时间均为北京时间）`,
        outcome: "passed",
        cost: 0.0123,
        quota: quota(),
      }) + "\n",
    );
    return;
  }
  send(res, 404, { error: "没有这个路由" });
}).listen(PORT, "127.0.0.1");
