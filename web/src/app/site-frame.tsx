import Link from "next/link";
import type { ReactNode } from "react";
import { Icon } from "@/components/icon";
import { Navigation } from "@/components/navigation.client";
import { AuthTrigger } from "@/features/auth";
import type { DataSource } from "@/lib/display";

/** source 为空时（错误页、404）不标数据来源。 */
export function SiteFrame({ children, source }: { children: ReactNode; source?: DataSource }) {
  const demo = source?.mode === "demo";
  return <>
    <header className="site-header"><div className="header-inner">
      <Link href="/" className="brand" aria-label="绿茵观察首页">
        <span className="brand-mark"><Icon name="ball" size={25} /></span>
        <span>绿茵观察<small>足球赛果观察</small></span>
      </Link>
      <Navigation />
      {source && <span className={demo ? "pill pill-warning header-tag" : "pill pill-accent header-tag"}>{demo ? "演示版本" : "本机实盘"}</span>}
      <AuthTrigger />
    </div></header>
    <main id="main-content" className="site-main">{children}</main>
    <footer className="site-footer"><div className="footer-inner">
      <span>绿茵观察 · 用数据理解比赛</span>
      <span>{demo ? "固定演示数据 · " : source ? "本机实盘快照 · " : ""}时间显示为北京时间 · 预测不代表确定赛果</span>
    </div></footer>
  </>;
}
