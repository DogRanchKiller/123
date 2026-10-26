/** 页面展示契约（演示样本与实盘共用）。接口原始类型由 OpenAPI 生成在 `src/api/schema.d.ts`，
 * 经 `api-adapter.ts` 转成这里的形状；字段对应 Python `output/analysis.py` 的 analyse() 结果。 */
import type { DataSource } from "@/lib/display";
import type { LeagueCode } from "./leagues";

export type MatchStatus = "upcoming" | "inplay" | "finished";

/** 亚盘五种结算的概率，五项之和为 1；按主队方向。 */
export interface AsianOutcome {
  win: number;
  halfWin: number;
  push: number;
  halfLose: number;
  lose: number;
}

/** 亚盘块。线一律用主队方向的数字（负数 = 主队让球），前端不换算中文盘口名。 */
export interface AsianHandicap {
  line: number;
  /** 市场线：赔率里有亚盘；公平线：无市场亚盘时由比分矩阵取最接近五五开的线，不分档。 */
  lineSource: "市场线" | "公平线";
  outcome: AsianOutcome;
  /** 等效赢盘概率较高的一方；客队方向的线 = -line。 */
  side: "主" | "客";
  /** 选择方等效赢盘概率（走盘不计，半赢 / 半输各算一半）。 */
  pCover: number;
  /** 亚盘信心档；公平线时为 "-"。 */
  tier: "高" | "中" | "低" | "-";
  /** 该档历史赢盘命中率；公平线时为空。 */
  historicalHit: number | null;
  /** 稳妥线（主队方向）：从选择方的线每次退 0.25，直到选择方赢盘概率 ≥ 65%；没有时为空。 */
  safeLine: number | null;
  safeCover: number | null;
  /** 自研 dc_market 在同一条线上的主队赢盘概率，只作对照。 */
  selfHomeCover: number | null;
  /** 初盘 → 最新 → 定价的盘口与水位说明；不足两个阶段时为空。 */
  movement: string | null;
}

export interface Prediction {
  modelName: string;
  modelVersion: string;
  probabilitySource: string;
  scoreSource: string;
  /** 赔率来源，例如「多家中位数（5 家）」「赛程表」；无赔率时为空。 */
  oddsSource: string | null;
  sourceNote: string;
  asian: AsianHandicap | null;
  confidence: "高" | "中" | "低";
  historicalFirstHit: number;
  historicalDoubleHit: number;
  probabilities: [number, number, number];
  lean: string;
  double: string;
  likelyScores: string[];
  over25: number | null;
  sourceAt: string | null;
  fetchedAt: string;
  generatedAt: string;
}

export interface MatchRecord {
  id: string;
  league: LeagueCode;
  leagueName: string;
  home: string;
  away: string;
  /** 没有队徽时显示的文字标记。 */
  homeShort: string;
  awayShort: string;
  /** 本站静态队徽地址（/crests/{id}.png）；没有时为空。 */
  homeCrest: string | null;
  awayCrest: string | null;
  /** 赛程未给开球时间时为空。 */
  kickoffUtc: string | null;
  status: MatchStatus;
  statusLabel: string;
  recommended: boolean;
  recommendationNote: string | null;
  current: Prediction | null;
  /** 开赛前首次存档（赛前档，赛程表赔率），赛后评分以它为准。 */
  archived: Prediction | null;
  /** 临场存档（开球前 1.5 小时内多家中位数，模型名带 `_t1`）；没跑临场档时为空。 */
  nearArchived: Prediction | null;
  score: { home: number; away: number } | null;
  scoreSourceAt: string | null;
  inplay: {
    status: "not_connected";
    label: string;
    prediction: Prediction | null;
  };
  risks: string[];
}

export interface MatchRead {
  match: MatchRecord;
  delayed: boolean;
  source: DataSource;
}

export interface MatchList {
  matches: readonly MatchRecord[];
  source: DataSource;
}
