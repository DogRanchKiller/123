import Link from "next/link";
import type { ReactNode } from "react";
import { DataNotice } from "@/components/presentation";
import { beijingTime } from "@/lib/display";
import { PredictionSection } from "./prediction-section";
import { TeamCrest } from "./team-crest";
import type { MatchRead } from "./types";

export function MatchDetail({
  data,
  action,
}: {
  data: MatchRead;
  action: ReactNode;
}) {
  const { match, delayed, source } = data;
  return (
    <>
      <Link href="/predictions" scroll={false} className="text-link mb-4">
        ← 返回比赛列表
      </Link>
      <DataNotice source={source} />
      {delayed && (
        <p className="status-notice" role="status">
          更新延迟：当前显示上次有效结果，以下数据时间保持原值。
        </p>
      )}
      <div className="panel detail-hero">
        <span className="pill pill-accent">
          {match.leagueName} · {match.statusLabel}
        </span>
        <h1 className="mt-4">
          {match.home} 对 {match.away}
        </h1>
        <p className="muted mt-2">
          {beijingTime(match.kickoffUtc)} 开球 · 北京时间
        </p>
        {match.recommended && match.recommendationNote && (
          <p className="mt-2">
            <span className="pill pill-accent">★ 重点</span> {match.recommendationNote}
          </p>
        )}
        <div className="card-teams">
          <TeamCrest
            crest={match.homeCrest}
            short={match.homeShort}
            name={match.home}
            className="mx-auto"
          />
          <div>
            <p className="score">
              {match.score
                ? match.score.home + " : " + match.score.away
                : "— : —"}
            </p>
            <p className="fine-print">
              {match.score
                ? "比分时间 " + beijingTime(match.scoreSourceAt)
                : "比分暂无数据"}
            </p>
          </div>
          <TeamCrest
            crest={match.awayCrest}
            short={match.awayShort}
            name={match.away}
            className="mx-auto"
          />
        </div>
        {action}
      </div>
      <div className="detail-grid">
        <div>
          <PredictionSection title="当前预测" prediction={match.current} />
          {match.nearArchived && (
            <PredictionSection title="临场存档" prediction={match.nearArchived} />
          )}
          <PredictionSection title="首次预测存档" prediction={match.archived} />
        </div>
        <aside>
          <section className="panel side-panel">
            <h2>滚球预测</h2>
            <p className="mt-3">{match.inplay.label}</p>
            <p className="mt-3">
              赛前预测与比赛中预测分别展示。实时比分也不代表已具备滚球预测能力。
            </p>
          </section>
          <section className="panel side-panel">
            <h2>阅读这份预测</h2>
            <p className="mt-3">
              每场都给结论和把握程度。胜平负市场档为高（市场最大概率 ≥ 60%）时标为重点，这一档历史上约
              72% 命中，仍约有四分之一未中。
              {"重点只表示胜平负把握高，这类场次在市场亚盘线上仍接近五五开，亚盘请看稳妥线。"}
              命中率是历史表现，不是本场承诺。
            </p>
            <ul className="mt-4 space-y-3 text-sm text-muted">
              {match.risks.map((risk) => (
                <li key={risk}>{risk}</li>
              ))}
            </ul>
          </section>
          <section className="panel side-panel">
            <h3>结果与存档</h3>
            <p>
              当前预测随数据变化；首次预测用于赛后评价，后续刷新不会覆盖历史记录。临场存档是开球前
              1.5 小时内按多家赔率另存的一份，亚盘线与首次存档不同时在盘口变动里标出。
            </p>
            <p className="mt-3 break-all">比赛 ID：{match.id}</p>
          </section>
        </aside>
      </div>
    </>
  );
}
