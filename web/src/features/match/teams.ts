/**
 * 球队展示：本库队名（football-data 写法）→ 中文名与队徽。只改显示，不参与任何计算。
 * 队徽由 `_diag/web_crests.py` 从 FotMob 下载到 public/crests/{id}.png，crests.json 记队名 → FotMob 球队 id。
 * 表里没有的队（升班马等）显示原名，队徽位置用名字前两个字。
 * 中文名表 team-zh.json 是 football_prediction/data/team_zh.json 的副本（Agent 的 resolve_team 用那份），
 * 两份由 tests/test_team_zh.py 检查一致；补队名时两份一起改。
 */
import crests from "./crests.json";
import teamZhTable from "./team-zh.json";

const ZH: Readonly<Record<string, string>> = teamZhTable;

const CRESTS: Readonly<Record<string, string>> = crests;

/** 中文队名；表里没有时原样返回。 */
export function teamZh(name: string): string {
  return ZH[name] ?? name;
}

/** 队徽地址；没有下载到时为空。 */
export function crestOf(name: string): string | null {
  const id = CRESTS[name];
  return id ? `/crests/${id}.png` : null;
}

/** 没有队徽时的文字标记：中文名取前两个字，其余取英文首字母。 */
export function teamShort(name: string): string {
  const zh = ZH[name];
  if (zh) return zh.slice(0, 2);
  const words = name.split(/[\s.\-']+/).filter(Boolean);
  const short =
    words.length > 1 ? words.map((word) => word[0]).join("") : name.slice(0, 3);
  return short.slice(0, 3).toUpperCase();
}
