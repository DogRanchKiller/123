import { ProbabilityBar, EmptyState } from "@/components/presentation";
import { beijingTime, percentage } from "@/lib/display";
import { modelLabel } from "@/lib/models";
import { AsianBlock } from "./asian-section";
import type { Prediction } from "./types";

/** 模型自己的结论（按页面显示精度）：亚盘、胜平负、大小球、比分、模型与版本。
 * 不算时间、赔率来源、说明文字和市场对照（存档接口不带市场对照，当前预测才有），
 * 这些在存档与当前预测之间本来就不同。 */
function shown(p: Prediction): string {
  const pct = (v: number | null) => (v === null ? null : percentage(v));
  const a = p.asian;
  return JSON.stringify([
    p.modelName, p.modelVersion, p.confidence, p.lean, p.double, p.likelyScores,
    p.probabilities.map(pct), pct(p.over25),
    a && [a.line, a.lineSource, a.side, a.tier, pct(a.pCover), a.safeLine, pct(a.safeCover),
      Object.values(a.outcome).map(pct)],
  ]);
}

/** 两份预测在页面上显示的结论完全相同。 */
export function samePrediction(a: Prediction, b: Prediction): boolean {
  return shown(a) === shown(b);
}

/** 与当前预测相同的存档：默认收起（原生 details，键盘可展开），标题旁写「与当前预测相同」，展开后是完整内容。 */
export function CollapsedPredictionSection({ prediction, title }: { prediction: Prediction; title: string }) {
  return (
    <details className="panel prediction-section prediction-collapsed">
      <summary>
        <h2>{title}</h2>
        <span className="pill">与当前预测相同</span>
      </summary>
      <PredictionBody prediction={prediction} />
    </details>
  );
}

export function PredictionSection({
  prediction,
  title,
}: {
  prediction: Prediction | null;
  title: string;
}) {
  if (!prediction)
    return (
      <section className="panel prediction-section">
        <h2>{title}</h2>
        <EmptyState
          title="暂无数据"
          description="此区域尚无对应模型结果，不使用其他结果替代。"
        />
      </section>
    );
  return (
    <section className="panel prediction-section">
      <h2>{title}</h2>
      <PredictionBody prediction={prediction} />
    </section>
  );
}

function PredictionBody({ prediction }: { prediction: Prediction }) {
  return (
    <>
      <AsianBlock asian={prediction.asian} />
      <div className="section-heading mt-6">
        <h3>胜平负</h3>
        <span
          className={
            prediction.confidence === "高" ? "pill pill-accent" : "pill"
          }
        >
          胜平负信心 {prediction.confidence}
        </span>
      </div>
      <ProbabilityBar values={prediction.probabilities} />
      {prediction.marketProbabilities && (
        <p className="fine-print">
          市场对照（去水）主 {percentage(prediction.marketProbabilities[0])} · 平{" "}
          {percentage(prediction.marketProbabilities[1])} · 客{" "}
          {percentage(prediction.marketProbabilities[2])}
        </p>
      )}
      <div className="stat-grid">
        <div className="stat">
          <p>赛果倾向</p>
          <strong>{prediction.lean}</strong>
        </div>
        <div className="stat">
          <p>双选方向</p>
          <strong>{prediction.double}</strong>
        </div>
        <div className="stat">
          <p>大 2.5 球</p>
          <strong>
            {prediction.over25 === null
              ? "暂无数据"
              : percentage(prediction.over25)}
          </strong>
        </div>
      </div>
      <p className="fine-print">最可能比分 · {prediction.scoreSource}</p>
      <div>
        {prediction.likelyScores.map((score) => (
          <span className="score-chip" key={score}>
            {score}
          </span>
        ))}
      </div>
      <dl className="mt-5">
        <div className="definition">
          <dt>模型 / 版本</dt>
          <dd title={prediction.modelName}>
            {modelLabel(prediction.modelName)} / {prediction.modelVersion}
          </dd>
        </div>
        <div className="definition">
          <dt>概率来源</dt>
          <dd>{prediction.probabilitySource}</dd>
        </div>
        <div className="definition">
          <dt>赔率来源</dt>
          <dd>{prediction.oddsSource ?? "无赔率"}</dd>
        </div>
        <div className="definition">
          <dt>历史首选 / 双选命中</dt>
          <dd>
            {percentage(prediction.historicalFirstHit)} /{" "}
            {percentage(prediction.historicalDoubleHit)}
          </dd>
        </div>
        <div className="definition">
          <dt>数据来源时间</dt>
          <dd>{beijingTime(prediction.sourceAt)}</dd>
        </div>
        <div className="definition">
          <dt>本站获取时间</dt>
          <dd>{beijingTime(prediction.fetchedAt)}</dd>
        </div>
        <div className="definition">
          <dt>预测生成时间</dt>
          <dd>{beijingTime(prediction.generatedAt)}</dd>
        </div>
      </dl>
      <p className="fine-print mt-4">{prediction.sourceNote}</p>
    </>
  );
}
