"use client";

import { MatchCard, type MatchRecord } from "@/features/match";
import { FollowButton } from "@/features/following";
import {
  DemoNotice,
  EmptyState,
  SectionHeading,
} from "@/components/presentation";
import { useListState } from "./list-state.client";

export function Predictions({ matches }: { matches: readonly MatchRecord[] }) {
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
          <p className="eyebrow">MATCHDAY / 比赛观察</p>
          <h1>每一场比赛，都有迹可循。</h1>
          <p>从赛前概率到赛后验证，清楚了解每一次判断。</p>
        </div>
        <span className="pill">英超 · 德甲 · 西甲</span>
      </div>
      <DemoNotice />
      <section aria-label="高信心推荐">
        <SectionHeading
          title="值得关注的比赛"
          description="模型高信心推荐 · 仅展示符合条件的赛前结果"
          aside={
            <span className="pill pill-accent">
              {recommendations.length} 场推荐
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
            title="暂无推荐"
            description="目前没有符合高信心条件的赛前比赛。"
          />
        )}
        <p className="fine-print mt-3">
          高信心档历史上仍约有四分之一未命中。请结合概率来源和数据时间阅读。
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
                <option value="E0">英超</option>
                <option value="D1">德甲</option>
                <option value="SP1">西甲</option>
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
            <p className="eyebrow">MODEL NOTES</p>
            <h3>让预测有据可查</h3>
            <p>
              胜平负概率、比分与模型来源一起呈现。预测会变化，首次判断会被保留。
            </p>
            <dl>
              <div className="definition">
                <dt>主模型</dt>
                <dd>市场隐含</dd>
              </div>
              <div className="definition">
                <dt>无赔率时</dt>
                <dd>展示后端来源</dd>
              </div>
              <div className="definition">
                <dt>当前数据</dt>
                <dd>固定演示样本</dd>
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
