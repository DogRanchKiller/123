/** 模型名（存档里的 model_name）→ 页面上的中文名。只改显示；原名放在 title 里供核对。 */
const LABELS: Readonly<Record<string, string>> = {
  market_implied: "市场隐含",
  market_avg: "市场平均赔率",
  market_shin: "市场隐含（Shin 去水）",
  dc_market: "进球 + 赔率强度",
  dixon_coles: "进球模型",
  dc_sot: "射正模型",
  dc_xg: "预期进球模型",
  elo: "等级分",
  blend: "预期进球 + 等级分融合",
  blend_xg_elo: "预期进球 + 等级分融合",
  lgbm_correction: "梯度提升修正",
  lineup: "阵容调整",
  lineup_base: "阵容对照",
};

/** 中文模型名；`_t1` 结尾的是临场档。表里没有时原样返回。 */
export function modelLabel(name: string): string {
  const near = name.endsWith("_t1");
  const base = near ? name.slice(0, -3) : name;
  const label = LABELS[base];
  if (!label) return name;
  return near ? label + "（临场）" : label;
}

const TOKEN = new RegExp(
  "\\b(" +
    Object.keys(LABELS)
      .sort((a, b) => b.length - a.length)
      .join("|") +
    ")(_t1)?\\b(?: (?=[\\u4e00-\\u9fff]))?",
  "g",
);

/** 后端提示文字里的模型名和 pp 换成中文；模型名后紧跟中文时去掉中间的空格。 */
export function zhText(text: string): string {
  return text
    .replace(TOKEN, (_, base: string, near?: string) => modelLabel(base + (near ?? "")))
    .replace(/([+\-−]?\d+(?:\.\d+)?)pp\b/g, "$1 个百分点");
}
