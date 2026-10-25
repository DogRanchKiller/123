import type { Metadata } from "next";
import { siteUrl } from "@/lib/site.server";
import { FollowingProvider } from "@/features/following";
import "@/styles/globals.css";

export const metadata: Metadata = {
  metadataBase: siteUrl,
  title: { default: "绿茵观察 · 足球预测", template: "%s · 绿茵观察" },
  description: "查看足球比赛预测、模型来源和赛后成绩单。当前为演示网站。",
  robots: { index: false, follow: false },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <a className="skip-link" href="#main-content">
          跳转到正文
        </a>
        <FollowingProvider>{children}</FollowingProvider>
      </body>
    </html>
  );
}
