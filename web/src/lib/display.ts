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

export function percentage(value: number): string {
  return `${(value * 100).toFixed(1).replace(/\.0$/, "")}%`;
}
