/** 实盘联赛，顺序与 Python `live.LEAGUES` 一致；代码沿用 football-data 的联赛代码。 */
export const LEAGUES = [
  { code: "E0", name: "英超" },
  { code: "D1", name: "德甲" },
  { code: "SP1", name: "西甲" },
  { code: "I1", name: "意甲" },
  { code: "F1", name: "法甲" },
  { code: "E1", name: "英冠" },
  { code: "N1", name: "荷甲" },
  { code: "P1", name: "葡超" },
  { code: "SC0", name: "苏超" },
  { code: "B1", name: "比甲" },
  { code: "T1", name: "土超" },
] as const;

export type LeagueCode = (typeof LEAGUES)[number]["code"];

export const LEAGUE_CODES: readonly string[] = LEAGUES.map((item) => item.code);

/** 页面标题、metadata 用的简短联赛说明。 */
export const LEAGUE_SUMMARY = "英超、德甲、西甲等 11 个联赛";
