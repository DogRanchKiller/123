import { readFile } from "node:fs/promises";
import { EntryScreen, selectEntryPrediction, type EntryRead } from "@/features/entry";
import { AuthTrigger } from "@/features/auth";
import { readDemoMatches } from "@/features/match/read.server";
import { pageMetadata } from "@/lib/site.server";

export const dynamic = "force-dynamic";
export const metadata = pageMetadata("首页", "英超、德甲、西甲的赛前预测与赛后成绩单。当前为演示数据。", "/");

export default async function Home() {
  let result: EntryRead;
  // 回执只确认本次读取，不冒充数据获取时间，不传入 3D 场景。
  // 动态服务端读取需要独立回执；不是客户端渲染中的随机状态。
  // eslint-disable-next-line react-hooks/purity
  const readAt = performance.timeOrigin + performance.now();
  try {
    let matches = readDemoMatches();
    // 沿用本机测试控制文件；不提供公开测试接口。
    if (process.env.WEB_TEST_CONTROL_FILE) {
      const control: { entry?: "fail" | "empty" | "ordinary" | "second" } = JSON.parse(
        await readFile(process.env.WEB_TEST_CONTROL_FILE, "utf8"),
      );
      if (control.entry === "fail") throw new Error("首页读取失败（测试）");
      if (control.entry === "empty") matches = [];
      if (control.entry === "ordinary") matches = matches.filter((item) => !item.recommended);
      if (control.entry === "second") matches = matches.slice(1);
    }
    result = { status: "ok", match: selectEntryPrediction(matches), readAt };
  } catch {
    result = { status: "error", readAt };
  }
  return <EntryScreen result={result} account={<AuthTrigger />} />;
}
