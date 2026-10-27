import { describe, expect, it } from "vitest";
import { dollars, readEvents, type ChatEvent } from "./protocol";

function stream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect(chunks: string[]): Promise<ChatEvent[]> {
  const out: ChatEvent[] = [];
  for await (const event of readEvents(stream(chunks))) out.push(event);
  return out;
}

describe("readEvents", () => {
  it("跨块的半行拼回来", async () => {
    const line = JSON.stringify({ type: "step", node: "tools", label: "查数据" }) + "\n";
    const events = await collect([line.slice(0, 10), line.slice(10, 30), line.slice(30)]);
    expect(events).toEqual([{ type: "step", node: "tools", label: "查数据" }]);
  });

  it("空行跳过，最后一行没有换行也收", async () => {
    const events = await collect(['{"type":"ping"}\n\n{"type":"step","node":"agent","label":"思考中"}\n', '{"type":"error","error":"x"}']);
    expect(events.map((event) => event.type)).toEqual(["ping", "step", "error"]);
  });

  it("按字节切开的多字节字符也能拼回来", async () => {
    const bytes = new TextEncoder().encode('{"type":"error","error":"服务出错"}\n');
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
        controller.close();
      },
    });
    const out: ChatEvent[] = [];
    for await (const event of readEvents(body)) out.push(event);
    expect(out).toEqual([{ type: "error", error: "服务出错" }]);
  });
});

describe("dollars", () => {
  it("小额保留四位", () => {
    expect(dollars(0.0042)).toBe("$0.0042");
    expect(dollars(0)).toBe("$0.00");
    expect(dollars(2)).toBe("$2.00");
  });
});
