import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { closingRowsOf, primaryOf, reviewRowsOf, type ApiReview } from "./api-adapter";
import { Review } from "./review";

const row = {
  model_name: "market_implied", model_ver: "1.0.0", matches: 51,
  log_loss: 0.9541, brier: 0.5598, hit_rate: 0.588, ou25_ll: 0.68, score_ll: 2.92,
  ah_n: 51, ah_ll: 0.9634, ah_hit: 0.574, base: "market_avg", paired_n: 51, diff_vs_base: -0.0018, se: 0.0041,
};
const review: ApiReview = {
  generated_at: "2026-10-26T04:48:44+00:00", system_version: "1.10.0",
  primary_model: { name: "market_implied", version: "1.0.0" },
  scorecard: [row, { ...row, model_name: "market_avg", model_ver: "1.1.0", ah_n: 0,
    ah_ll: null, ah_hit: null, diff_vs_base: 0, se: 0 },
    { ...row, model_name: "market_avg_t1", model_ver: "1.1.0", base: "market_avg_t1", diff_vs_base: 0, se: 0 },
    { ...row, model_name: "market_implied_t1", base: "market_avg_t1", diff_vs_base: 0.0008, se: 0.005 }],
  closing: [
    { model_name: "closing_avg", model_ver: "", paired_n: 59, log_loss: 0.9254, diff_vs_close: 0, se: 0 },
    { model_name: "market_avg", model_ver: "1.1.0", paired_n: 59, log_loss: 0.9386, diff_vs_close: 0.0132, se: 0.0082 },
  ],
};

describe("成绩单接口 → 页面行", () => {
  it("改名并保留同场对比，基准自身不显示配对", () => {
    const [implied, base] = reviewRowsOf(review);
    expect(implied).toMatchObject({ name: "market_implied", asianMatches: 51, diffVsMarket: -0.0018, pairedMatches: 51 });
    expect(base).toMatchObject({ name: "market_avg", asianLogLoss: null, diffVsMarket: null, se: null, pairedMatches: null });
  });

  it("临场档对同一档的市场基准；该档基准自身不显示配对", () => {
    const [, , t1Base, t1] = reviewRowsOf(review);
    expect(t1Base).toMatchObject({ base: "market_avg_t1", diffVsMarket: null });
    expect(t1).toMatchObject({ base: "market_avg_t1", diffVsMarket: 0.0008, se: 0.005 });
  });

  it("旧快照没有 base 时按 market_avg 处理", () => {
    const old = { ...row, model_name: "market_avg", base: undefined };
    const [r] = reviewRowsOf({ ...review, scorecard: [old] });
    expect(r).toMatchObject({ base: "market_avg", diffVsMarket: null });
  });

  it("对收盘参照：收盘自身不显示差值", () => {
    const [close, avg] = closingRowsOf(review);
    expect(close).toMatchObject({ name: "closing_avg", pairedMatches: 59, diffVsClose: null, se: null });
    expect(avg).toMatchObject({ name: "market_avg", diffVsClose: 0.0132, se: 0.0082 });
    expect(closingRowsOf({ ...review, closing: [] })).toEqual([]);
  });
});

describe("成绩单标出主模型", () => {
  const live = { mode: "live", generatedAt: review.generated_at } as const;

  it("主模型有评分时标在对应行", () => {
    render(<Review rows={reviewRowsOf(review)} primary={primaryOf(review)} source={live} />);
    expect(screen.getAllByText("主模型")).toHaveLength(1);
    expect(screen.getByText("主模型").closest("tr")).toHaveClass("row-primary");
    expect(screen.getByText(/表中标「主模型」的一行/)).toBeInTheDocument();
  });

  it("主模型还没有评分时说明，版本不同不算", () => {
    const primary = { name: "market_implied", version: "2.0.0" };
    render(<Review rows={reviewRowsOf(review)} primary={primary} source={live} />);
    expect(screen.queryByText("主模型")).toBeNull();
    expect(screen.getByText(/还没有已评分的场次/)).toBeInTheDocument();
  });
});
