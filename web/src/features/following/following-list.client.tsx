"use client";

import { MatchCard, type MatchRecord } from "@/features/match";
import { EmptyState } from "@/components/presentation";
import { FollowButton, useFollowing } from "./following.client";

export function FollowingList({
  matches,
}: {
  matches: readonly MatchRecord[];
}) {
  const { ids, ready } = useFollowing();
  if (!ready)
    return (
      <p role="status" className="panel muted">
        正在读取本机关注记录…
      </p>
    );
  const selected = matches.filter((match) => ids.includes(match.id));
  if (!selected.length)
    return (
      <EmptyState
        title="还没有关注的比赛"
        description="在比赛卡片上点击「关注比赛」，即可在这里集中查看。关注只保存在当前浏览器。"
      />
    );
  return (
    <div className="match-grid">
      {selected.map((match) => (
        <MatchCard
          key={match.id}
          match={match}
          action={
            <FollowButton
              id={match.id}
              label={`${match.home}对${match.away}`}
            />
          }
        />
      ))}
    </div>
  );
}
