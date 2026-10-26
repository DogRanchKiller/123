/** 只读接口（OpenAPI 生成的类型）→ 页面展示契约。纯函数：不计算概率，只改字段名和展示文本。 */
import type { components } from "@/api/schema";
import { zhText } from "@/lib/models";
import { lineText } from "./asian";
import { LEAGUE_CODES, type LeagueCode } from "./leagues";
import { crestOf, teamShort, teamZh } from "./teams";
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
    safeLine: a.safe_line ?? null,
    safeCover: a.safe_cover ?? null,
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
    : "本场暂无赔率，回退到自研的预期进球模型；亚盘为公平线，不分信心档。";
  return {
    modelName: view.model_name,
    modelVersion: view.model_version,
    probabilitySource: zhText(view.probability_source),
    scoreSource: zhText(view.score_source),
    oddsSource: view.odds_source && zhText(view.odds_source),
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

type ApiArchive = Schemas["ArchivedPrediction"];

/** 存档的赔率来源：赛前档是赛程表，临场档是多家中位数。 */
function archiveOdds(a: ApiArchive): string {
  if (a.horizon !== "t1") return "赛程表（存档时）";
  return a.n_books ? `多家中位数（${a.n_books} 家，存档时）` : "多家中位数（存档时）";
}

function archiveNote(a: ApiArchive, scored: string): string {
  if (a.horizon !== "t1") return `开赛前首次存档，后续刷新不覆盖。${scored}。`;
  const lead = a.hours_to_ko != null ? `开球前 ${a.hours_to_ko.toFixed(1)} 小时` : "开球前 1.5 小时内";
  return `临场存档（${lead}），只存一次。赛后评分以首次存档为准，临场档另行配对比较。${scored}。`;
}

/** 首次存档 → 临场存档的亚盘线变化；任一边没有亚盘时为空。 */
function lineMove(first: ApiArchive | null, near: ApiArchive | null): string | null {
  const a = first?.asian?.line, b = near?.asian?.line;
  if (a == null || b == null) return null;
  // 按让球方说变化：线变小 = 往主队方向移，主让时是让得更深，主受让时是受让变少
  let dir = "盘口未变";
  if (a !== b) {
    if (a * b < 0) dir = "让球方换边";
    else if (Math.min(a, b) < 0) dir = b < a ? "主队让球加深" : "主队让球变浅";
    else dir = b < a ? "主队受让变少" : "主队受让变多";
  }
  return `首次存档 ${lineText(a)} → 临场 ${lineText(b)}；${dir}`;
}

/** 开赛前存档（首次存档或临场档）→ 存档预测；赛后评分写在说明里。 */
export function archivedOf(a: ApiArchive, movement: string | null = null): Prediction {
  const hasOdds = a.odds?.avg_h != null;
  const scored =
    a.scored && a.log_loss !== null
      ? `已评分：胜平负对数损失 ${a.log_loss.toFixed(4)}` +
        (a.ah_log_loss !== null ? `，亚盘对数损失 ${a.ah_log_loss.toFixed(4)}` : "") +
        (a.result_src ? `（赛果来源 ${resultSource(a.result_src)}）` : "")
      : "尚未评分：等待赛果";
  return {
    modelName: a.model_name,
    modelVersion: a.model_version,
    probabilitySource: hasOdds ? "市场（存档时赔率）" : "自研模型",
    scoreSource: hasOdds ? "市场隐含" : "自研模型",
    oddsSource: hasOdds ? archiveOdds(a) : null,
    sourceNote: archiveNote(a, scored),
    asian: a.asian ? { ...asianOf(a.asian), movement } : null,
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
  archives: [ApiArchive | null, ApiArchive | null],
  score: MatchRecord["score"],
  generatedAt: string | null,
  now: number,
): MatchRecord | null {
  if (!isLeague(base.league)) return null;
  const [status, statusLabel] = statusOf(base, score, now);
  const risks = current ? [...current.risks, ...current.hints].map(zhText) : [];
  const [first, near] = archives;
  return {
    id: base.match_id,
    league: base.league,
    leagueName: base.league_name,
    home: teamZh(base.home),
    away: teamZh(base.away),
    homeShort: teamShort(base.home),
    awayShort: teamShort(base.away),
    homeCrest: crestOf(base.home),
    awayCrest: crestOf(base.away),
    kickoffUtc: base.kickoff_utc,
    status,
    statusLabel,
    recommended: current?.recommended ?? false,
    recommendationNote: current?.recommendation_note ?? null,
    current: current ? currentOf(current, generatedAt) : null,
    archived: first ? archivedOf(first) : null,
    nearArchived: near ? archivedOf(near, lineMove(first, near)) : null,
    score,
    scoreSourceAt: score ? (base.score_fetched_at ?? null) : null,
    inplay: INPLAY,
    risks: [...new Set(risks)],
  };
}

/** 比赛列表：本轮未开赛场次（当前看法）+ 最近已开球场次（首次存档与比分）；不在本站联赛表里的跳过。 */
export function matchesOf(list: ApiMatchList, now = Date.now()): MatchRecord[] {
  const upcoming = list.matches.map((view) =>
    record(view, view, [null, null], null, list.generated_at, now),
  );
  const recent = list.recent.map(({ match, archived, near_archived }) =>
    record(match, null, [archived, near_archived ?? null], match.score, list.generated_at, now),
  );
  return [...upcoming, ...recent].filter(
    (item): item is MatchRecord => item !== null,
  );
}

/** 单场详情：当前看法来自快照（最后一轮里有这场才有），存档来自首次预测与临场档。 */
export function detailOf(
  detail: ApiMatchDetail,
  now = Date.now(),
): MatchRecord | null {
  return record(
    detail.match,
    detail.current,
    [detail.archived, detail.near_archived ?? null],
    detail.match.score,
    detail.generated_at,
    now,
  );
}
