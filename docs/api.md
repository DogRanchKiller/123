# 接口对接说明

给调用只读接口的前端或第三方。接口由 `server/`（FastAPI）提供，只读本机的快照和库，不拟合、不写库、不联网。字段的权威定义是 [`web/openapi.json`](../web/openapi.json)（`python -m server --openapi web/openapi.json` 导出，`tests/test_server.py` 检查它和代码一致）；本文解释字段含义和约定。

## 启动与访问

```bash
python -m server                                  # http://127.0.0.1:8000 ，交互文档 /docs
python -m server --host 0.0.0.0 --port 8000       # 局域网；没有鉴权，访问范围必须在防火墙 / 路由器上限制
```

参数：`--db`（默认 `football.db`）、`--snapshot`（默认 `reports/latest_round.json`）、`--fotmob`（默认 `fotmob.db`，不存在时跳过）。路径相对启动目录，从仓库根目录启动。

- **没有鉴权、没有 CORS。** 默认只听 127.0.0.1。本项目的网站由 Next.js 服务端用 `API_URL` 直连，浏览器不直接访问接口。第三方要从浏览器调用，需要自己在前面加反向代理、鉴权和 CORS，不要把 8000 端口映射到公网。
- 数据只在实盘一轮（每天 18:07、23:37）和临场档（18:13 起每 30 分钟到 05:43）之后变化，轮询间隔 1 分钟以上即可。以 `generated_at` 判断是否有新数据。

## 通用约定

| 约定 | 说明 |
|---|---|
| 时间 | `generated_at`、`kickoff_utc`、`scored_at` 都是带时区的 ISO 8601 UTC（如 `2026-10-26T16:00:00+00:00`）。`match_date` 是 `YYYY-MM-DD`。展示时自己换成北京时间 |
| 胜平负数组 | `probabilities`、`self_models.*` 一律 `[主胜, 平, 客胜]`，和为 1 |
| 亚盘线 | 主队方向的数字：负数 = 主队让球（`-1.5` 即主让 1.5 球），正数 = 主队受让。0.25 / 0.75 是四分之一盘（赢半 / 输半）。不用中文盘口名 |
| 亚盘结算 `outcome` | 主队方向五种结算的概率，`win + half_win + push + half_lose + lose = 1` |
| 等效赢盘概率 | `p_cover`、`safe_cover`、`*_home_cover` = (赢 + 赢半/2) / (赢 + 赢半/2 + 输 + 输半/2)，不计走盘。主队方向的值为 x 时，客队方向是 1 − x |
| 概率 | 0～1 小数，4 位；`expected_goals` 2 位 |
| null | 没有该数据（无赔率、未评分、未抓到等），不是 0 |
| 联赛代码 | `E0` 英超、`D1` 德甲、`SP1` 西甲、`I1` 意甲、`F1` 法甲、`E1` 英冠、`N1` 荷甲、`P1` 葡超、`SC0` 苏超、`B1` 比甲、`T1` 土超；`league_name` 给中文名 |
| `match_id` | 后端生成的 16 位十六进制字符串（联赛、赛季、日期、两队的 SHA-1 前 16 位），稳定，用作详情路径；不要自己按队名拼 |
| 队名 | `home` / `away` 是英文库名（football-data 写法）。中文名和队徽由网站自己映射（`web/src/features/match/teams.ts`、`crests.json`），接口不提供 |

## 接口

### `GET /api/matches?recent_days=3`

本轮未开赛场次的看法 + 最近已开球场次。`recent_days` 取 0～14，默认 3，0 为不附带。

```json
{
  "generated_at": "2026-10-26T14:43:07+00:00",
  "system_version": "1.12.0",
  "primary_model": {"name": "market_implied", "version": "1.0.0"},
  "matches": [MatchView, ...],
  "recent":  [{"match": MatchInfo, "archived": ArchivedPrediction, "near_archived": ArchivedPrediction | null}, ...]
}
```

