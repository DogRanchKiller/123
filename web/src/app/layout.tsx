import type { Metadata } from "next";
import Link from "next/link";
import { siteUrl } from "@/lib/site.server";
import { Icon } from "@/components/icon";
import { FollowingProvider } from "@/features/following";
import { Navigation } from "./navigation.client";
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
        <header className="site-header">
          <div className="header-inner">
            <Link
              href="/predictions"
              className="brand"
              aria-label="绿茵观察首页"
            >
              <span className="brand-mark">
                <Icon name="ball" size={25} />
              </span>
              <span>
                绿茵观察<small>FOOTBALL INSIGHTS</small>
              </span>
            </Link>
            <span className="pill pill-warning header-tag sm:order-last">
              演示版本
            </span>
            <Navigation />
          </div>
        </header>
        <main id="main-content" className="site-main">
          <FollowingProvider>{children}</FollowingProvider>
        </main>
        <footer className="site-footer">
          <div className="footer-inner">
            <span>绿茵观察 · 用数据理解比赛</span>
            <span>固定演示数据 · 时间显示为北京时间 · 预测不代表确定赛果</span>
          </div>
        </footer>
      </body>
    </html>
  );
}
