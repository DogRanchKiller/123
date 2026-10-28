import "server-only";
import { apiBase, getJson } from "@/lib/api.server";
import { DEMO_SOURCE, type DataSource } from "@/lib/display";
import { closingRowsOf, reviewRowsOf, type ApiReview } from "./api-adapter";
import { demoClosing, demoReview } from "./demo-review.server";
import type { ClosingRow, ReviewRow } from "./review";

/** 未配置 API_URL 时用演示样本；配置后读 /api/review，失败交给路由的错误页（5xx）。 */
export async function readReview(): Promise<{
  rows: readonly ReviewRow[];
  closing: readonly ClosingRow[];
  source: DataSource;
}> {
  const base = await apiBase();
  if (!base) return { rows: demoReview, closing: demoClosing, source: DEMO_SOURCE };
  const review = await getJson<ApiReview>(base, "/api/review");
  if (!review) throw new Error("只读接口没有 /api/review");
  return {
    rows: reviewRowsOf(review),
    closing: closingRowsOf(review),
    source: { mode: "live", generatedAt: review.generated_at },
  };
}
