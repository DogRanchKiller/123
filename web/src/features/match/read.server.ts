import "server-only";
import { cache } from "react";
import { readFile } from "node:fs/promises";
import { apiBase, getJson } from "@/lib/api.server";
import { DEMO_SOURCE } from "@/lib/display";
import {
  detailOf,
  matchesOf,
  type ApiMatchDetail,
  type ApiMatchList,
} from "./api-adapter";
import { demoMatches } from "./demo-data.server";
import type { MatchList, MatchRead } from "./types";

// 未配置 API_URL 时读固定演示样本；配置后读本机只读接口（python -m server）。
// 服务进程内保留每场最近一次成功读取：接口暂时失败时显示旧结果并标记延迟。
const previous = new Map<string, MatchRead>();

async function shouldFail(id: string): Promise<boolean> {
  const file = process.env.WEB_TEST_CONTROL_FILE;
  if (!file) return false;
  const control: { failIds?: string[] } = JSON.parse(
    await readFile(file, "utf8"),
  );
  return control.failIds?.includes(id) ?? false;
}

/** 比赛列表；接口失败时抛错，由路由错误页返回 5xx。 */
export const readMatches = cache(async (): Promise<MatchList> => {
  const base = await apiBase();
  if (!base) return { matches: demoMatches, source: DEMO_SOURCE };
  const list = await getJson<ApiMatchList>(base, "/api/matches");
  if (!list) throw new Error("只读接口没有 /api/matches");
  return {
    matches: matchesOf(list),
    source: { mode: "live", generatedAt: list.generated_at },
  };
});

async function fetchMatch(id: string): Promise<MatchRead | null> {
  const base = await apiBase();
  if (!base) {
    const match = demoMatches.find((item) => item.id === id);
    if (!match) return null;
    if (await shouldFail(id)) throw new Error("演示数据读取暂时不可用");
    return { match, delayed: false, source: DEMO_SOURCE };
  }
  const detail = await getJson<ApiMatchDetail>(
    base,
    "/api/matches/" + encodeURIComponent(id),
  );
  const match = detail ? detailOf(detail) : null;
  if (!detail || !match) return null;
  return {
    match,
    delayed: false,
    source: { mode: "live", generatedAt: detail.generated_at },
  };
}

/** 单场；找不到返回 null（404）。读取失败时有旧结果就返回旧结果并标记延迟，否则抛错（5xx）。 */
export const readMatch = cache(
  async (id: string): Promise<MatchRead | null> => {
    try {
      const data = await fetchMatch(id);
      if (data) previous.set(id, data);
      return data;
    } catch (error) {
      const last = previous.get(id);
      if (last) return { ...last, delayed: true };
      throw error;
    }
  },
);
