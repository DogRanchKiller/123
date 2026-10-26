import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { lineText, outcomeText, pickText, safeText, tierText } from "./asian";
import { AsianBlock, AsianSummary } from "./asian-section";
import type { AsianHandicap } from "./types";

const market: AsianHandicap = {
  line: -0.75,
  lineSource: "市场线",
  outcome: { win: 0.36, halfWin: 0.18, push: 0, halfLose: 0, lose: 0.46 },
  side: "客",
  pCover: 0.55,
  tier: "中",
  historicalHit: 0.562, safeLine: -1.5, safeCover: 0.66,
  selfHomeCover: null,
  movement: null,
};
const fair: AsianHandicap = {
  ...market,
  line: -0.5,
  lineSource: "公平线",
  side: "主",
  pCover: 0.53,
  tier: "-",
  historicalHit: null, safeLine: null, safeCover: null,
};

describe("亚盘文字与 Python ah_text / ah_pick_text 一致", () => {
  it("线用主队方向数字，0 不带负号，客队方向取反", () => {
    expect(lineText(-0.75)).toBe("主-0.75");
    expect(lineText(0.25)).toBe("主+0.25");
    expect(lineText(0)).toBe("主+0.00");
    expect(lineText(-0)).toBe("主+0.00");
    expect(lineText(-0.75, "客")).toBe("客+0.75");
    expect(lineText(0, "客")).toBe("客+0.00");
    expect(pickText(market)).toBe("客+0.75 55%");
  });

  it("赢半 / 输半 / 走盘只在大于 0.5% 时写出", () => {
    expect(outcomeText(-0.75, market.outcome)).toBe(
      "主-0.75 赢盘54%（赢36%、赢半18%），输46%",
    );
    expect(
      outcomeText(-1, { win: 0.39, halfWin: 0, push: 0.25, halfLose: 0, lose: 0.36 }),
    ).toBe("主-1.00 赢盘39%，走25%，输36%");
    expect(
      outcomeText(-0.25, { win: 0, halfWin: 0.2, push: 0, halfLose: 0.8, lose: 0 }),
    ).toBe("主-0.25 赢盘20%（赢半），输80%（输半）");
  });

  it("稳妥线按选择方写，缺时为空", () => {
    expect(safeText(market)).toBe("客+1.50 66%");
    expect(safeText({ ...market, side: "主", safeLine: 0 })).toBe("主+0.00 66%");
    expect(safeText(fair)).toBeNull();
  });

  it("公平线不分档", () => {
    expect(tierText(market)).toBe("中[56%]");
    expect(tierText(fair)).toBe("不分档（公平线）");
  });
});

describe("亚盘区块", () => {
  it("详情列出五种结算与来源，缺失项写暂无数据", () => {
    render(<AsianBlock asian={market} />);
    const block = screen.getByRole("group", { name: "亚盘" });
    expect(within(block).getByRole("heading", { name: "亚盘 · 市场线" })).toBeInTheDocument();
    expect(within(block).getByText("亚盘信心 中[56%]")).toBeInTheDocument();
    expect(within(block).getByText("客+0.75 55%")).toBeInTheDocument();
    expect(within(block).getByText("客+1.50 66%")).toBeInTheDocument();
    expect(within(block).getAllByRole("term")).toHaveLength(6);
    expect(within(block).getAllByText("暂无数据")).toHaveLength(2);
  });

  it("没有亚盘时不伪造线和概率", () => {
    render(<AsianBlock asian={null} />);
    expect(screen.getByRole("heading", { name: "亚盘" })).toBeInTheDocument();
    expect(screen.queryByText(/主[+-]\d/)).toBeNull();
  });

  it("卡片摘要标出公平线", () => {
    render(<AsianSummary asian={fair} />);
    const summary = screen.getByRole("group", { name: "亚盘" });
    expect(summary).toHaveTextContent("主-0.50");
    expect(summary).toHaveTextContent("（公平线）");
    expect(summary).toHaveTextContent("不分档（公平线）");
    expect(summary).not.toHaveTextContent("稳妥");
  });

  it("卡片摘要有稳妥线时另起一行", () => {
    render(<AsianSummary asian={market} />);
    expect(screen.getByRole("group", { name: "亚盘" })).toHaveTextContent("稳妥 客+1.50 66%");
  });
});
