/** 只读接口的成绩单行 → 页面行。每行对同一档的市场基准（赛前档 market_avg，临场档 market_avg_t1 等），基准自身没有同场对比，配对字段为空。 */
import type { components } from "@/api/schema";
import type { ClosingRow, PrimaryModel, ReviewRow } from "./review";

export type ApiReview = components["schemas"]["Review"];

/** 旧快照没有 base 字段时的基准；Python live_report 里基准对自己的差值是 0 ± 0。 */
const BASE = "market_avg";

/** Python review/scorecard.CLOSING_NAME：收盘参照自身。 */
const CLOSING = "closing_avg";

export function reviewRowsOf(review: ApiReview): ReviewRow[] {
  return review.scorecard.map((row) => {
    const baseName = row.base ?? BASE;
    const base = row.model_name === baseName;
    return {
    name: row.model_name,
    version: row.model_ver,
    matches: row.matches,
    logLoss: row.log_loss,
    brier: row.brier,
    hitRate: row.hit_rate,
    asianMatches: row.ah_n ?? 0,
    asianLogLoss: row.ah_ll ?? null,
    asianHit: row.ah_hit ?? null,
    base: baseName,
    pairedMatches: base ? null : (row.paired_n ?? null),
    diffVsMarket: base ? null : (row.diff_vs_base ?? null),
    se: base ? null : (row.se ?? null),
    };
  });
}

/** 对收盘参照的行；收盘自身的差值是 0 ± 0，页面显示为「参照」。旧快照没有 closing 时为空。 */
/** 快照里的主模型；旧快照没有 primary_model 时为空。 */
export function primaryOf(review: ApiReview): PrimaryModel | null {
  const p = review.primary_model;
  return p ? { name: p.name, version: p.version } : null;
}

export function closingRowsOf(review: ApiReview): ClosingRow[] {
  return (review.closing ?? []).map((row) => {
    const self = row.model_name === CLOSING;
    return {
      name: row.model_name,
      version: row.model_ver,
      pairedMatches: row.paired_n,
      logLoss: row.log_loss,
      diffVsClose: self ? null : row.diff_vs_close,
      se: self ? null : row.se,
    };
  });
}
