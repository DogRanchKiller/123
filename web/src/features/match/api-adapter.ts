/** 只读接口（OpenAPI 生成的类型）→ 页面展示契约。纯函数：不计算概率，只改字段名和展示文本。 */
import type { components } from "@/api/schema";
import { LEAGUE_CODES, type LeagueCode } from "./leagues";
import type {
  AsianHandicap,
  MatchRecord,
  MatchStatus,
  Prediction,
} from "./types";

type Schemas = components["schemas"];
export type ApiMatchView = Schemas["MatchView"];
export type ApiMatchDetail = Schemas["MatchDetail"];
export type ApiMatchList = Schemas["MatchList"];

/** 开球后多久仍算「比赛中」；之后没有比分则显示等待赛果。 */
const INPLAY_MS = 2.5 * 60 * 60 * 1000;

const INPLAY = {
  status: "not_connected",
  label: "滚球预测尚未接入",
  prediction: null,
} as const;

export function isLeague(code: string): code is LeagueCode {
  return (LEAGUE_CODES as readonly string[]).includes(code);
}

/** 队名缩写：多词取首字母，单词取前三个字母。 */
export function teamShort(name: string): string {
  const words = name.split(/[\s.\-']+/).filter(Boolean);
  const short =
    words.length > 1 ? words.map((word) => word[0]).join("") : name.slice(0, 3);
  return short.slice(0, 3).toUpperCase();
}

function scoreText(score: string): string {
  return score.replace("-", "–");
}

function triple(values: readonly (number | null)[]): [number, number, number] {
  return [values[0] ?? 0, values[1] ?? 0, values[2] ?? 0];
}

function asianOf(
  a: Schemas["AsianBase"] | Schemas["AsianCurrent"],
): AsianHandicap {
  const current = "movement" in a ? a : null;
  return {
    line: a.line,
    lineSource: a.line_source,
    outcome: {
      win: a.outcome.win,
      halfWin: a.outcome.half_win,
      push: a.outcome.push,
      halfLose: a.outcome.half_lose,
      lose: a.outcome.lose,
    },
    side: a.side,
    pCover: a.p_cover,
    tier: a.tier,
    historicalHit: a.historical_hit,
    selfHomeCover: current?.self_home_cover ?? null,
    movement: current?.movement ?? null,
  };
}

/** 本轮看法 → 当前预测。时间都取快照生成时间：数据源本身不给赔率时间。 */
export function currentOf(
  view: ApiMatchView,
  generatedAt: string | null,
): Prediction {
  const note = view.odds_source
    ? "由赛前市场赔率反推，亚盘按市场线五种结算；来自最近一次实盘运行。"
    : "本场暂无赔率，回退到自研模型（dc_xg）；亚盘为公平线，不分信心档。";
  return {
    modelName: view.model_name,
    modelVersion: view.model_version,
    probabilitySource: view.probability_source,
    scoreSource: view.score_source,
    oddsSource: view.odds_source,
    sourceNote: note,
    asian: asianOf(view.asian),
    confidence: view.confidence,
    historicalFirstHit: view.historical_first_hit,
    historicalDoubleHit: view.historical_double_hit,
    probabilities: triple(view.probabilities),
    lean: view.lean,
    double: view.double,
    likelyScores: view.likely_scores.map((s) => scoreText(s.score)),
    over25: view.over25,
    sourceAt: null,
    fetchedAt: generatedAt ?? "",
    generatedAt: generatedAt ?? "",
  };
}

function resultSource(src: string): string {
  return src === "fotmob" ? "FotMob，football-data 赛果到后核对" : src;
}

/** 开赛前首次存档 → 存档预测；赛后评分写在说明里。 */
export function archivedOf(a: Schemas["ArchivedPrediction"]): Prediction {
  const hasOdds = a.odds?.avg_h != null;
  const scored =
    a.scored && a.log_loss !== null
      ? `已评分：胜平负 Log Loss ${a.log_loss.toFixed(4)}` +
        (a.ah_log_loss !== null ? `，亚盘 Log Loss ${a.ah_log_loss.toFixed(4)}` : "") +
        (a.result_src ? `（赛果来源 ${resultSource(a.result_src)}）` : "")
      : "尚未评分：等待赛果";
  return {
    modelName: a.model_name,
    modelVersion: a.model_version,
    probabilitySource: hasOdds ? "市场（存档时赔率）" : "自研模型",
    scoreSource: hasOdds ? "市场隐含" : "自研模型",
    oddsSource: hasOdds ? "赛程表（存档时）" : null,
    sourceNote: `开赛前首次存档，后续刷新不覆盖。${scored}。`,
    asian: a.asian ? asianOf(a.asian) : null,
    confidence: a.confidence,
    historicalFirstHit: a.historical_first_hit,
    historicalDoubleHit: a.historical_double_hit,
    probabilities: triple(a.probabilities),
    lean: a.lean,
    double: a.double,
    likelyScores: a.likely_scores.map((s) => scoreText(s.score)),
    over25: a.over25,
    sourceAt: null,
    fetchedAt: a.generated_at,
    generatedAt: a.generated_at,
  };
}

function statusOf(
  base: Base,
  score: MatchRecord["score"],
  now: number,
): [MatchStatus, string] {
  if (score) return ["finished", "已完赛"];
  // 没有开球时间时按比赛日结束判断。
  const kickoff = Date.parse(base.kickoff_utc ?? base.match_date + "T23:59:59Z");
  if (Number.isNaN(kickoff) || kickoff > now) return ["upcoming", "未开赛"];
  if (now - kickoff < INPLAY_MS) return ["inplay", "已开球"];
  return ["finished", "已开球 · 等待赛果"];
}

interface Base {
  match_id: string;
  league: string;
  league_name: string;
  home: string;
  away: string;
  kickoff_utc: string | null;
  match_date: string;
  /** 只有 MatchInfo 有：比分抓取时间（football-data 或 FotMob）。 */
  score_fetched_at?: string | null;
}

function record(
  base: Base,
  current: ApiMatchView | null,
  archived: Prediction | null,
  score: MatchRecord["score"],
  generatedAt: string | null,
  now: number,
): MatchRecord | null {
  if (!isLeague(base.league)) return null;
  const [status, statusLabel] = statusOf(base, score, now);
  const risks = current ? [...current.risks, ...current.hints] : [];
  return {
    id: base.match_id,
    league: base.league,
    leagueName: base.league_name,
    home: base.home,
    away: base.away,
    homeShort: teamShort(base.home),
    awayShort: teamShort(base.away),
    kickoffUtc: base.kickoff_utc,
    status,
    statusLabel,
    recommended: current?.recommended ?? false,
    recommendationNote: current?.recommendation_note ?? null,
    current: current ? currentOf(current, generatedAt) : null,
    archived,
    score,
    scoreSourceAt: score ? (base.score_fetched_at ?? null) : null,
    inplay: INPLAY,
    risks: [...new Set(risks)],
  };
}

/** 比赛列表：本轮未开赛场次（当前看法）+ 最近已开球场次（首次存档与比分）；不在本站联赛表里的跳过。 */
export function matchesOf(list: ApiMatchList, now = Date.now()): MatchRecord[] {
  const upcoming = list.matches.map((view) =>
    record(view, view, null, null, list.generated_at, now),
  );
  const recent = list.recent.map(({ match, archived }) =>
    record(match, null, archivedOf(archived), match.score, list.generated_at, now),
  );
  return [...upcoming, ...recent].filter(
    (item): item is MatchRecord => item !== null,
  );
}

/** 单场详情：当前看法来自快照（最后一轮里有这场才有），存档来自首次预测。 */
export function detailOf(
  detail: ApiMatchDetail,
  now = Date.now(),
): MatchRecord | null {
  const archived = detail.archived ? archivedOf(detail.archived) : null;
  return record(
    detail.match,
    detail.current,
    archived,
    detail.match.score,
    detail.generated_at,
    now,
  );
}
