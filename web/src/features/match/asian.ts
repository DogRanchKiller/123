import type { AsianHandicap, AsianOutcome } from "./types";

// 亚盘文字与 Python `output/analysis.py` 的 ah_text / ah_pick_text 保持同一写法；只做格式化，不计算概率。

function whole(value: number): string {
  return `${Math.round(value * 100)}%`;
}

/** 主队方向的数字线：-0.75 → 「主-0.75」，0 → 「主+0.00」。 */
export function lineText(line: number, side: "主" | "客" = "主"): string {
  const value = side === "主" ? line : -line;
  // 0 和 -0 都写成 +0.00，与 Python 的 f"{line + 0.0:+.2f}" 一致。
  return `${side}${value < 0 ? "" : "+"}${(value === 0 ? 0 : value).toFixed(2)}`;
}

/** 选择方与等效赢盘概率：「客+0.75 55%」。 */
export function pickText(asian: AsianHandicap): string {
  return `${lineText(asian.line, asian.side)} ${whole(asian.pCover)}`;
}

function part(word: string, short: string, full: number, half: number): string {
  const total = full + half;
  if (half <= 0.005) return `${word}${whole(total)}`;
  if (full <= 0.005) return `${word}${whole(total)}（${short}半）`;
  return `${word}${whole(total)}（${short}${whole(full)}、${short}半${whole(half)}）`;
}

/** 「主-0.75 赢盘54%（赢36%、赢半18%），输46%」；有走盘时加「走x%」。 */
export function outcomeText(line: number, outcome: AsianOutcome): string {
  let text = `${lineText(line)} ${part("赢盘", "赢", outcome.win, outcome.halfWin)}`;
  if (outcome.push > 0.005) text += `，走${whole(outcome.push)}`;
  return `${text}，${part("输", "输", outcome.lose, outcome.halfLose)}`;
}

/** 稳妥线：「客+1.25 66%」；没有时为空。与 Python analysis.safe_text 同写法。 */
export function safeText(asian: AsianHandicap): string | null {
  if (asian.safeLine === null || asian.safeCover === null) return null;
  return `${lineText(asian.safeLine, asian.side)} ${whole(asian.safeCover)}`;
}

/** 档名加历史命中：「中[56%]」；公平线时为「不分档（公平线）」。 */
export function tierText(asian: AsianHandicap): string {
  if (asian.tier === "-" || asian.historicalHit === null)
    return "不分档（公平线）";
  return `${asian.tier}[${whole(asian.historicalHit)}]`;
}
