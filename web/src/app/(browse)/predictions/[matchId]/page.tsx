import { notFound } from "next/navigation";
import { MatchDetail } from "@/features/match";
import { readDemoMatch } from "@/features/match/read.server";
import { FollowButton } from "@/features/following";
import { pageMetadata } from "@/lib/site.server";

export const dynamic = "force-dynamic";
export const revalidate = 0;
type Props = { params: Promise<{ matchId: string }> };

async function load(params: Props["params"]) {
  const { matchId } = await params;
  const data = await readDemoMatch(matchId);
  if (!data) notFound();
  return data;
}

export async function generateMetadata({ params }: Props) {
  const { matchId } = await params;
  const data = await readDemoMatch(matchId);
  if (!data) return pageMetadata("找不到这场比赛", "请返回比赛列表选择比赛。", "/predictions/" + matchId);
  const { match } = data;
  return pageMetadata(
    match.home + " vs " + match.away + " · 比赛预测",
    match.leagueName +
      "：查看" +
      match.home +
      "对" +
      match.away +
      "的预测、来源、首次存档与比赛状态。演示数据。",
    "/predictions/" + match.id,
  );
}

export default async function MatchPage({ params }: Props) {
  const data = await load(params);
  return (
    <MatchDetail
      data={data}
      action={
        <FollowButton
          id={data.match.id}
          label={data.match.home + "对" + data.match.away}
        />
      }
    />
  );
}
