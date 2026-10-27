"use client";

import { useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { logout } from "./actions";
import {
  MAX_QUESTION,
  OUTCOMES,
  dollars,
  readEvents,
  verified,
  type Quota,
} from "./protocol";

interface Turn {
  id: number;
  question: string;
  status: "running" | "done" | "error";
  label: string;
  answer?: string;
  outcome?: string;
  cost?: number;
  error?: string;
}

const FALLBACK: Record<number, string> = {
  401: "登录已过期，请刷新页面重新登录",
  403: "页面已过期，请刷新后再问",
  429: "正在进行的对话太多，请稍后再问",
  503: "对话服务未接入",
};

async function failure(response: Response): Promise<string> {
  const body = (await response.json().catch(() => null)) as { error?: string } | null;
  return body?.error || FALLBACK[response.status] || `这一轮没有完成（${response.status}）`;
}

export function ChatPanel({
  user,
  csrf,
  quota: initialQuota,
}: {
  user: string;
  csrf: string;
  quota: Quota[];
}) {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [quota, setQuota] = useState(initialQuota);
  const [announce, setAnnounce] = useState("");
  const nextId = useRef(0);
  const running = turns.some((turn) => turn.status === "running");

  function update(id: number, patch: Partial<Turn>) {
    setTurns((all) => all.map((turn) => (turn.id === id ? { ...turn, ...patch } : turn)));
  }

  async function ask(text: string) {
    const id = nextId.current++;
    setTurns((all) => [...all, { id, question: text, status: "running", label: "发送中" }]);
    setQuestion("");
    setAnnounce("问题已发送");
    const fail = (error: string) => {
      update(id, { status: "error", error });
      setAnnounce(error);
    };
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf": csrf },
        body: JSON.stringify({ question: text, thread_id: threadId }),
      });
      if (!response.ok || !response.body) return fail(await failure(response));
      for await (const event of readEvents(response.body)) {
        if (event.type === "step") {
          const label = event.tools?.length ? `${event.label}（${event.tools.length} 项）` : event.label;
          update(id, { label });
          setAnnounce(label);
        } else if (event.type === "done") {
          update(id, { status: "done", answer: event.output, outcome: event.outcome, cost: event.cost });
          setThreadId(event.thread_id);
          setQuota(event.quota);
          setAnnounce("回答已生成");
          return;
        } else if (event.type === "error") {
          return fail(event.error);
        }
      }
      fail("连接中断，这一轮的结果没有收到");
    } catch {
      fail("连接中断，这一轮的结果没有收到");
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (text && !running) void ask(text);
  }

  function shortcut(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <div className="chat-layout">
      <section className="panel chat-main" aria-label="对话">
        {turns.length === 0 ? (
          <p className="muted">
            可以问即将开赛的比赛、某队最近的状态、阵容伤停或模型成绩。回答里的数字会逐个核对本站数据；核对不上时，只列出查到的数据。
          </p>
        ) : (
          <ol className="chat-turns">
            {turns.map((turn) => (
              <li key={turn.id} className="chat-turn">
                <p className="chat-question">{turn.question}</p>
                {turn.status === "running" ? <p className="chat-progress">{turn.label}…</p> : null}
                {turn.status === "error" ? <p className="chat-alert">{turn.error}</p> : null}
                {turn.status === "done" ? (
                  <div className="chat-answer">
                    <span className={verified(turn.outcome ?? "") ? "pill pill-accent" : "pill pill-warning"}>
                      {OUTCOMES[turn.outcome ?? ""] ?? turn.outcome}
                    </span>
                    <div className="chat-output">{turn.answer}</div>
                    <p className="chat-cost">本轮花费 {dollars(turn.cost ?? 0)}</p>
                  </div>
                ) : null}
              </li>
            ))}
          </ol>
        )}
        <p className="sr-only" role="status" aria-live="polite">
          {announce}
        </p>
        <form className="chat-form" onSubmit={submit}>
          <label htmlFor="chat-question">你的问题</label>
          <textarea
            id="chat-question"
            value={question}
            maxLength={MAX_QUESTION}
            rows={3}
            placeholder="例如：Arsenal 下一场亚盘怎么看？"
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={shortcut}
          />
          <div className="chat-form-row">
            <span className="muted" aria-live="off">
              {question.length}/{MAX_QUESTION} · Ctrl/⌘ + Enter 发送
            </span>
            <div className="chat-actions">
              <button
                className="button"
                type="button"
                disabled={running || turns.length === 0}
                onClick={() => {
                  setTurns([]);
                  setThreadId(null);
                  setAnnounce("已开始新对话");
                }}
              >
                新对话
              </button>
              <button className="button button-primary" type="submit" disabled={running || !question.trim()}>
                {running ? "回答中…" : "发送"}
              </button>
            </div>
          </div>
        </form>
      </section>
      <aside className="panel chat-side" aria-label="额度">
        <h2>额度</h2>
        <p className="muted">已登录：{user}</p>
        <dl className="chat-quota">
          {quota.map((item) => (
            <div key={item.name} className="definition">
              <dt>{item.name}</dt>
              <dd>
                {dollars(item.used)} / {dollars(item.cap)}
              </dd>
            </div>
          ))}
        </dl>
        <p className="muted">每轮发出前按最坏花费预留，额度不够时这一轮不会调用模型。日额度按北京时间 0 点重置。</p>
        <form action={logout}>
          <button className="button" type="submit">
            退出登录
          </button>
        </form>
      </aside>
    </div>
  );
}
