import { FollowingList } from "@/features/following";
import { readDemoMatches } from "@/features/match/read.server";
import { DemoNotice } from "@/components/presentation";
import { pageMetadata } from "@/lib/site.server";

export const metadata = pageMetadata(
  "我的关注",
  "在当前浏览器集中查看手动关注的比赛。无需登录，不跨设备同步。",
  "/following",
);

export default function FollowingPage() {
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">YOUR WATCHLIST</p>
          <h1>我的关注</h1>
          <p>你的比赛清单，从赛前判断到终场比分。</p>
        </div>
        <span className="pill">仅保存在当前浏览器</span>
      </div>
      <DemoNotice />
      <FollowingList matches={readDemoMatches()} />
    </>
  );
}
