import { DataNotice, EmptyState } from "@/components/presentation";
import { percentage, type DataSource } from "@/lib/display";

/** 对应 Python `review/scorecard.live_report()` 的一行；数值由页面格式化。 */
export interface ReviewRow {
  name: string;
  version: string;
  /** 已评分场数（胜平负）。 */
  matches: number;
  logLoss: number | null;
  brier: number | null;
  hitRate: number | null;
  /** 有亚盘评分的场数；亚盘只作参考，不进替换检查。 */
  asianMatches: number;
  /** 市场线五种结算的 log loss；无亚盘评分时为空。 */
  asianLogLoss: number | null;
  /** 选择方赢盘命中率，走盘不计；无亚盘评分时为空。 */
  asianHit: number | null;
  /** 与 market_avg 同场配对的场数、差值和 SE；差值为负表示优于市场。基准自身为空。 */
  pairedMatches: number | null;
  diffVsMarket: number | null;
  se: number | null;
}

function fixed(value: number | null): string {
  return value === null ? "暂无数据" : value.toFixed(4);
}

function share(value: number | null): string {
  return value === null ? "暂无数据" : percentage(value);
}

function paired(row: ReviewRow): string {
  if (row.diffVsMarket === null || row.se === null) return "基准";
  const sign = row.diffVsMarket > 0 ? "+" : "";
  return `${sign}${row.diffVsMarket.toFixed(4)} ± ${row.se.toFixed(4)}（${row.pairedMatches ?? 0} 场）`;
}

export function Review({
  rows,
  source,
}: {
  rows: readonly ReviewRow[];
  source: DataSource;
}) {
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">LOOK BACK / 赛后验证</p>
          <h1>让每一次预测，经得起回看。</h1>
          <p>基于首次预测存档，展示模型的赛后表现。亚盘为主，胜平负为辅。</p>
        </div>
        <span className="pill">指标越低越好 · Log Loss / Brier</span>
      </div>
      <DataNotice source={source} />
      <section className="panel">
        <h2>模型成绩单</h2>
        <p className="muted mt-2 mb-5">
          {source.mode === "demo"
            ? "以下为界面展示样本，不代表项目真实评测结果。"
            : "实盘首次存档的赛后评分，按胜平负 Log Loss 升序；样本少时差异不稳定。"}
        </p>
        {rows.length === 0 ? (
          <EmptyState
            title="暂无已评分的实盘场次"
            description="比赛结束、赛果入库并评分后，这里会出现各模型的成绩。"
          />
        ) : (
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
                <th>亚盘场次</th>
                <th>亚盘 Log Loss</th>
                <th>亚盘命中</th>
                <th>胜平负场次</th>
                <th>Log Loss</th>
                <th>Brier</th>
                <th>首选命中率</th>
                <th>同场对比 market_avg</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.name}-${row.version}`}>
                  <td>
                    <strong>{row.name}</strong>
                  </td>
                  <td>{row.version}</td>
                  <td>{row.asianMatches}</td>
                  <td>{fixed(row.asianLogLoss)}</td>
                  <td>{share(row.asianHit)}</td>
                  <td>{row.matches}</td>
                  <td>{fixed(row.logLoss)}</td>
                  <td>{fixed(row.brier)}</td>
                  <td>{share(row.hitRate)}</td>
                  <td>{paired(row)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        )}
        <p className="fine-print mt-3">
          亚盘命中不计走盘。同场对比为差值 ± SE，负数表示优于市场；|差值| 小于
          2 倍 SE 视为无显著差异。
        </p>
      </section>
      <div className="grid gap-5 md:grid-cols-2 mt-6">
        <section className="panel side-panel">
          <h3>只评价首次预测</h3>
          <p>
            比赛开始前的首次预测被保留用于评分，后续赔率变化不会改写这份记录。
          </p>
        </section>
        <section className="panel side-panel !mt-0">
          <h3>替换主模型只看胜平负</h3>
          <p>
            亚盘成绩只作参考。替换主模型要求同一批已评分比赛不少于 1000
            场，且胜平负 Log Loss 的差值加 2 倍 SE 仍小于 0。
          </p>
        </section>
      </div>
    </>
  );
}
