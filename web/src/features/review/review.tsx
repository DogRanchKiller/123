import { DataNotice, EmptyState } from "@/components/presentation";
import { percentage, type DataSource } from "@/lib/display";
import { modelLabel } from "@/lib/models";

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
  /** 同一档的市场基准（赛前档 market_avg，临场档 market_avg_t1 / _t2 / _t24）。 */
  base: string;
  /** 与 base 同场配对的场数、差值和 SE；差值为负表示优于市场。基准自身为空。 */
  pairedMatches: number | null;
  diffVsMarket: number | null;
  se: number | null;
}

/** 对应 Python `review/scorecard.closing_report()` 的一行：各模型对收盘平均赔率的同场差，只作参照。 */
export interface ClosingRow {
  name: string;
  version: string;
  /** 有收盘赔率的已评分场数。 */
  pairedMatches: number;
  logLoss: number | null;
  /** 差值为负表示比收盘好；收盘自身为空。 */
  diffVsClose: number | null;
  se: number | null;
}

function fixed(value: number | null): string {
  return value === null ? "暂无数据" : value.toFixed(4);
}

function share(value: number | null): string {
  return value === null ? "暂无数据" : percentage(value);
}

function diff(value: number | null, se: number | null, n: number | null, self: string): string {
  if (value === null || se === null) return self;
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(4)} ± ${se.toFixed(4)}（${n ?? 0} 场）`;
}

/** 当前主模型（接口 primary_model）；旧快照没有时为空。 */
export interface PrimaryModel {
  name: string;
  version: string;
}

function isPrimary(row: { name: string; version: string }, primary: PrimaryModel | null): boolean {
  return primary !== null && row.name === primary.name && row.version === primary.version;
}

export function Review({
  rows,
  closing = [],
  primary = null,
  source,
}: {
  rows: readonly ReviewRow[];
  closing?: readonly ClosingRow[];
  primary?: PrimaryModel | null;
  source: DataSource;
}) {
  const primaryGraded = rows.some((row) => isPrimary(row, primary));
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">回看 / 赛后验证</p>
          <h1>让每一次预测，经得起回看。</h1>
          <p>基于首次预测存档，展示模型的赛后表现。亚盘为主，胜平负为辅。</p>
        </div>
        <span className="pill">指标越低越好 · 对数损失 / 布里尔分数</span>
      </div>
      <DataNotice source={source} />
      <section className="panel">
        <h2>模型成绩单</h2>
        <p className="muted mt-2 mb-5">
          {source.mode === "demo"
            ? "以下为界面展示样本，不代表项目真实评测结果。"
            : "实盘首次存档的赛后评分，按胜平负对数损失升序；样本少时差异不稳定。"}
        </p>
        {primary && (
          <p className="fine-print mb-4">
            当前主模型：
            <strong title={primary.name}>{modelLabel(primary.name)}</strong> {primary.version}
            {primaryGraded
              ? "，表中标「主模型」的一行。"
              : "，还没有已评分的场次（开赛前首次存档，比赛结束并评分后出现在表中）。"}
          </p>
        )}
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
                <th>亚盘对数损失</th>
                <th>亚盘命中</th>
                <th>胜平负场次</th>
                <th>对数损失</th>
                <th>布里尔分数</th>
                <th>首选命中率</th>
                <th>对比基准</th>
                <th>同场对比</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={`${row.name}-${row.version}`}
                  className={isPrimary(row, primary) ? "row-primary" : undefined}
                >
                  <td>
                    <strong title={row.name}>{modelLabel(row.name)}</strong>
                    {isPrimary(row, primary) && <span className="pill pill-accent ml-2">主模型</span>}
                  </td>
                  <td>{row.version}</td>
                  <td>{row.asianMatches}</td>
                  <td>{fixed(row.asianLogLoss)}</td>
                  <td>{share(row.asianHit)}</td>
                  <td>{row.matches}</td>
                  <td>{fixed(row.logLoss)}</td>
                  <td>{fixed(row.brier)}</td>
                  <td>{share(row.hitRate)}</td>
                  <td title={row.base}>{modelLabel(row.base)}</td>
                  <td>{diff(row.diffVsMarket, row.se, row.pairedMatches, "基准")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        )}
        <p className="fine-print mt-3">
          亚盘命中不计走盘。每个模型对同一时点的市场平均赔率（赛前档对赛前，临场档对同一临场档）。
          同场对比为差值 ± 标准误，负数表示优于市场；|差值| 小于 2 倍标准误视为无显著差异。
        </p>
      </section>
      {closing.length > 0 && (
        <section className="panel mt-6">
          <h2>对收盘赔率（参照）</h2>
          <p className="muted mt-2 mb-5">
            收盘平均赔率按比例去水后作为参照。收盘在存档时还看不到，这张表只看差距，不参与替换主模型。
          </p>
          <div
            className="table-wrap"
            tabIndex={0}
            aria-label="对收盘赔率参照，可横向滚动"
          >
            <table>
              <thead>
                <tr>
                  <th>模型</th>
                  <th>版本</th>
                  <th>有收盘的场次</th>
                  <th>对数损失</th>
                  <th>同场对比收盘</th>
                </tr>
              </thead>
              <tbody>
                {closing.map((row) => (
                  <tr
                    key={`${row.name}-${row.version}`}
                    className={isPrimary(row, primary) ? "row-primary" : undefined}
                  >
                    <td>
                      <strong title={row.name}>{modelLabel(row.name)}</strong>
                      {isPrimary(row, primary) && <span className="pill pill-accent ml-2">主模型</span>}
                    </td>
                    <td>{row.version || "—"}</td>
                    <td>{row.pairedMatches}</td>
                    <td>{fixed(row.logLoss)}</td>
                    <td>{diff(row.diffVsClose, row.se, row.pairedMatches, "参照")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
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
            场，且胜平负对数损失的差值加 2 倍标准误仍小于 0。
          </p>
        </section>
      </div>
    </>
  );
}