- `matches` 只含快照里**现在还没开球**的场次（按请求时刻过滤）。
- `recent` 按开球时间倒序；`archived` 是开赛前首次存档，`near_archived` 是开球前 1.5 小时内的临场档（没有时为 null）。
- 状态码：200；还没跑过实盘一轮（无快照）时 503；库正被实盘写入、超过等待时间时 503（稍后重试）。

### `GET /api/matches/{match_id}`

```json
{"match": MatchInfo, "current": MatchView | null, "archived": ArchivedPrediction | null,
 "near_archived": ArchivedPrediction | null, "generated_at": "..." | null}
```

`current` 只在该场还在本轮快照里时有值。快照和库里都没有这场时 404，库暂时打不开时 503。

### `GET /api/review`

实盘成绩单：`{"generated_at", "system_version", "primary_model", "scorecard": [ScorecardRow, ...]}`，按 `log_loss` 升序。无快照时 503。

## MatchView：本轮看法

实盘一轮按最新赔率现算后写进快照；赔率选法是 24 小时内 ≥3 家公司的中位数优先，否则用赛程表赔率。

| 字段 | 含义 |
|---|---|
| `match_id` `league` `league_name` `home` `away` `kickoff_utc` `match_date` | 对阵与时间；`kickoff_utc` 可能为 null（只知道日期） |
| `model_name` `model_version` | 给出这份看法的模型。有赔率时 `market_implied`（市场赔率反推，主模型）；没有赔率时 `dc_market`（自研兜底） |
| `odds_source` | 赔率来源说明（如"多家中位数（4 家，北京 10-26 22:45 抓取）"）；无赔率时 null |
| `asian` | 亚盘，见下表。**这是主看法** |
| `probabilities` | 胜平负 `[主, 平, 客]` |
| `probability_source` | `市场`（赔率 Shin 去水）或 `dc_market`（无赔率） |
| `score_source` | 比分矩阵来源：`市场隐含`；`dc_market（无赔率）`；`dc_market（缺大小球盘）` |
| `lean` / `double` | 胜平负首选（`主胜` / `平` / `客胜`）/ 前二（如 `主胜或平`） |
| `confidence` | 胜平负信心档 `高` / `中` / `低`，按最大概率分：≥0.60 高，≥0.45 中 |
| `historical_first_hit` `historical_double_hit` | 该信心档历史上首选 / 前二的命中率（固定标定值） |
| `estimated_first_hit` `estimated_double_hit` | 本场的首选 / 前二概率（就是概率本身，不是另一个模型） |
| `recommended` `recommendation_note` | 重点场：有赔率且胜平负档为"高"。`recommendation_note` 形如"胜平负高把握 · 主胜 70% · 亚盘稳妥 客+2.00 67%"；非重点为 null |
| `expected_goals` | `[主, 客]` 预期进球 |
| `likely_scores` | 概率最高的 5 个比分 `{"score": "2-1", "prob": 0.0953}` |
| `over25` `btts` | 大 2.5 球概率、两队都进球概率 |
| `self_models` | 自研模型的胜平负 `{"dc_market": [...], "dc_xg": [...], "elo": [...], "blend": [...]}`，只作对照 |
| `movement` | 胜平负盘口变动说明（主胜概率变化 ≥5pp 才有），否则 null |
| `hints` | 文字提示：自研模型与市场在胜平负或同一亚盘线上分歧 >8pp。**只是提示，历史上市场更准** |
| `risks` | 风险提示：缺胜平负赔率、缺大小球盘、各盘口之间拟合误差大 |

### `asian`（主队方向）

