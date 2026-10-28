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
    side: "主", pCover: 0.57, tier: "高", historicalHit: 0.607, safeLine: null, safeCover: null, selfHomeCover: null, movement: null },
  confidence: "中", historicalFirstHit: 0.5, historicalDoubleHit: 0.7,
  probabilities: [0.48, 0.32, 0.2], lean: "主胜", double: "主胜或平", likelyScores: ["1–0"],
  over25: 0.4, sourceAt: null, fetchedAt: "2026-10-25T06:00:00Z", generatedAt: "2026-10-25T06:00:00Z",
};
const near: Prediction = {
  ...archive, modelName: "market_implied_t1", oddsSource: "多家中位数（5 家，存档时）",
  asian: { ...archive.asian!, line: -0.5, movement: "首次存档 主-0.25 → 临场 主-0.50；主队让球加深" },
};
const started: MatchRecord = { ...missing, status: "inplay", statusLabel: "已开球", archived: archive };

describe("重点标记", () => {
  it("未开赛且标为重点时卡片显示，开球后的存档不显示", () => {
    const hot = { ...missing, current: archive, recommended: true,
      recommendationNote: "胜平负高把握 · 主胜 70%" };
    const { rerender } = render(<MatchCard match={hot} />);
    expect(screen.getByText("★ 重点")).toHaveAttribute("title", "胜平负高把握 · 主胜 70%");
    rerender(<MatchCard match={{ ...hot, recommended: false }} />);
    expect(screen.queryByText("★ 重点")).toBeNull();
    rerender(<MatchCard match={{ ...started, recommended: true }} />);
    expect(screen.queryByText("★ 重点")).toBeNull();
  });
});

describe("概率来源", () => {
  it("来源就是模型本身时只写一次", () => {
    const own = { ...archive, modelName: "dc_dyn", probabilitySource: "动态攻防模型" };
    render(<MatchCard match={{ ...missing, current: own }} />);
    expect(screen.getAllByText("动态攻防模型")).toHaveLength(1);
    expect(screen.getByTitle("dc_dyn")).toHaveTextContent("动态攻防模型");
  });
});

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

describe("市场对照", () => {
  it("当前看法有市场去水时列在胜平负下方，存档没有时不显示", () => {
    const current: Prediction = { ...archive, modelName: "dc_dyn", probabilitySource: "动态攻防模型",
      marketProbabilities: [0.44, 0.3, 0.26] };
    const { unmount } = render(
      <MatchDetail data={{ match: { ...missing, current }, delayed: false, source: { mode: "demo" } }}
        action={null} />,
    );
    expect(screen.getByText(/市场对照（去水）/)).toHaveTextContent("主 44% · 平 30% · 客 26%");
    unmount();
    render(<MatchDetail data={{ match: started, delayed: false, source: { mode: "demo" } }} action={null} />);
    expect(screen.queryByText(/市场对照（去水）/)).toBeNull();
  });
});

describe("首次存档与当前预测相同", () => {
  const detail = (current: Prediction) =>
    render(<MatchDetail data={{ match: { ...missing, current, archived: archive }, delayed: false,
      source: { mode: "demo" } }} action={null} />);

  it("结论相同（时间和来源不同）时收起，展开后仍是完整内容", () => {
    const { container } = detail({ ...archive, generatedAt: "2026-10-25T09:00:00Z",
      fetchedAt: "2026-10-25T09:00:00Z", oddsSource: "多家中位数（5 家）", sourceNote: "按最新赔率现算。" });
    const folded = container.querySelector("details.prediction-collapsed");
    expect(folded).not.toBeNull();
    expect(folded).not.toHaveAttribute("open");
    expect(folded!.querySelector("summary")).toHaveTextContent("首次预测存档与当前预测相同");
    expect(folded).toHaveTextContent("开赛前首次存档。");
  });

  it("显示出来的任一结论不同就照常展开", () => {
    const { container, unmount } = detail({ ...archive, probabilities: [0.49, 0.31, 0.2] });
    expect(container.querySelector("details")).toBeNull();
    expect(screen.getAllByRole("heading", { name: "首次预测存档" })).toHaveLength(1);
    unmount();
    const other = detail({ ...archive, asian: { ...archive.asian!, line: -0.5 } });
    expect(other.container.querySelector("details")).toBeNull();
  });

  it("当前预测多出市场对照不影响判断（存档接口不带市场对照）", () => {
    const { container } = detail({ ...archive, marketProbabilities: [0.44, 0.3, 0.26],
      asian: { ...archive.asian!, marketHomeCover: 0.52 } });
    expect(container.querySelector("details.prediction-collapsed")).not.toBeNull();
  });

  it("按显示精度比较：千分位的差别看不出来时算相同", () => {
    const { container } = detail({ ...archive, probabilities: [0.4801, 0.3199, 0.2] });
    expect(container.querySelector("details.prediction-collapsed")).not.toBeNull();
  });
});
