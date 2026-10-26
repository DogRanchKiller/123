"use client";

import { useEffect, useRef, useState } from "react";
import { LEAGUE_CODES } from "@/features/match";

export const LIST_STATE_KEY = "football.predictions.view.v1";
type Filters = { league: string; status: string };
const defaults: Filters = { league: "all", status: "all" };

export function useListState() {
  const [filters, setFilters] = useState(defaults);
  const [warning, setWarning] = useState<string | null>(null);
  const lastY = useRef(0);
  const latest = useRef(filters);
  const cancelRestore = useRef(() => {});

  useEffect(() => {
    let targetY = 0;
    try {
      const saved = JSON.parse(
        sessionStorage.getItem(LIST_STATE_KEY) ?? "null",
      );
      if (
        saved &&
        (saved.league === "all" || LEAGUE_CODES.includes(saved.league)) &&
        ["all", "upcoming", "inplay", "finished"].includes(saved.status)
      ) {
        // eslint-disable-next-line react-hooks/set-state-in-effect -- restore browser storage after hydration
        setFilters({ league: saved.league, status: saved.status });
        latest.current = { league: saved.league, status: saved.status };
        targetY =
          typeof saved.scrollY === "number" && Number.isFinite(saved.scrollY)
            ? Math.max(0, saved.scrollY)
            : 0;
      }
    } catch {
      setWarning("无法保存或读取筛选位置，本次筛选仍可正常使用。");
    }
    // Next.js 可保留页面状态但重新挂载 effects；每次激活都从存储恢复。
    // 等筛选渲染和路由布局结束再滚动，恢复前不写入浏览器自动滚动产生的 0。
    lastY.current = targetY;
    let restoring = true;
    let secondFrame = 0;
    const frame = requestAnimationFrame(() => {
      secondFrame = requestAnimationFrame(() => {
        window.scrollTo(0, targetY);
        restoring = false;
      });
    });
    cancelRestore.current = () => {
      cancelAnimationFrame(frame);
      cancelAnimationFrame(secondFrame);
      restoring = false;
      lastY.current = window.scrollY;
    };
    const save = () => {
      try {
        sessionStorage.setItem(
          LIST_STATE_KEY,
          JSON.stringify({ ...latest.current, scrollY: lastY.current }),
        );
      } catch {
        setWarning("无法保存筛选位置，刷新后将恢复默认筛选。");
      }
    };
    // 进入详情时，路由先切换并滚到顶部，列表的监听要等卸载才移除；
    // 这期间的滚动属于新页面，不能覆盖列表的位置。
    const listPath = window.location.pathname;
    const onScroll = () => {
      if (restoring || window.location.pathname !== listPath) return;
      lastY.current = window.scrollY;
      save();
    };
    window.addEventListener("pagehide", save);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      cancelAnimationFrame(secondFrame);
      save();
      window.removeEventListener("pagehide", save);
      window.removeEventListener("scroll", onScroll);
    };
  }, []);

  function changeFilters(next: Filters) {
    cancelRestore.current();
    setFilters(next);
    latest.current = next;
    try {
      sessionStorage.setItem(
        LIST_STATE_KEY,
        JSON.stringify({ ...next, scrollY: window.scrollY }),
      );
    } catch {
      setWarning("无法保存筛选位置，刷新后将恢复默认筛选。");
    }
  }

  return { filters, changeFilters, warning };
}
