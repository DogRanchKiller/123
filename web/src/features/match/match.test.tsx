import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MatchDetail } from "./match-detail";
import type { MatchRecord } from "./types";

const missing: MatchRecord = {
  id: "demo-empty",
  league: "E0",
  leagueName: "英超",
  home: "主队",
  away: "客队",
  homeShort: "H",
  awayShort: "A",
  kickoffUtc: "2026-10-25T12:00:00Z",
  status: "upcoming",
  statusLabel: "未开赛",
  recommended: false,
  recommendationNote: null,
  current: null,
  archived: null,
  score: null,
  scoreSourceAt: null,
  inplay: {
    status: "not_connected",
    label: "滚球预测尚未接入",
    prediction: null,
  },
  risks: [],
};

describe("缺失数据", () => {
  it("缺比分和模型不伪造零或概率，显示北京时间", () => {
    render(
      <MatchDetail data={{ match: missing, delayed: false, source: { mode: "demo" } }} action={null} />,
    );
    expect(screen.getByText("比分暂无数据")).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { name: "暂无数据" })).toHaveLength(
      2,
    );
    expect(screen.getByText(/20:00 开球/)).toBeInTheDocument();
    expect(screen.queryByLabelText("胜平负概率")).not.toBeInTheDocument();
  });

  it("延迟标识与比赛存在分开", () => {
    render(
      <MatchDetail data={{ match: missing, delayed: true, source: { mode: "demo" } }} action={null} />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("更新延迟");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "主队 vs 客队",
    );
  });
});
