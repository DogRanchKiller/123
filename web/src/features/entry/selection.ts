import type { MatchRecord } from "@/features/match";
import type { EntryPrediction } from "./types";

export function selectEntryPrediction(matches: readonly MatchRecord[]): EntryPrediction | null {
  const eligible = (match: MatchRecord) => match.status === "upcoming" && match.current !== null;
  const match = matches.find((item) => eligible(item) && item.recommended) ?? matches.find(eligible);
  if (!match?.current) return null;
  const { probabilities, over25, likelyScores, lean, fetchedAt, sourceNote } = match.current;
  return {
    id: match.id, leagueName: match.leagueName, home: match.home, away: match.away,
    statusLabel: match.statusLabel, kickoffUtc: match.kickoffUtc,
    probabilities, over25, likelyScores, lean, fetchedAt, sourceNote,
  };
}
