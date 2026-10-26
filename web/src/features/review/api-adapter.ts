/** 只读接口的成绩单行 → 页面行。基准 market_avg 自身没有同场对比，配对字段为空。 */
import type { components } from "@/api/schema";
import type { ReviewRow } from "./review";

export type ApiReview = components["schemas"]["Review"];

/** 同场对比的基准；Python live_report 里它对自己的差值是 0 ± 0。 */
const BASE = "market_avg";

export function reviewRowsOf(review: ApiReview): ReviewRow[] {
  return review.scorecard.map((row) => {
    const base = row.model_name === BASE;
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
    pairedMatches: base ? null : (row.paired_n ?? null),
    diffVsMarket: base ? null : (row.diff_vs_base ?? null),
    se: base ? null : (row.se ?? null),
    };
  });
}
