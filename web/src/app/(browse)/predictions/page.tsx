import { Predictions } from "@/features/predictions";
import { readMatches } from "@/features/match/read.server";
import { pageMetadata } from "@/lib/site.server";

export const dynamic = "force-dynamic";
export const metadata = pageMetadata(
  "比赛预测",
  "浏览英超、德甲、西甲等 11 个联赛的赛前预测：亚盘为主，胜平负与比分为辅。",
  "/predictions",
);

export default async function PredictionsPage() {
  const { matches, source } = await readMatches();
  return <Predictions matches={matches} source={source} />;
}
