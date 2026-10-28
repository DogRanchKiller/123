import "server-only";
import type { ClosingRow, ReviewRow } from "./review";

export const demoReview: readonly ReviewRow[] = [
  {
    name: "market_implied",
    version: "1.3.0",
    matches: 120,
    logLoss: 0.9821,
    brier: 0.5843,
    hitRate: 0.542,
    asianMatches: 112,
    asianLogLoss: 0.9634,
    asianHit: 0.554,
    base: "market_avg",
    pairedMatches: 120,
    diffVsMarket: -0.0018,
    se: 0.0041,
  },
  {
    name: "market_avg",
    version: "1.1.0",
    matches: 120,
    logLoss: 0.9839,
    brier: 0.5856,
    hitRate: 0.542,
    asianMatches: 112,
    asianLogLoss: 0.9651,
    asianHit: 0.545,
    base: "market_avg",
    pairedMatches: null,
    diffVsMarket: null,
    se: null,
  },
  {
    name: "dc_xg",
    version: "1.0.0",
    matches: 120,
    logLoss: 1.0412,
    brier: 0.6171,
    hitRate: 0.508,
    asianMatches: 112,
    asianLogLoss: 1.0123,
    asianHit: 0.509,
    base: "market_avg",
    pairedMatches: 120,
    diffVsMarket: 0.0573,
    se: 0.0112,
  },
];

export const demoClosing: readonly ClosingRow[] = [
  { name: "closing_avg", version: "", pairedMatches: 118, logLoss: 0.9712, diffVsClose: null, se: null },
  { name: "market_implied", version: "1.3.0", pairedMatches: 118, logLoss: 0.9825, diffVsClose: 0.0113, se: 0.0052 },
  { name: "dc_xg", version: "1.0.0", pairedMatches: 118, logLoss: 1.0405, diffVsClose: 0.0693, se: 0.0118 },
];
