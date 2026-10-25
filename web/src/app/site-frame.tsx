import Link from "next/link";
import type { ReactNode } from "react";
import { Icon } from "@/components/icon";
import { Navigation } from "@/components/navigation.client";
import { AuthTrigger } from "@/features/auth";

export function SiteFrame({ children }: { children: ReactNode }) {
  return <>
    <header className="site-header"><div className="header-inner">
      <Link href="/" className="brand" aria-label="绿茵观察首页">
        <span className="brand-mark"><Icon name="ball" size={25} /></span>
        <span>绿茵观察<small>FOOTBALL INSIGHTS</small></span>
      </Link>
      <Navigation />
      <span className="pill pill-warning header-tag">演示版本</span>
      <AuthTrigger />
    </div></header>
    <main id="main-content" className="site-main">{children}</main>
    <footer className="site-footer"><div className="footer-inner">
      <span>绿茵观察 · 用数据理解比赛</span>
      <span>固定演示数据 · 时间显示为北京时间 · 预测不代表确定赛果</span>
    </div></footer>
  </>;
}
