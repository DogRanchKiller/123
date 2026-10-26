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
  // 列表只含未开赛和最近几天已开球的场次；更早的关注仍保存在本机，只是不显示。
  const hidden = ids.length - selected.length;
  const hiddenNote = hidden > 0 && (
    <p role="note" className="panel muted">
      另有 {hidden} 场关注不在当前数据里（开球已超过几天，或已不在赛程表），未显示。
    </p>
  );
  if (!selected.length)
    return (
      <>
        {hiddenNote}
        <EmptyState
          title={hidden > 0 ? "当前没有可显示的关注" : "还没有关注的比赛"}
          description="在比赛卡片上点击「关注比赛」，即可在这里集中查看。关注只保存在当前浏览器。"
        />
      </>
    );
  return (
    <>
      {hiddenNote}
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
    </>
  );
}
