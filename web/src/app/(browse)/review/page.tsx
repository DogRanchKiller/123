import { Review } from "@/features/review/review";
import { demoReview } from "@/features/review/demo-review.server";
import { pageMetadata } from "@/lib/site.server";

export const metadata = pageMetadata(
  "赛后成绩单",
  "查看预测模型的样本数、版本、Log Loss、Brier 和命中率。当前指标均为演示样本。",
  "/review",
);

export default function ReviewPage() {
  return <Review rows={demoReview} />;
}
