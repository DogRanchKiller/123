const beijing = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

export function beijingTime(value: string | null): string {
  return value ? beijing.format(new Date(value)) : "来源未提供";
}

/** 页面数据来自哪里：未配置 API_URL 时是固定演示样本；配置后读本机只读接口（实盘快照）。 */
export type DataSource =
  | { mode: "demo" }
  | { mode: "live"; generatedAt: string | null };

export const DEMO_SOURCE: DataSource = { mode: "demo" };

export function percentage(value: number): string {
  return `${(value * 100).toFixed(1).replace(/\.0$/, "")}%`;
}
