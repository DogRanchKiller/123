export interface EntryPrediction {
  id: string;
  leagueName: string;
  home: string;
  away: string;
  statusLabel: string;
  kickoffUtc: string | null;
  probabilities: [number | null, number | null, number | null];
  over25: number | null;
  likelyScores: string[];
  lean: string;
  /** 亚盘选择文本，例如「主-1.00 52%」；无亚盘时为空。 */
  asianPick: string | null;
  fetchedAt: string | null;
  sourceNote: string;
}

export type EntryRead =
  | { status: "ok"; match: EntryPrediction | null; readAt: number }
  | { status: "error"; readAt: number };
