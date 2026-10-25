export interface EntryPrediction {
  id: string;
  leagueName: string;
  home: string;
  away: string;
  statusLabel: string;
  kickoffUtc: string;
  probabilities: [number | null, number | null, number | null];
  over25: number | null;
  likelyScores: string[];
  lean: string;
  fetchedAt: string | null;
  sourceNote: string;
}

export type EntryRead =
  | { status: "ok"; match: EntryPrediction | null; readAt: number }
  | { status: "error"; readAt: number };
