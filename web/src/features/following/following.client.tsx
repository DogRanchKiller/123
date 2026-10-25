"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { Icon } from "@/components/icon";

export const FOLLOWING_KEY = "football.following.v1";
type FollowingState = {
  ids: string[];
  ready: boolean;
  warning: string | null;
  toggle: (id: string) => void;
};
const FollowingContext = createContext<FollowingState | null>(null);

export function FollowingProvider({ children }: { children: ReactNode }) {
  const [ids, setIds] = useState<string[]>([]);
  const [ready, setReady] = useState(false);
  const [warning, setWarning] = useState<string | null>(null);

  useEffect(() => {
    // 浏览器存储是外部系统；首次渲染固定为空，挂载后再恢复，不覆盖已有记录。
    try {
      const saved: unknown = JSON.parse(
        localStorage.getItem(FOLLOWING_KEY) ?? "[]",
      );
      if (!Array.isArray(saved) || !saved.every((id) => typeof id === "string"))
        throw new Error("invalid storage");
      // eslint-disable-next-line react-hooks/set-state-in-effect -- restore external browser storage after hydration
      setIds([...new Set(saved)]);
    } catch {
      setWarning("浏览器无法读取关注记录，本次操作将暂存在当前页面。");
    }
    setReady(true);
  }, []);

  function toggle(id: string) {
    if (!ready) return;
    const next = ids.includes(id)
      ? ids.filter((value) => value !== id)
      : [...ids, id];
    setIds(next);
    try {
      localStorage.setItem(FOLLOWING_KEY, JSON.stringify(next));
    } catch {
      setWarning("浏览器无法保存关注记录，刷新后可能丢失；当前仍可继续关注。");
    }
  }

  return (
    <FollowingContext value={{ ids, ready, warning, toggle }}>
      {warning && (
        <p role="status" className="status-notice">
          {warning}
        </p>
      )}
      {children}
    </FollowingContext>
  );
}

export function useFollowing() {
  const context = useContext(FollowingContext);
  if (!context) throw new Error("FollowingProvider is required");
  return context;
}

export function FollowButton({ id, label }: { id: string; label: string }) {
  const { ids, ready, toggle } = useFollowing();
  const selected = ids.includes(id);
  return (
    <button
      className="button"
      disabled={!ready}
      aria-pressed={selected}
      aria-label={`${selected ? "取消关注" : "关注"}${label}`}
      onClick={() => toggle(id)}
    >
      <Icon name={selected ? "check" : "star"} size={15} />
      {selected ? "已关注" : "关注比赛"}
    </button>
  );
}
