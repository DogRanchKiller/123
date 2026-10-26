"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { Component, type ReactNode } from "react";
import { Icon } from "@/components/icon";
import { Navigation } from "@/components/navigation.client";
import { LEAGUES, LEAGUE_SUMMARY } from "@/features/match";
import { PredictionCards } from "./prediction-cards";
import { PitchPoster } from "./pitch-poster";
import { useEntryRefresh } from "./refresh.client";
import { DEMO_SOURCE, type DataSource } from "@/lib/display";
import type { EntryRead } from "./types";

const HIGHLIGHTS = [
  [`${LEAGUES.length} 个联赛`, "赛前预测"],
  ["亚盘为主", "胜平负 / 比分为辅"],
  ["首次存档", "赛后评分"],
] as const;

const PitchCanvas = dynamic(() => import("./pitch-canvas.client"), { ssr: false, loading: () => <PitchPoster /> });

class PitchLoaderBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <div className="entry-pitch"><PitchPoster /></div> : this.props.children; }
}

export function EntryScreen({ result, account, source = DEMO_SOURCE }: { result: EntryRead; account?: ReactNode; source?: DataSource }) {
  const demo = source.mode === "demo";
  const { match, delayed } = useEntryRefresh(result);
  return <div className="entry-screen" data-read-at={result.readAt}>
    <aside className="entry-rail" aria-label="快捷导航">
      <Link href="/" aria-label="绿茵观察首页" className="entry-rail-brand"><Icon name="ball" size={29} /></Link>
      <Link href="/" aria-current="page"><Icon name="grid" size={22} /><span>首页</span></Link>
      <Link href="/predictions"><Icon name="ball" size={22} /><span>预测</span></Link>
      <Link href="/following"><Icon name="star" size={22} /><span>关注</span></Link>
      <Link href="/review"><Icon name="chart" size={22} /><span>成绩单</span></Link>
      <span className="entry-rail-bottom">EST. 2026</span>
    </aside>
    <div className="entry-body">
      <header className="entry-header">
        <Link href="/" className="brand" aria-label="绿茵观察首页"><span className="entry-brand-icon"><Icon name="ball" size={29} /></span><span>绿茵观察<small>FOOTBALL INSIGHTS</small></span></Link>
        <Navigation />
        <span className="pill pill-accent header-tag">{demo ? "演示版本" : "本机实盘"}</span>
        {account}
      </header>
      <main id="main-content" className="entry-main">
        <div className="entry-copy">
          <p className="entry-eyebrow"><span /> THE GAME, THROUGH DATA</p>
          <h1>从数据中，<br />发现胜负的<span>可能</span><i>。</i></h1>
          <p className="entry-description">每一场比赛，都有值得读懂的信号。<br />对照市场赔率与模型，从赛前判断到赛后验证。</p>
          <Link href="/predictions" className="entry-cta">查看今日预测 <Icon name="arrow" size={22} /></Link>
          <p className="entry-cta-note">无需登录 · 先看数据，再做判断</p>
          <div className="entry-leagues">{HIGHLIGHTS.map(([title, note], i) => <div key={title}><span>0{i + 1} /</span><strong>{title}</strong><small>{note}</small></div>)}</div>
        </div>
        <div className="entry-visual">
          <div className="entry-scene-caption"><span className="entry-dot" /> HOLOGRAPHIC MATCH LAB<span>01 — 03</span></div>
          <PitchLoaderBoundary><PitchCanvas /></PitchLoaderBoundary>
          <PredictionCards match={match} delayed={delayed} demo={demo} />
          <p className="entry-scene-note">全息球场 · 装饰性战术示意，非实时比赛轨迹</p>
        </div>
      </main>
      <footer className="entry-footer"><span>{LEAGUE_SUMMARY} <i>/</i> 用数据理解比赛</span><span>{demo ? "演示数据" : "本机实盘快照"}，不代表确定赛果</span></footer>
    </div>
  </div>;
}
