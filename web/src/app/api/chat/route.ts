import { agentServe } from "@/features/chat/agent.server";
import { forwardChat } from "@/features/chat/forward.server";
import { siteUrl } from "@/lib/site.server";

// 网站唯一的转发路由（docs/modules.md）：只有 POST，其余方法由 Next.js 回 405。
export const dynamic = "force-dynamic";

export function POST(request: Request) {
  return forwardChat(request, siteUrl, agentServe());
}
