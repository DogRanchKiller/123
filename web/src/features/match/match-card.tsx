import Link from "next/link";
import type { ReactNode } from "react";
import { Icon } from "@/components/icon";
import { ProbabilityBar } from "@/components/presentation";
import { beijingTime } from "@/lib/display";
import { modelLabel } from "@/lib/models";
import { AsianSummary } from "./asian-section";
import { TeamCrest } from "./team-crest";
import type { MatchRecord } from "./types";

export function MatchCard({
  match,
  featured = false,
  action,
}: {
  match: MatchRecord;
  featured?: boolean;
  action?: ReactNode;
}) {
  // 未开赛看本轮看法；开球后看存档：临场档（更接近开球）优先，没有时用首次存档。
  const prediction = match.current ?? match.nearArchived ?? match.archived;
  const archiveLabel = match.current
    ? null
    : match.nearArchived
      ? "临场存档"
      : match.archived
        ? "首次存档"
        : null;
  return (
    <article
      className={"match-card" + (featured ? " featured" : "")}
      aria-label={match.home + "对" + match.away}
    >
      <div className="card-body">
        <div className="card-meta">
          <span className="pill">{match.leagueName}</span>
          <span>{beijingTime(match.kickoffUtc)}</span>
          <span
            className={
              match.status === "inplay" ? "pill pill-accent" : "fine-print"
            }
          >
            {match.statusLabel}
          </span>
        </div>
        <div className="card-teams">
          <div>
            <TeamCrest
              crest={match.homeCrest}
              short={match.homeShort}
              name={match.home}
              decorative
            />
            <p className="team-name">{match.home}</p>
          </div>
          {match.score ? (
            <span className="score">
              {match.score.home} : {match.score.away}
            </span>
          ) : (
            <span className="versus">对</span>
          )}
          <div>
            <TeamCrest
              crest={match.awayCrest}
              short={match.awayShort}
              name={match.away}
              decorative
            />
            <p className="team-name">{match.away}</p>
          </div>
        </div>
        {prediction ? (
          <>
            <AsianSummary asian={prediction.asian} />
            <ProbabilityBar values={prediction.probabilities} />
            <div className="card-summary">
              <span>
                倾向 <strong>{prediction.lean}</strong>{" "}
                <span
                  className={
                    prediction.confidence === "高" ? "pill pill-accent" : "pill"
                  }
                >
                  胜平负{prediction.confidence}
                </span>
              </span>
              <span>
                可能比分{" "}
                <strong>{prediction.likelyScores[0] ?? "暂无数据"}</strong>
              </span>
            </div>
            <p className="fine-print mt-3">
              {archiveLabel && archiveLabel + " · "}
              概率来源：{prediction.probabilitySource} ·{" "}
              <span title={prediction.modelName}>
                {modelLabel(prediction.modelName)}
              </span>
              {prediction.oddsSource && " · 赔率：" + prediction.oddsSource}
            </p>
          </>
        ) : (
          <div className="card-summary">
            <span>
              {match.status === "upcoming"
                ? "预测结果暂无数据"
                : "赛前预测暂无存档"}
            </span>
            <span>{match.inplay.label}</span>
          </div>
        )}
      </div>
      <div className="card-footer">
        {action}
        <Link
          href={"/predictions/" + match.id}
          className="text-link"
          aria-label={"查看" + match.home + "对" + match.away + "详情"}
        >
          比赛详情
          <Icon name="arrow" size={15} />
        </Link>
      </div>
    </article>
  );
}
