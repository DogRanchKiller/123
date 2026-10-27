import { Chat } from "@/features/chat";
import { readChatState } from "@/features/chat/read.server";
import { pageMetadata } from "@/lib/site.server";

export const metadata = pageMetadata(
  "问答",
  "用邀请码登录后提问：比赛、球队近况、阵容伤停与模型成绩，回答里的数字逐个核对本站数据。",
  "/chat",
);

export const dynamic = "force-dynamic";

export default async function ChatPage() {
  return <Chat state={await readChatState()} />;
}
