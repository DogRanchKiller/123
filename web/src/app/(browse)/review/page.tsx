import { Review } from "@/features/review/review";
import { readReview } from "@/features/review/read.server";
import { pageMetadata } from "@/lib/site.server";

export const metadata = pageMetadata(
  "赛后成绩单",
  "查看预测模型的亚盘与胜平负成绩：样本数、版本、对数损失、布里尔分数、命中率与同场对比。",
  "/review",
);

export const dynamic = "force-dynamic";

export default async function ReviewPage() {
  const { rows, source } = await readReview();
  return <Review rows={rows} source={source} />;
}
