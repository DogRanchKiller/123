"use client";

import {
  LEAGUES,
  LEAGUE_SUMMARY,
  MatchCard,
  type MatchRecord,
} from "@/features/match";
import { FollowButton } from "@/features/following";
import {
  DataNotice,
  EmptyState,
  SectionHeading,
} from "@/components/presentation";
import type { DataSource } from "@/lib/display";
import { useListState } from "./list-state.client";

export function Predictions({
  matches,
  source,
}: {
  matches: readonly MatchRecord[];
  source: DataSource;
}) {
  const { filters, changeFilters, warning } = useListState();
  const recommendations = matches.filter((match) => match.recommended);
  const visible = matches.filter(
    (match) =>
      (filters.league === "all" || match.league === filters.league) &&
      (filters.status === "all" || match.status === filters.status),
  );
  const follow = (match: MatchRecord) => (
    <FollowButton id={match.id} label={match.home + "对" + match.away} />
  );

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">比赛日 / 比赛观察</p>
          <h1>每一场比赛，都有迹可循。</h1>
          <p>从赛前概率到赛后验证，清楚了解每一次判断。</p>
        </div>
        <span className="pill">{LEAGUE_SUMMARY}</span>
      </div>
      <DataNotice source={source} />
      <section aria-label="重点比赛">
        <SectionHeading
          title="重点比赛"
          description="胜平负市场最大概率 ≥ 60% 的赛前场次；其余场次在下方照常给出结论和把握程度"
          aside={
            <span className="pill pill-accent">
              {recommendations.length} 场重点
            </span>
          }
        />
        {recommendations.length ? (
          <div className="recommended-grid">
            {recommendations.map((match) => (
              <MatchCard
                key={match.id}
                match={match}
                featured
                action={follow(match)}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            title="暂无重点"
            description="目前没有胜平负高把握的赛前比赛。"
          />
        )}
        <p className="fine-print mt-3">
          这一档胜平负首选历史上约 72% 命中（2526 留出赛季 72.8%），仍约有四分之一未中。
          {"重点只表示胜平负把握高：这类场次在市场亚盘线上的命中约 52–55%，和其他场次差不多。"}
          {"亚盘看卡片里的「稳妥」，即选择方赢盘 ≥ 65% 的最近一条线（历史命中约 67%）。"}
        </p>
      </section>
      <div className="dashboard-columns">
        <section aria-label="全部比赛">
          <SectionHeading
            title="全部比赛"
            description="按联赛和比赛状态浏览，关注你感兴趣的场次。"
            aside={<span className="fine-print">{visible.length} 场</span>}
          />
          <div className="filter-bar">
            <label>
              联赛
              <select
                aria-label="筛选联赛"
                value={filters.league}
                onChange={(event) =>
                  changeFilters({ ...filters, league: event.target.value })
                }
              >
                <option value="all">全部联赛</option>
                {LEAGUES.map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              状态
              <select
                aria-label="筛选比赛状态"
                value={filters.status}
                onChange={(event) =>
                  changeFilters({ ...filters, status: event.target.value })
                }
              >
                <option value="all">全部状态</option>
                <option value="upcoming">未开赛</option>
                <option value="inplay">比赛中</option>
                <option value="finished">已结束</option>
              </select>
            </label>
          </div>
          {warning && (
            <p role="status" className="status-notice">
              {warning}
            </p>
          )}
          {visible.length ? (
            <div className="match-grid">
              {visible.map((match) => (
                <MatchCard
                  key={match.id}
                  match={match}
                  action={follow(match)}
                />
              ))}
            </div>
          ) : (
            <EmptyState
              title="没有符合筛选的比赛"
              description="试试其他联赛或比赛状态。"
            />
          )}
        </section>
        <aside className="sidebar">
          <section className="panel side-panel">
            <p className="eyebrow">模型说明</p>
            <h3>让预测有据可查</h3>
            <p>
              亚盘为主，胜平负、比分与大小球为辅，模型来源一起呈现。预测会变化，首次判断会被保留。
            </p>
            <dl>
              <div className="definition">
                <dt>主模型</dt>
                <dd>动态攻防模型</dd>
              </div>
              <div className="definition">
                <dt>市场赔率</dt>
                <dd>只作对照；无赔率时照常出动态攻防</dd>
              </div>
              <div className="definition">
                <dt>当前数据</dt>
                <dd>{source.mode === "demo" ? "固定演示样本" : "本机实盘快照"}</dd>
              </div>
            </dl>
          </section>
          <section className="panel side-panel">
            <h3>从赛前，看到赛后</h3>
            <p>
              关注比赛后，可在「我的关注」集中查看。实时比分和滚球预测将在后续独立接入。
            </p>
            <p className="mt-4">关注保存在当前浏览器，无需登录。</p>
          </section>
        </aside>
      </div>
    </>
  );
}
