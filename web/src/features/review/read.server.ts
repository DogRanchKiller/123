import "server-only";
import { apiBase, getJson } from "@/lib/api.server";
import { DEMO_SOURCE, type DataSource } from "@/lib/display";
import { reviewRowsOf, type ApiReview } from "./api-adapter";
import { demoReview } from "./demo-review.server";
import type { ReviewRow } from "./review";

/** 未配置 API_URL 时用演示样本；配置后读 /api/review，失败交给路由的错误页（5xx）。 */
export async function readReview(): Promise<{
  rows: readonly ReviewRow[];
  source: DataSource;
}> {
  const base = await apiBase();
  if (!base) return { rows: demoReview, source: DEMO_SOURCE };
  const review = await getJson<ApiReview>(base, "/api/review");
  if (!review) throw new Error("只读接口没有 /api/review");
  return {
    rows: reviewRowsOf(review),
    source: { mode: "live", generatedAt: review.generated_at },
  };
}
