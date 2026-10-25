"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { EntryRead } from "./types";

export function useEntryRefresh(result: EntryRead) {
  const router = useRouter();
  const [snapshot, setSnapshot] = useState({
    readAt: result.readAt,
    match: result.status === "ok" ? result.match : null,
    failed: result.status === "error",
  });
  const [timeoutAt, setTimeoutAt] = useState<number | null>(null);
  const inFlight = useRef(false);
  const watchdog = useRef<ReturnType<typeof setTimeout> | null>(null);
  const receipt = useRef(result.readAt);

  // 条件式派生状态：同值保留对象身份；失败保留最后成功结果。
  if (result.readAt > snapshot.readAt) {
    setSnapshot({
      readAt: result.readAt,
      match: result.status === "ok"
        ? JSON.stringify(result.match) === JSON.stringify(snapshot.match) ? snapshot.match : result.match
        : snapshot.match,
      failed: result.status === "error",
    });
  }

  useEffect(() => {
    receipt.current = result.readAt;
    inFlight.current = false;
    if (watchdog.current) clearTimeout(watchdog.current);
  }, [result.readAt]);

  useEffect(() => {
    function refresh() {
      if (document.visibilityState !== "visible" || inFlight.current) return;
      inFlight.current = true;
      const startedFrom = receipt.current;
      watchdog.current = setTimeout(() => {
        if (receipt.current !== startedFrom) return;
        inFlight.current = false;
        setTimeoutAt(startedFrom);
        watchdog.current = null;
      }, 15_000);
      router.refresh();
    }
    let interval: ReturnType<typeof setInterval> | undefined;
    function schedule() {
      if (interval) clearInterval(interval);
      interval = undefined;
      if (document.visibilityState === "visible") interval = setInterval(refresh, 60_000);
    }
    function visibilityChanged() {
      schedule();
      if (document.visibilityState === "visible") refresh();
    }
    schedule();
    document.addEventListener("visibilitychange", visibilityChanged);
    return () => {
      if (interval) clearInterval(interval);
      if (watchdog.current) clearTimeout(watchdog.current);
      document.removeEventListener("visibilitychange", visibilityChanged);
    };
  }, [router]);

  return { match: snapshot.match, delayed: snapshot.failed || timeoutAt === snapshot.readAt };
}
