"use client";

import Link from "next/link";

export function MissingPage() {
  return <><div className="empty-state">
    <h1>找不到这场比赛或页面</h1>
    <p>请检查地址，或返回比赛列表。未知场次不会被当作数据读取故障。</p>
  </div><Link href="/predictions" className="text-link mt-5">返回比赛列表 →</Link></>;
}

export function ReadError() {
  return <div className="empty-state" role="alert">
    <h1>数据暂时无法读取</h1>
    <p>当前没有可展示的有效结果，请稍后重试。这不表示比赛不存在。</p>
    <button className="button button-primary mt-5" onClick={() => window.location.reload()}>重新读取</button>
  </div>;
}
