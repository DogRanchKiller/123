/** 仅供演示页面的展示契约；真实接口类型未来由 OpenAPI 生成。 */
export type MatchStatus = "upcoming" | "inplay" | "finished";

export interface Prediction {
  modelName: string;
  modelVersion: string;
  probabilitySource: string;
  scoreSource: string;
  sourceNote: string;
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
  league: "E0" | "D1" | "SP1";
  leagueName: string;
  home: string;
  away: string;
  homeShort: string;
  awayShort: string;
  kickoffUtc: string;
  status: MatchStatus;
  statusLabel: string;
  recommended: boolean;
  recommendationNote: string | null;
  current: Prediction | null;
  archived: Prediction | null;
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
}
