import Link from "next/link";
import type { ReactNode } from "react";
import { DataNotice } from "@/components/presentation";
import { beijingTime } from "@/lib/display";
import { PredictionSection } from "./prediction-section";
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
          {match.home} vs {match.away}
        </h1>
        <p className="muted mt-2">
          {beijingTime(match.kickoffUtc)} 开球 · 北京时间
        </p>
        <div className="card-teams">
          <span className="team-badge mx-auto">{match.homeShort}</span>
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
          <span className="team-badge mx-auto">{match.awayShort}</span>
        </div>
        {action}
      </div>
      <div className="detail-grid">
        <div>
          <PredictionSection title="当前预测" prediction={match.current} />
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
              高信心档历史上仍约有四分之一未命中。命中率是历史表现，不是本场承诺。
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
              当前预测随数据变化；首次预测用于赛后评价，后续刷新不会覆盖历史记录。
            </p>
            <p className="mt-3 break-all">比赛 ID：{match.id}</p>
          </section>
        </aside>
      </div>
    </>
  );
}
