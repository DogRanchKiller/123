import "server-only";
import type { ReviewRow } from "./review";

export const demoReview: readonly ReviewRow[] = [
  {
    name: "market_implied",
    version: "1.0.0",
    samples: 120,
    logLoss: "0.982",
    brier: "0.584",
    hitRate: "54.2%",
  },
  {
    name: "market_avg",
    version: "1.1.0",
    samples: 120,
    logLoss: "0.985",
    brier: "0.586",
    hitRate: "54.2%",
  },
  {
    name: "dc_xg",
    version: "1.0.0",
    samples: 120,
    logLoss: "1.041",
    brier: "0.617",
    hitRate: "50.8%",
  },
];
