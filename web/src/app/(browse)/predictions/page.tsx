import { Predictions } from "@/features/predictions";
import { readDemoMatches } from "@/features/match/read.server";
import { pageMetadata } from "@/lib/site.server";

export const dynamic = "force-dynamic";
export const metadata = pageMetadata(
  "比赛预测",
  "浏览英超、德甲和西甲的赛前预测、模型来源与高信心推荐。固定演示数据。",
  "/predictions",
);

export default function PredictionsPage() {
  return <Predictions matches={readDemoMatches()} />;
}
