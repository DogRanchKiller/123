import { percentage } from "@/lib/display";
import { lineText, outcomeText, pickText, safeText, tierText } from "./asian";
import type { AsianHandicap } from "./types";

/** 比赛卡片里的亚盘摘要：线 · 选择 · 信心，下一行是稳妥线。 */
export function AsianSummary({ asian }: { asian: AsianHandicap | null }) {
  if (!asian)
    return (
      <div className="card-summary asian-summary">
        <span>亚盘暂无数据</span>
      </div>
    );
  return (
    <div className="card-summary asian-summary" role="group" aria-label="亚盘">
      <span>
        亚盘 <strong>{lineText(asian.line)}</strong>
        {asian.lineSource === "公平线" && (
          <span className="fine-print">（公平线）</span>
        )}
      </span>
      <span>
        选择 <strong>{pickText(asian)}</strong>{" "}
        <span className={asian.tier === "高" ? "pill pill-accent" : "pill"}>
          {tierText(asian)}
        </span>
      </span>
      {safeText(asian) && (
        <span className="asian-safe">
          稳妥 <strong>{safeText(asian)}</strong>
          <span className="fine-print">（让步换把握）</span>
        </span>
      )}
    </div>
  );
}

/** 比赛详情里的亚盘块：放在胜平负之前。 */
export function AsianBlock({ asian }: { asian: AsianHandicap | null }) {
  if (!asian)
    return (
      <div className="asian-block">
        <h3>亚盘</h3>
        <p className="muted mt-2">暂无数据：没有市场亚盘，也没有可用的比分矩阵。</p>
      </div>
    );
  const { outcome } = asian;
  return (
    <div className="asian-block" role="group" aria-label="亚盘">
      <div className="section-heading">
        <h3>亚盘 · {asian.lineSource}</h3>
        <span className={asian.tier === "高" ? "pill pill-accent" : "pill"}>
          亚盘信心 {tierText(asian)}
        </span>
      </div>
      <div className="stat-grid">
        <div className="stat">
          <p>盘口（主队方向）</p>
          <strong>{lineText(asian.line)}</strong>
        </div>
        <div className="stat">
          <p>亚盘选择</p>
          <strong>{pickText(asian)}</strong>
        </div>
        <div className="stat">
          <p>稳妥线（赢盘 ≥ 65%）</p>
          <strong>{safeText(asian) ?? "暂无数据"}</strong>
        </div>
        <div className="stat">
          <p>市场同线主队赢盘（对照）</p>
          <strong>
            {asian.marketHomeCover == null
              ? "暂无数据"
              : percentage(asian.marketHomeCover)}
          </strong>
        </div>
      </div>
      <p>{outcomeText(asian.line, outcome)}</p>
      <dl className="mt-3">
        {(
          [
            ["主队赢", outcome.win],
            ["主队赢半", outcome.halfWin],
            ["走盘", outcome.push],
            ["主队输半", outcome.halfLose],
            ["主队输", outcome.lose],
          ] as const
        ).map(([label, value]) => (
          <div className="definition" key={label}>
            <dt>{label}</dt>
            <dd>{percentage(value)}</dd>
          </div>
        ))}
        <div className="definition">
          <dt>盘口变动</dt>
          <dd>{asian.movement ?? "暂无数据"}</dd>
        </div>
      </dl>
      <p className="fine-print mt-3">
        赢盘概率按走盘不计、半赢 / 半输各算一半，来自主模型动态攻防（dc_dyn）。亚盘信心档是历史分档命中率，不是本场承诺；
        市场线上两边通常接近五五开，动态攻防在市场线上不分档。稳妥线是同一判断换一条更宽的线，命中更高是因为让步了，不代表判断更准。
        市场同线赢盘只作对照：留出赛季里赛前市场的亚盘对数损失仍略好于动态攻防。
      </p>
    </div>
  );
}
