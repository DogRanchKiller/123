import { describe, expect, it } from "vitest";
import {
  detailOf,
  matchesOf,
  type ApiMatchDetail,
  type ApiMatchList,
  type ApiMatchView,
} from "./api-adapter";
import { crestOf, teamShort, teamZh } from "./teams";

const outcome = { win: 0.4, half_win: 0.1, push: 0, half_lose: 0.1, lose: 0.4 };
const view: ApiMatchView = {
  match_id: "E0_2627_Arsenal_Chelsea", league: "E0", league_name: "英超",
  home: "Arsenal", away: "Chelsea", kickoff_utc: "2026-11-02T16:30:00+00:00",
  match_date: "2026-11-02", model_name: "dc_dyn", model_version: "1.0.0",
  recommended: true, recommendation_note: "胜平负高把握 · 主胜 55% · 亚盘稳妥 主+0.00 66%",
  odds_source: "多家中位数（5 家）",
  asian: {
    line: -0.75, line_source: "市场线", outcome, side: "主", p_cover: 0.57,
    tier: "高", historical_hit: 0.58, safe_line: 0, safe_cover: 0.66, self_home_cover: 0.55,
    market_home_cover: 0.52, implied_home_cover: 0.53, movement: "初盘 主-0.50 → 最新 主-0.75",
  },
  probabilities: [0.55, 0.25, 0.2], market_probabilities: [0.5, 0.27, 0.23],
  probability_source: "dc_dyn", score_source: "dc_dyn", lean: "主胜", double: "主胜或平", confidence: "中",
  historical_first_hit: 0.6, historical_double_hit: 0.8,
  estimated_first_hit: null, estimated_double_hit: null,
  expected_goals: [1.6, 1.1], likely_scores: [{ score: "1-0", prob: 0.11 }],
  over25: 0.55, btts: 0.5, self_models: {}, movement: null,
  hints: ["市场与 dc_dyn 分歧：主胜 9pp"], risks: ["高信心档历史上仍约有四成未命中。"],
};
const list: ApiMatchList = {
  generated_at: "2026-10-26T10:37:00+00:00", system_version: "1.10.0",
  primary_model: { name: "dc_dyn", version: "1.0.0" },
  matches: [view, { ...view, match_id: "x", league: "MLS" }],
  recent: [],
};
const now = Date.parse("2026-10-26T12:00:00Z");

describe("接口 → 展示契约", () => {
  it("列表：字段改名、比分换短横、提示并入风险，未知联赛跳过", () => {
    const [m, ...rest] = matchesOf(list, now);
    expect(rest).toHaveLength(0);
    expect(m.status).toBe("upcoming");
    expect(m.home).toBe("阿森纳");
    expect(m.homeShort).toBe("阿森");
    expect(m.homeCrest).toMatch(/^\/crests\/\d+\.png$/);
    expect(m.recommended).toBe(true);
    expect(m.current?.asian).toMatchObject({ line: -0.75, lineSource: "市场线" });
    expect(m.current?.asian?.outcome.halfWin).toBe(0.1);
    expect(m.current?.asian?.selfHomeCover).toBe(0.55);
    expect(m.current?.asian?.marketHomeCover).toBe(0.53);        // 市场隐含优先于水位去水
    expect(m.current?.marketProbabilities).toEqual([0.5, 0.27, 0.23]);
    expect(m.current?.probabilitySource).toBe("动态攻防模型");
    expect(m.current?.asian).toMatchObject({ safeLine: 0, safeCover: 0.66 });
    expect(m.current?.likelyScores).toEqual(["1–0"]);
    expect(m.current?.generatedAt).toBe(list.generated_at);
    expect(m.risks).toEqual([...view.risks, "市场与动态攻防模型分歧：主胜 9 个百分点"]);
    expect(m.archived).toBeNull();
  });

  it("详情：已完赛用存档，赛前看法为空时不推荐", () => {
    const m = detailOf(detail, now)!;
    expect(m.status).toBe("finished");
    expect(m.home).toBe("拜仁慕尼黑");
    expect(m.recommended).toBe(false);
    expect(m.current).toBeNull();
    expect(m.archived?.asian?.selfHomeCover).toBeNull();
    expect(m.archived?.asian?.safeLine ?? null).toBeNull();   // 旧接口没有稳妥线字段
    expect(m.archived?.sourceNote).toContain("0.5100");
    expect(m.archived?.oddsSource).toBe("赛程表（存档时）");
    expect(m.archived?.probabilitySource).toBe("市场（存档时赔率）");   // 2.0.0 之前的市场隐含存档
    expect(m.scoreSourceAt).toBe("2026-10-21T06:00:00+00:00");
  });

  it("主模型存档：概率来源写模型名，不当作市场；没有市场对照", () => {
    const m = detailOf({ ...detail, archived: { ...detail.archived!, model_name: "dc_dyn" } }, now)!;
    expect(m.archived?.probabilitySource).toBe("动态攻防模型");
    expect(m.archived?.scoreSource).toBe("动态攻防模型");
    expect(m.archived?.oddsSource).toBe("赛程表（存档时）");
    expect(m.archived?.asian?.marketHomeCover).toBeNull();
  });

  it("无赔率的看法：没有市场对照", () => {
    const [m] = matchesOf({ ...list, matches: [{ ...view, odds_source: null, market_probabilities: null,
      asian: { ...view.asian, market_home_cover: null, implied_home_cover: null } }] }, now);
    expect(m.current?.marketProbabilities).toBeNull();
    expect(m.current?.asian?.marketHomeCover).toBeNull();
    expect(m.current?.sourceNote).toContain("没有市场对照");
  });

  it("列表附带最近已开球场次：用首次存档和比分，FotMob 赛果标明待核对", () => {
    const recent = { match: { ...detail.match, score: null, kickoff_utc: "2026-10-26T11:00:00Z" },
      archived: { ...detail.archived!, result_src: null, scored: false, log_loss: null } };
    const fotmob = { match: { ...detail.match, match_id: "m2", score_source: "fotmob" as const },
      archived: { ...detail.archived!, result_src: "fotmob" } };
    const [up, inplay, done] = matchesOf({ ...list, recent: [recent, fotmob] }, now);
    expect(up.status).toBe("upcoming");
    expect(inplay.status).toBe("inplay");
    expect(inplay.current).toBeNull();
    expect(inplay.archived?.sourceNote).toContain("尚未评分");
    expect(done.status).toBe("finished");
    expect(done.score).toEqual({ home: 2, away: 1 });
    expect(done.archived?.sourceNote).toContain("FotMob，football-data 赛果到后核对");
  });
});

