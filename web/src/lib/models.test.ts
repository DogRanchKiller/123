import { describe, expect, it } from "vitest";
import { modelLabel, zhText } from "./models";

describe("模型名中文显示", () => {
  it("已知模型换中文，临场档加后缀，未知原样", () => {
    expect(modelLabel("market_implied")).toBe("市场隐含");
    expect(modelLabel("market_implied_t1")).toBe("市场隐含（临场）");
    expect(modelLabel("new_model")).toBe("new_model");
  });

  it("提示文字里的模型名和 pp", () => {
    expect(zhText("dc_xg 与市场分歧：主胜 -16pp（仅提示）")).toBe(
      "预期进球模型与市场分歧：主胜 -16 个百分点（仅提示）",
    );
    expect(zhText("elo 在主-1.50")).toBe("等级分在主-1.50");
    expect(zhText("blend")).toBe("预期进球 + 等级分融合");
    expect(zhText("dc_xg（无赔率）")).toBe("预期进球模型（无赔率）");
    expect(zhText("多家中位数（5 家）")).toBe("多家中位数（5 家）");
  });
});
