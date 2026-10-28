import { ProbabilityBar, EmptyState } from "@/components/presentation";
import { beijingTime, percentage } from "@/lib/display";
import { modelLabel } from "@/lib/models";
import { AsianBlock } from "./asian-section";
import type { Prediction } from "./types";

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
    </section>
  );
}