const detail: ApiMatchDetail = {
  generated_at: list.generated_at, current: null,
  match: { match_id: "m1", league: "D1", league_name: "德甲", home: "Bayern Munich",
    away: "Dortmund", kickoff_utc: null, match_date: "2026-10-20", score: { home: 2, away: 1 },
    score_source: "football-data", score_fetched_at: "2026-10-21T06:00:00+00:00" },
  archived: {
    model_name: "market_implied", model_version: "1.1.0",
    generated_at: "2026-10-19T10:00:00+00:00", kickoff_utc: null,
    probabilities: [0.6, 0.22, 0.18], lean: "主胜", double: "主胜或平",
    confidence: "高", historical_first_hit: 0.7, historical_double_hit: 0.9,
    asian: { line: -1, line_source: "市场线", outcome, side: "主", p_cover: 0.55, tier: "中", historical_hit: 0.56 },
    likely_scores: [{ score: "2-1", prob: 0.1 }], over25: 0.6,
    odds: { avg_h: 1.6, avg_d: 4, avg_a: 5, ah_line: -1 },
    scored: true, actual_outcome: "home_win", log_loss: 0.51, brier: 0.2,
    ou25_log_loss: 0.6, score_log_loss: 2.1, ah_log_loss: 0.9, ah_hit: 1,
    result_src: "football-data", scored_at: "2026-10-21T00:00:00+00:00", horizon: "pre",
  },
};

describe("接口 → 展示契约：临场存档", () => {
  const near = {
    ...detail.archived!, model_name: "market_implied_t1", horizon: "t1" as const,
    n_books: 5, hours_to_ko: 1.2, generated_at: "2026-10-20T12:00:00+00:00",
    asian: { ...detail.archived!.asian!, line: -1.25 },
  };

  it("临场档标明多家中位数与开球前时长，亚盘线变化写进盘口变动", () => {
    const m = detailOf({ ...detail, near_archived: near }, now)!;
    expect(m.archived?.asian?.movement).toBeNull();
    expect(m.nearArchived?.modelName).toBe("market_implied_t1");
    expect(m.nearArchived?.oddsSource).toBe("多家中位数（5 家，存档时）");
    expect(m.nearArchived?.sourceNote).toContain("开球前 1.2 小时");
    expect(m.nearArchived?.asian?.movement).toBe(
      "首次存档 主-1.00 → 临场 主-1.25；主队让球加深");
    const up = (line: number) => detailOf({ ...detail, archived: { ...detail.archived!,
      asian: { ...detail.archived!.asian!, line: 1.5 } },
      near_archived: { ...near, asian: { ...near.asian!, line } } }, now)!.nearArchived?.asian?.movement;
    expect(up(1.25)).toContain("主队受让变少");
    expect(up(1.75)).toContain("主队受让变多");
    expect(up(-0.25)).toContain("让球方换边");
    const same = detailOf({ ...detail, near_archived: { ...near, asian: detail.archived!.asian } }, now)!;
    expect(same.nearArchived?.asian?.movement).toContain("盘口未变");
  });

  it("没有临场档时为空；列表的最近场次同样带上", () => {
    expect(detailOf(detail, now)!.nearArchived).toBeNull();
    const [, recent] = matchesOf({ ...list, recent: [
      { match: detail.match, archived: detail.archived!, near_archived: near }] }, now);
    expect(recent.nearArchived?.asian?.line).toBe(-1.25);
    expect(recent.archived?.oddsSource).toBe("赛程表（存档时）");
  });
});

describe("接口 → 展示契约：状态与缩写", () => {
  it("开球后没有比分：先是比赛中，超过时限为等待赛果", () => {
    const kicked = { ...view, kickoff_utc: "2026-10-26T11:00:00Z" };
    const late = { ...view, kickoff_utc: "2026-10-26T08:00:00Z" };
    const [a, b] = matchesOf({ ...list, matches: [kicked, late] }, now);
    expect(a.status).toBe("inplay");
    expect(b.statusLabel).toBe("已开球 · 等待赛果");
  });

  it("队名：中文名、缩写、队徽；表里没有的队用原名和英文缩写", () => {
    expect(teamZh("Man City")).toBe("曼城");
    expect(teamShort("Lens")).toBe("朗斯");
    expect(teamZh("Some United")).toBe("Some United");
    expect(teamShort("Some United")).toBe("SU");
    expect(teamShort("Lensx")).toBe("LEN");
    expect(crestOf("Some United")).toBeNull();
  });
});
