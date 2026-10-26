import { describe, expect, it } from "vitest";
import { reviewRowsOf, type ApiReview } from "./api-adapter";

const row = {
  model_name: "market_implied", model_ver: "1.0.0", matches: 51,
  log_loss: 0.9541, brier: 0.5598, hit_rate: 0.588, ou25_ll: 0.68, score_ll: 2.92,
  ah_n: 51, ah_ll: 0.9634, ah_hit: 0.574, paired_n: 51, diff_vs_base: -0.0018, se: 0.0041,
};
const review: ApiReview = {
  generated_at: "2026-10-26T04:48:44+00:00", system_version: "1.10.0",
  primary_model: { name: "market_implied", version: "1.0.0" },
  scorecard: [row, { ...row, model_name: "market_avg", model_ver: "1.1.0", ah_n: 0,
    ah_ll: null, ah_hit: null, diff_vs_base: 0, se: 0 }],
};

describe("成绩单接口 → 页面行", () => {
  it("改名并保留同场对比，基准自身不显示配对", () => {
    const [implied, base] = reviewRowsOf(review);
    expect(implied).toMatchObject({ name: "market_implied", asianMatches: 51, diffVsMarket: -0.0018, pairedMatches: 51 });
    expect(base).toMatchObject({ name: "market_avg", asianLogLoss: null, diffVsMarket: null, se: null, pairedMatches: null });
  });
});