| 字段 | 含义 |
|---|---|
| `line` | 用来判断的亚盘线 |
| `line_source` | `市场线`（有亚盘赔率）或 `公平线`（无亚盘赔率时由比分矩阵算出最接近五五开的线） |
| `outcome` | 主队在该线上五种结算的概率 |
| `side` | 选择方 `主` / `客`：主队等效赢盘概率 ≥0.5 选主 |
| `p_cover` | 选择方的等效赢盘概率 |
| `tier` / `historical_hit` | 亚盘信心档：`p_cover` ≥0.56 高（历史命中 0.607）、≥0.54 中（0.60）、其余低（0.517）；公平线时 `"-"` / null |
| `safe_line` / `safe_cover` | 稳妥线：从选择方往受让方向每次退 0.25 球，直到选择方等效赢盘概率 ≥0.65 的最近一条线（主队方向写法：选主时线变大，如 −1.5 → −1.0；选客时线变小，如 −1.5 → −2.0 即客 +2.0）；找不到时 null |
| `market_home_cover` | 只看该线去水水位的主队赢盘概率 |
| `self_home_cover` | 自研 `dc_market` 在同一条线上的主队赢盘概率；对照用 |
| `movement` | 亚盘线与水位轨迹：初盘 → 最新快照 → 定价 |

**怎么理解亚盘选边**（`_diag/ah_direction/result.txt`，33430 场）：选边和"只看亚盘水位"同边 93～96%，`p_cover` 平均约 0.52，长期命中约 0.51～0.53。它是市场自己的判断，接近五五开；约 55% 的场次选冷门、53% 选客队，这是市场深盘定价的结果。展示时不要把它包装成高把握推荐。胜平负倾向主胜、亚盘却选客队（主队赢球但赢不够盘）是正常现象，两者回答的是不同问题。

## ArchivedPrediction：首次存档

每场每个模型只保留开赛前的**首次**预测，之后不覆盖，用于赛后评分。字段与 MatchView 同名的含义相同。

| 字段 | 含义 |
|---|---|
| `model_name` `model_version` `generated_at` | 存档的模型与时刻 |
| `horizon` | `pre` 赛前首次（约开球前 24 小时）；`t1` 临场（开球前 1.5 小时内，多家中位数） |
| `n_books` `hours_to_ko` | 临场档用了几家公司、离开球几小时 |
| `asian` | 同 MatchView 的 `asian`，少三个对照字段；可能为 null |
| `odds` | 存档时用的赔率：`avg_h/d/a` 胜平负、`avg_over25/under25`、`ah_line` 与 `avg_ahh/aha` 亚盘主 / 客水位 |
| `scored` | 是否已评分；以下字段未评分时为 null |
| `actual_outcome` | `home_win` / `draw` / `away_win` |
| `log_loss` `brier` | 胜平负评分（越小越好） |
| `ou25_log_loss` `score_log_loss` `ah_log_loss` | 大小 2.5、比分、亚盘五种结算的 log loss |
| `ah_hit` | 亚盘选择方是否赢盘：1 / 0；走盘为 null。**赢半算 1、输半算 0**，四分之一盘上偏粗 |
| `result_src` `scored_at` | 赛果来源与评分时刻 |

`MatchInfo` 是对阵信息，`score` 为 `{"home", "away"}` 或 null；`score_source` 为 `football-data`（正式）或 `fotmob`（football-data 未到时的临时比分，到达后会核对重评）。

## ScorecardRow：成绩单

| 字段 | 含义 |
|---|---|
| `model_name` `model_ver` `matches` | 模型、版本、已评分场数 |
| `log_loss` `brier` `hit_rate` | 胜平负 |
| `ou25_ll` `score_ll` | 大小 2.5、比分 log loss |
| `ah_n` `ah_ll` `ah_hit` | 亚盘评分场数、log loss、选择方命中（口径同上，只作参考） |
| `paired_n` `diff_vs_base` `se` | 和市场基准 `market_avg` 在同一批比赛上的 log loss 差与标准误；负数表示比市场好，`|差| < 2×SE` 视为无差异 |

`_t1` / `_t2` 结尾的模型名是临场档（`_t2` 是开球前 0.6 小时内）。实盘样本目前只有几十场，数字波动很大。

## 前端生成类型

```bash
python -m server --openapi web/openapi.json
cd web && npm run api:types        # 生成 src/api/schema.d.ts，禁止手改
```

字段只增不改是目标，但目前没有接口版本号；`system_version` 变化时请对照 `web/openapi.json` 的 diff。
