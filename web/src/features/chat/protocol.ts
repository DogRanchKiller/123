/** 网站与 agent.serve 之间的对话协议（agent/serve.py）。客户端和服务端共用，不含密钥。 */

/** 会话 Cookie：值是 agent.serve 发的随机会话 id，库里只存哈希。 */
export const SESSION_COOKIE = "fp_chat";
/** 与 agent/serve.py 的 MAX_QUESTION 一致。 */
export const MAX_QUESTION = 500;
/** 与 agent/serve.py 的 THREAD_ID 一致。 */
export const THREAD_ID = /^[0-9a-f]{8,32}$/;

export interface Quota {
  name: string;
  used: number;
  cap: number;
}

export type ChatEvent =
  | { type: "step"; node: string; label: string; tools?: string[] }
  | {
      type: "done";
      thread_id: string;
      output: string;
      outcome: string;
      cost: number;
      quota: Quota[];
    }
  | { type: "error"; error: string }
  /** 久无进度时的保活行，页面忽略。 */
  | { type: "ping" };

/** 一轮的结局（agent/graph.py）。只有 passed / passed_retry 是核对过数字的回答。 */
export const OUTCOMES: Record<string, string> = {
  passed: "数字已核对",
  passed_retry: "数字已核对（重答一次）",
  degraded: "没能核对回答里的数字，只列出查到的数据",
  timeout: "超时，只列出查到的数据",
  refused: "额度或次数用完，只列出查到的数据",
  error: "模型调用失败，只列出查到的数据",
};

export function verified(outcome: string): boolean {
  return outcome === "passed" || outcome === "passed_retry";
}

/** 按行解析 NDJSON 流；半行留到下一块，空行跳过。 */
export async function* readEvents(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<ChatEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = done ? "" : (lines.pop() ?? "");
    for (const line of lines) if (line.trim()) yield JSON.parse(line) as ChatEvent;
    if (done) return;
  }
}

export function dollars(value: number): string {
  return `$${value > 0 && value < 0.1 ? value.toFixed(4) : value.toFixed(2)}`;
}
