import { percentage } from "@/lib/display";
import { Icon } from "./icon";

export function DemoNotice() {
  return (
    <div className="demo-notice">
      <Icon name="info" />
      <p>
        <strong>演示数据</strong> ·
        当前展示固定样本，尚未接入真实赛程、赔率或实时比分。所有时间均为北京时间。
      </p>
    </div>
  );
}

export function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="empty-state">
      <h3>{title}</h3>
      <p>{description}</p>
    </div>
  );
}

export function ProbabilityBar({
  values,
}: {
  values: [number, number, number];
}) {
  return (
    <div aria-label="胜平负概率">
      <div className="probability-labels">
        {["主胜", "平局", "客胜"].map((label, index) => (
          <span key={label}>
            {label}
            <strong>{percentage(values[index])}</strong>
          </span>
        ))}
      </div>
      <div className="probability-track" aria-hidden="true">
        {values.map((value, index) => (
          <span key={index} style={{ width: `${value * 100}%` }} />
        ))}
      </div>
    </div>
  );
}

export function SectionHeading({
  title,
  description,
  aside,
}: {
  title: string;
  description?: string;
  aside?: React.ReactNode;
}) {
  return (
    <div className="section-heading">
      <div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {aside}
    </div>
  );
}
