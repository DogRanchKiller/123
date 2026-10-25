import { DemoNotice } from "@/components/presentation";

export interface ReviewRow {
  name: string;
  version: string;
  samples: number;
  logLoss: string;
  brier: string;
  hitRate: string;
}

export function Review({ rows }: { rows: readonly ReviewRow[] }) {
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">LOOK BACK / 赛后验证</p>
          <h1>让每一次预测，经得起回看。</h1>
          <p>基于首次预测存档，展示模型的赛后表现。</p>
        </div>
        <span className="pill">指标越低越好 · Log Loss / Brier</span>
      </div>
      <DemoNotice />
      <section className="panel">
        <h2>模型成绩单</h2>
        <p className="muted mt-2 mb-5">
          以下为界面展示样本，不代表项目真实评测结果。
        </p>
        <div
          className="table-wrap"
          tabIndex={0}
          aria-label="模型成绩单，可横向滚动"
        >
          <table>
            <thead>
              <tr>
                <th>模型</th>
                <th>版本</th>
                <th>已评分场次</th>
                <th>Log Loss</th>
                <th>Brier</th>
                <th>首选命中率</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.name}>
                  <td>
                    <strong>{row.name}</strong>
                  </td>
                  <td>{row.version}</td>
                  <td>{row.samples}</td>
                  <td>{row.logLoss}</td>
                  <td>{row.brier}</td>
                  <td>{row.hitRate}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <div className="grid gap-5 md:grid-cols-2 mt-6">
        <section className="panel side-panel">
          <h3>只评价首次预测</h3>
          <p>
            比赛开始前的首次预测被保留用于评分，后续赔率变化不会改写这份记录。
          </p>
        </section>
        <section className="panel side-panel !mt-0">
          <h3>命中率之外，也看概率</h3>
          <p>
            Log Loss 与 Brier
            衡量概率预测的质量。样本数量、版本和同场比较会影响指标的解释。
          </p>
        </section>
      </div>
    </>
  );
}
