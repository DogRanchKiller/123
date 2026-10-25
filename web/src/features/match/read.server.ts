import "server-only";
import { cache } from "react";
import { readFile } from "node:fs/promises";
import { demoMatches } from "./demo-data.server";
import type { MatchRead, MatchRecord } from "./types";

// 仅演示服务进程内最近一次成功读取；真实接入时由后端持久缓存提供。
const previous = new Map<string, MatchRecord>();

export function readDemoMatches(): readonly MatchRecord[] {
  return demoMatches;
}

async function shouldFail(id: string): Promise<boolean> {
  const file = process.env.WEB_TEST_CONTROL_FILE;
  if (!file) return false;
  const control: { failIds?: string[] } = JSON.parse(
    await readFile(file, "utf8"),
  );
  return control.failIds?.includes(id) ?? false;
}

export const readDemoMatch = cache(
  async (id: string): Promise<MatchRead | null> => {
    const match = demoMatches.find((item) => item.id === id);
    if (!match) return null;
    try {
      if (await shouldFail(id)) throw new Error("演示数据读取暂时不可用");
      previous.set(id, match);
      return { match, delayed: false };
    } catch (error) {
      const last = previous.get(id);
      if (last) return { match: last, delayed: true };
      throw error;
    }
  },
);
