import { SiteFrame } from "../site-frame";
import { apiConfigured } from "@/lib/api.server";
import { DEMO_SOURCE, type DataSource } from "@/lib/display";

export default async function BrowseLayout({ children }: { children: React.ReactNode }) {
  // 只按是否配置接口区分标签；生成时间由各页的数据说明给出。地址无效时由各页读取报错，框架照常显示。
  const source: DataSource = (await apiConfigured()) ? { mode: "live", generatedAt: null } : DEMO_SOURCE;
  return <SiteFrame source={source}>{children}</SiteFrame>;
}
