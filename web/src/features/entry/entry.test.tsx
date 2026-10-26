import { act, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MatchRecord, Prediction } from "@/features/match";
import { EntryScreen } from "./entry-screen.client";
import { selectEntryPrediction } from "./selection";
import type { EntryPrediction, EntryRead } from "./types";

const mocks = vi.hoisted(() => ({ refresh: vi.fn(), mounts: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/" }));
const router = { refresh: mocks.refresh };
vi.mock("next/dynamic", () => ({ default: () => function Scene() {
  useEffect(() => { mocks.mounts(); }, []);
  return <canvas data-testid="scene" />;
} }));

const prediction: Prediction = {
  modelName:"sample", modelVersion:"1", probabilitySource:"market", scoreSource:"sample",
  sourceNote:"测试来源", oddsSource:"赛程表", asian:{
    line:-0.25, lineSource:"市场线", outcome:{win:.45,halfWin:0,push:0,halfLose:.25,lose:.3},
    side:"主", pCover:.57, tier:"高", historicalHit:.607, selfHomeCover:null, movement:null,
  }, confidence:"中", historicalFirstHit:.5, historicalDoubleHit:.7,
  probabilities:[.48,.32,.2], lean:"主胜", double:"主胜或平", likelyScores:["1–0","1–1"],
  over25:.35, sourceAt:null, fetchedAt:"2026-10-25T10:00:00Z", generatedAt:"2026-10-25T10:01:00Z",
};
const fixture: MatchRecord = {
  id:"one", league:"E0", leagueName:"测试联赛", home:"队伍甲", away:"队伍乙", homeShort:"H", awayShort:"A", homeCrest:null, awayCrest:null,
  kickoffUtc:"2026-10-26T12:00:00Z", status:"upcoming", statusLabel:"未开赛", recommended:false,
  recommendationNote:null, current:prediction, archived:{ ...prediction, probabilities:[.9,.05,.05] }, nearArchived:null,
  score:null, scoreSourceAt:null, inplay:{status:"not_connected",label:"未接入",prediction:null}, risks:[],
};
const match = selectEntryPrediction([fixture])!;
const ok = (readAt: number, value: EntryPrediction | null = match): EntryRead => ({status:"ok", readAt, match:value});
function visibility(value: "visible" | "hidden") {
  Object.defineProperty(document,"visibilityState",{configurable:true,value});
  act(() => document.dispatchEvent(new Event("visibilitychange")));
}
beforeEach(() => { vi.useFakeTimers(); visibility("visible"); });
afterEach(() => { vi.useRealTimers(); });

describe("首页选场契约", () => {
  it("推荐优先，保留原顺序，只读未开赛 current", () => {
    const recommended = {...fixture,id:"recommended",recommended:true};
    expect(selectEntryPrediction([fixture,recommended,{...recommended,id:"last"}])?.id).toBe("recommended");
    expect(selectEntryPrediction([{...recommended,status:"finished"},{...recommended,current:null},fixture])?.id).toBe("one");
    expect(selectEntryPrediction([{...fixture,current:null}])).toBeNull();
    expect(selectEntryPrediction([])).toBeNull();
    expect(match.probabilities).toEqual([.48,.32,.2]);
    expect(match).not.toHaveProperty("archived");
    expect(match.asianPick).toBe("主-0.25 57%");
    expect(selectEntryPrediction([{...fixture,current:{...prediction,asian:null}}])?.asianPick).toBeNull();
  });
  it("显示传入球队、北京时间，缺失字段不补零", () => {
    render(<EntryScreen result={ok(1,{...match,probabilities:[null,.32,.2],over25:null,likelyScores:[],lean:"",asianPick:null})} />);
    expect(screen.getByText("队伍甲",{exact:false})).toBeInTheDocument();
    expect(screen.getByTestId("entry-probability-0")).toHaveTextContent("暂无数据");
    expect(screen.getByText(/10\/26 20:00 开球/)).toBeInTheDocument();
    expect(screen.getAllByText("暂无数据")).toHaveLength(5);
  });
  it("亚盘选择排在赛果倾向之前", () => {
    render(<EntryScreen result={ok(1)} />);
    const terms = screen.getAllByRole("term").map((node) => node.textContent);
    expect(terms.slice(0, 2)).toEqual(["亚盘选择","赛果倾向"]);
    expect(screen.getByText("主-0.25 57%")).toBeInTheDocument();
  });
});

describe("刷新与场景隔离", () => {
  it("每60秒读取，可见性恢复立即读取，无重叠，卸载清理", () => {
    const {rerender,unmount}=render(<EntryScreen result={ok(1)} />);
    act(() => vi.advanceTimersByTime(59_999)); expect(mocks.refresh).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1)); expect(mocks.refresh).toHaveBeenCalledTimes(1);
    visibility("hidden"); visibility("visible"); expect(mocks.refresh).toHaveBeenCalledTimes(1);
    rerender(<EntryScreen result={ok(2)} />);
    visibility("hidden"); act(() => vi.advanceTimersByTime(180_000)); expect(mocks.refresh).toHaveBeenCalledTimes(1);
    visibility("visible"); expect(mocks.refresh).toHaveBeenCalledTimes(2);
    unmount(); act(() => vi.advanceTimersByTime(180_000)); expect(mocks.refresh).toHaveBeenCalledTimes(2);
  });
  it("同值保留文字节点，新概率和换场原位更新，Canvas不重挂", () => {
    const {rerender}=render(<EntryScreen result={ok(1)} />);
    const number=screen.getByTestId("entry-probability-0"), text=number.firstChild, scene=screen.getByTestId("scene");
    rerender(<EntryScreen result={ok(2,structuredClone(match))} />);
    expect(number.firstChild).toBe(text);
    rerender(<EntryScreen result={ok(3,{...match,id:"two",home:"队伍丙",probabilities:[.55,.25,.2]})} />);
    expect(screen.getByTestId("entry-probability-0")).toBe(number);
    expect(number).toHaveTextContent("55%");
    expect(screen.getByTestId("scene")).toBe(scene);
    expect(mocks.mounts).toHaveBeenCalledTimes(1);
  });
  it("失败及15秒超时保留旧值，超时后重试并可由成功回执恢复", () => {
    const {rerender}=render(<EntryScreen result={ok(1)} />);
    rerender(<EntryScreen result={{status:"error",readAt:2}} />);
    expect(screen.getByRole("status")).toHaveTextContent("更新延迟");
    expect(screen.getByTestId("entry-probability-0")).toHaveTextContent("48%");
    expect(screen.getByText(/获取于 10\/25 18:00/)).toBeInTheDocument();
    rerender(<EntryScreen result={ok(3)} />);
    expect(screen.queryByRole("status")).toBeNull();
    act(() => vi.advanceTimersByTime(60_000));
    act(() => vi.advanceTimersByTime(14_999)); expect(screen.queryByRole("status")).toBeNull();
    act(() => vi.advanceTimersByTime(1)); expect(screen.getByRole("status")).toHaveTextContent("更新延迟");
    act(() => vi.advanceTimersByTime(44_999)); expect(mocks.refresh).toHaveBeenCalledTimes(1);
    act(() => vi.advanceTimersByTime(1)); expect(mocks.refresh).toHaveBeenCalledTimes(2);
    act(() => vi.advanceTimersByTime(15_000));
    visibility("hidden"); visibility("visible"); expect(mocks.refresh).toHaveBeenCalledTimes(3);
    rerender(<EntryScreen result={ok(4)} />); expect(screen.queryByRole("status")).toBeNull();
  });
  it("首次失败隐藏卡片，恢复可展示，无候选明确清空", () => {
    const {rerender}=render(<EntryScreen result={{status:"error",readAt:1}} />);
    expect(screen.queryByTestId("entry-probability-0")).toBeNull();
    expect(screen.getByRole("heading",{level:1})).toBeInTheDocument();
    rerender(<EntryScreen result={ok(2)} />); expect(screen.getByTestId("entry-probability-0")).toBeInTheDocument();
    rerender(<EntryScreen result={ok(3,null)} />); expect(screen.queryByTestId("entry-probability-0")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    expect(mocks.mounts).toHaveBeenCalledTimes(1);
  });
});
