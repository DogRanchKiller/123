import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("./actions", () => ({ login: vi.fn(), logout: vi.fn() }));

const { ChatPanel } = await import("./chat-panel.client");

const quota = [
  { name: "你今日的额度", used: 0, cap: 2 },
  { name: "全站今日额度", used: 0.5, cap: 10 },
];

function ndjson(events: object[]): Response {
  const text = events.map((event) => JSON.stringify(event) + "\n").join("");
  return new Response(text, { headers: { "content-type": "application/x-ndjson" } });
}

function done(output: string, outcome = "passed") {
  return {
    type: "done",
    thread_id: "abcdef123456",
    output,
    outcome,
    cost: 0.0123,
    quota: [{ name: "你今日的额度", used: 0.0123, cap: 2 }],
  };
}

describe("ChatPanel", () => {
  it("发问题带 CSRF 头，显示核对结果和额度，追问沿用对话编号", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(ndjson([{ type: "step", node: "tools", label: "查数据", tools: ["list_upcoming"] }, done("Arsenal 下一场 <b>主场</b>")]))
      .mockResolvedValueOnce(ndjson([done("第二轮", "degraded")]));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ChatPanel user="alice" csrf="csrf-1" quota={quota} />);
    expect(screen.getByText("$0.50 / $10.00")).toBeInTheDocument();

    await user.type(screen.getByLabelText("你的问题"), "Arsenal 下一场？");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByText("Arsenal 下一场 <b>主场</b>")).toBeInTheDocument();
    expect(screen.getByText("数字已核对")).toBeInTheDocument();
    expect(screen.getByText("本轮花费 $0.0123")).toBeInTheDocument();
    expect(screen.getByText("$0.0123 / $2.00")).toBeInTheDocument();
    expect(document.querySelector("b")).toBeNull();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/chat");
    expect(init.headers).toEqual({ "content-type": "application/json", "x-csrf": "csrf-1" });
    expect(JSON.parse(init.body as string)).toEqual({ question: "Arsenal 下一场？", thread_id: null });

    await user.type(screen.getByLabelText("你的问题"), "那客队呢？");
    await user.keyboard("{Control>}{Enter}{/Control}");
    expect(await screen.findByText("第二轮")).toBeInTheDocument();
    expect(screen.getByText("没能核对回答里的数字，只列出查到的数据")).toBeInTheDocument();
    expect(JSON.parse((fetchMock.mock.calls[1] as [string, RequestInit])[1].body as string).thread_id).toBe("abcdef123456");

    await user.click(screen.getByRole("button", { name: "新对话" }));
    expect(screen.queryByText("第二轮")).toBeNull();
  });

  it("被拒时显示服务给的原因", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ error: "你已有一个进行中的对话", scope: "user" }, { status: 429 })));
    const user = userEvent.setup();
    render(<ChatPanel user="alice" csrf="c" quota={quota} />);
    await user.type(screen.getByLabelText("你的问题"), "x");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByText("你已有一个进行中的对话", { selector: ".chat-alert" })).toBeInTheDocument();
  });

  it("流没有 done 就断开时提示没收到结果", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ndjson([{ type: "step", node: "agent", label: "思考中" }])));
    const user = userEvent.setup();
    render(<ChatPanel user="alice" csrf="c" quota={quota} />);
    await user.type(screen.getByLabelText("你的问题"), "x");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByText("连接中断，这一轮的结果没有收到", { selector: ".chat-alert" })).toBeInTheDocument();
  });

  it("回答进行中不能再发", async () => {
    let finish: (value: Response) => void = () => undefined;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => (finish = resolve))));
    const user = userEvent.setup();
    render(<ChatPanel user="alice" csrf="c" quota={quota} />);
    await user.type(screen.getByLabelText("你的问题"), "x");
    await user.click(screen.getByRole("button", { name: "发送" }));
    await user.type(screen.getByLabelText("你的问题"), "y");
    expect(screen.getByRole("button", { name: "回答中…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "新对话" })).toBeDisabled();
    finish(ndjson([done("好了")]));
    await waitFor(() => expect(screen.getByRole("button", { name: "发送" })).toBeEnabled());
  });
});
