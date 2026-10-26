import Image from "next/image";
import Link from "next/link";
import { percentage, beijingTime } from "@/lib/display";
import type { EntryPrediction } from "./types";

const crest = (src: string | null) => src && <Image src={src} alt="" width={28} height={28} unoptimized className="entry-crest" />;

export function PredictionCards({ match, delayed, demo }: { match: EntryPrediction | null; delayed: boolean; demo: boolean }) {
  return <div className="entry-data" aria-label="当前预测">
    {delayed && <p className="entry-delay" role="status">更新延迟{match ? " · 当前保留上次有效预测" : " · 暂无有效预测"}</p>}
    {match && <>
      <section className="entry-glass entry-match">
        <p className="entry-card-label"><span className="entry-dot" /> {match.leagueName} <span>{match.statusLabel}</span></p>
        <Link href={`/predictions/${match.id}`} className="entry-match-link">{crest(match.homeCrest)}{match.home}<span>对</span>{match.away}{crest(match.awayCrest)}</Link>
        <p className="fine-print">{match.kickoffUtc ? beijingTime(match.kickoffUtc) : "暂无数据"} 开球 · 北京时间</p>
        <div className="entry-probabilities">
          {["主胜", "平局", "客胜"].map((label, index) => <div key={label}><span>{label}</span><strong data-testid={`entry-probability-${index}`}>{match.probabilities[index] == null ? "暂无数据" : percentage(match.probabilities[index])}</strong></div>)}
        </div>
        <p className="entry-data-note">{demo ? "演示数据" : "本机实盘"} · 获取于 {match.fetchedAt ? beijingTime(match.fetchedAt) : "暂无数据"}（北京时间）</p>
      </section>
      <section className="entry-glass entry-outlook">
        <p className="entry-card-label">赛前看法 <span>当前预测</span></p>
        <dl>
          <div><dt>亚盘选择</dt><dd>{match.asianPick ?? "暂无数据"}</dd></div>
          <div><dt>赛果倾向</dt><dd>{match.lean || "暂无数据"}</dd></div>
          <div><dt>大 2.5 球</dt><dd>{match.over25 === null ? "暂无数据" : percentage(match.over25)}</dd></div>
          <div><dt>可能比分</dt><dd>{match.likelyScores.length ? match.likelyScores.join(" / ") : "暂无数据"}</dd></div>
        </dl>
        <p className="entry-source">{match.sourceNote || "暂无数据"}</p>
      </section>
    </>}
  </div>;
}
