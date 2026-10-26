import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MatchCard } from "./match-card";
import { MatchDetail } from "./match-detail";
import type { MatchRecord, Prediction } from "./types";

const missing: MatchRecord = {
  id: "demo-empty",
  league: "E0",
  leagueName: "英超",
  home: "主队",
  away: "客队",
  homeShort: "H",
  awayShort: "A",
  homeCrest: null,
  awayCrest: null,
  kickoffUtc: "2026-10-25T12:00:00Z",
  status: "upcoming",
  statusLabel: "未开赛",
  recommended: false,
  recommendationNote: null,
  current: null,
  archived: null,
  nearArchived: null,
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
      "主队 对 客队",
    );
  });
});

const archive: Prediction = {
  modelName: "market_implied", modelVersion: "1.1.0", probabilitySource: "市场（存档时赔率）",
  scoreSource: "市场隐含", oddsSource: "赛程表（存档时）", sourceNote: "开赛前首次存档。",
  asian: { line: -0.25, lineSource: "市场线",
    outcome: { win: 0.45, halfWin: 0, push: 0, halfLose: 0.25, lose: 0.3 },
    side: "主", pCover: 0.57, tier: "高", historicalHit: 0.607, selfHomeCover: null, movement: null },
  confidence: "中", historicalFirstHit: 0.5, historicalDoubleHit: 0.7,
  probabilities: [0.48, 0.32, 0.2], lean: "主胜", double: "主胜或平", likelyScores: ["1–0"],
  over25: 0.4, sourceAt: null, fetchedAt: "2026-10-25T06:00:00Z", generatedAt: "2026-10-25T06:00:00Z",
};
const near: Prediction = {
  ...archive, modelName: "market_implied_t1", oddsSource: "多家中位数（5 家，存档时）",
  asian: { ...archive.asian!, line: -0.5, movement: "首次存档 主-0.25 → 临场 主-0.50；主队让球加深" },
};
const started: MatchRecord = { ...missing, status: "inplay", statusLabel: "已开球", archived: archive };

describe("开球后显示存档", () => {
  it("卡片：临场档优先，没有时用首次存档，并标明是哪份", () => {
    const { rerender } = render(<MatchCard match={{ ...started, nearArchived: near }} />);
    expect(screen.getByText(/临场存档 · 概率来源/)).toHaveTextContent("市场隐含（临场）");
    expect(screen.getByText("主-0.50")).toBeInTheDocument();
    rerender(<MatchCard match={started} />);
    expect(screen.getByText(/首次存档 · 概率来源/)).toBeInTheDocument();
    rerender(<MatchCard match={{ ...started, archived: null }} />);
    expect(screen.getByText("赛前预测暂无存档")).toBeInTheDocument();
  });

  it("详情：两份存档都列出，盘口变化写在临场档里", () => {
    render(
      <MatchDetail data={{ match: { ...started, nearArchived: near }, delayed: false,
        source: { mode: "demo" } }} action={null} />,
    );
    expect(screen.getByRole("heading", { name: "临场存档" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "首次预测存档" })).toBeInTheDocument();
    expect(screen.getByText(/主队让球加深/)).toBeInTheDocument();
  });
});
