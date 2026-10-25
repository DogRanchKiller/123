# 项目进度

系统版本：1.7.0，与 `football_prediction/version.py` 的 `SYSTEM_VERSION` 一致。

更新日期：2026-10-25。

这份文件只描述当前状态。规则在 `AGENTS.md`、`docs/stack.md`、`docs/modules.md`、`docs/ml-stack.md`。问题记录在 [issues.md](issues.md)。

## 当前

命令行预测可以跑。网页、HTTP 接口和 `services/` 中间层还没有写。

- 联赛：英超 E0、德甲 D1、西甲 SP1、意甲 I1、法甲 F1（实盘库都从 2122 起）。研究库 `research.db` 为同 5 联赛 9394–2526（赔率从 0001 起，xG 从 1415 起）。
- 主模型：`market_implied` / `model_market` 1.0.0（市场赔率反推比分）。无赔率时回退 `dc_xg` / `model_xg` 1.0.0。
- 实盘：`python -m football_prediction.live`；单场说明：`python -m football_prediction.explain 英超 Arsenal Chelsea`
- 多家赔率：`python -m football_prediction.data.oddsportal --hours 30`
- 临场档：`python -m football_prediction.live --near`（`run_near.bat`）；阵容 / 伤停：`python -m football_prediction.data.fotmob`
- FotMob 库：仓库根目录 `fotmob.db`（gitignore，可由 `_cache/fotmob/` 重建）
- 回测：`python -m football_prediction.main`
- 报告：`reports/预测_YYYY-MM-DD.csv`
- 数据库：仓库根目录 `football.db`
- 定时：Windows 任务计划每天 18:07、23:37 跑 `run_daily.bat`（live + oddsportal + fotmob 阵容），日志 `logs/daily.log`；`FootballPredictNear` 每天 18:13–05:43 每 30 分钟跑 `run_near.bat`，日志 `logs/near.log`（需开机）。

## 已完成

| 层 | 版本 | 状态 |
|---|---|---|
| data | 1.6.0 | 赛果、赔率（含亚盘 / Pinnacle / 赛程大小球）、射正、赛程、赔率快照、understat xG、OddsPortal 多家赔率 `book_odds`；意甲 / 法甲 2122–2627 已入实盘库 |
| data_fotmob | 1.0.0 | FotMob HTML 页：阵容（预测 / 正式）、伤停、球员分钟与 xG / xA、射门；understat 缺时补 `match_xg`。历史补抓进行中（E0 / D1 / SP1 2324 起） |
| features | 1.0.0 | 截止日之前的特征 |
| model_dc | 1.3.0 | Dixon-Coles，`shrink=0.5` |
| model_sot | 1.0.0 | 射正版，进球权重 `w=0.7` |
| model_xg | 1.0.0 | xG 版，`w=0.3`，无赔率时的兜底 |
| model_dc_market | 1.0.0 | 进球与历史赔率 λ 混合估强度（w=0.3），并行存档 `dc_market`；2526 留出对 dc_xg −0.0059±0.0022，仍比市场差 0.0095 |
| model_market | 1.0.0 | 由 1X2 + 大小 2.5 + 亚盘反推 λ，当前主模型 |
| model_market_shin | 1.0.0 | Shin 去水的市场隐含，并行存档 `market_shin`；选参期 1X2 −0.00025±0.00007，2526 留出 −0.00028±0.00028 |
| model_lineup | 1.1.0 | 球员评分、常规首发、阵容特征、λ 调整；合并规则按赔率与首发先后选 `COEF_PRE` / `COEF_POST`，两套都为 0（3 联赛 2526 留出 1214 场无增益，见 issues） |
| model_elo | 1.1.0 | 净胜球加权更新 + 有序 logit，并行存档 |
| model_blend | 1.0.0 | dc_xg 0.77 + Elo 0.23 的 1X2 融合，并行存档 |
| model_lgbm | 1.1.0 | 在 Dixon-Coles 上做残差修正，滚动样本外 |
| calibration | 1.0.0 | Platt；2425 上没有增益，不进实盘 |
| output | 1.4.0 | 判断流程（`analysis.py`）、报告、explain 单场说明、亚盘五种结算；信心档按 Shin 概率在 5 联赛重标定，报告与 explain 列本场命中估计；报告与 explain 优先用多家中位数赔率（`pipeline.latest_odds`），列赔率来源 |
| validation | 1.1.0 | 时间外回测、市场基准、同场配对 |
| review | 1.4.0 | 首次预测落库、赛后评分（含大小 2.5 / 精确比分）、`promotion_check`（跳过 `_t1`）、`horizon_report` 临场对赛前 |
| live | 1.7.0 | 5 联赛；更新数据、评分、预测、报告、成绩单；存档 market_implied / blend / market_shin / dc_market；`--near` 临场档 `*_t1` 与 lineup_t1 / lineup_base_t1，先抓阵容再抓赔率，打印临场最终看法 |

`2526` 留出，不在该季上重选 shrink 和权重。替换主模型只看实盘 `promotion_check`，场数至少 1000。

扩样本结论（`research.db`，5 联赛 × 1718–2526 样本外 16k 场）：自研模型每个联赛、每个赛季都不如赛前市场。提高准确率要靠赔率里还没有的信息。

## 已约定，尚未写代码

- 兜底模型：建议把 `FALLBACK_MODEL` 换成 `dc_market`（回测在 4/5 联赛优于 dc_xg），由用户决定；按规则也可等实盘配对。
- 临场档信心档：`MARKET_TIERS` 已按 Shin 赛前概率重标（output 1.3.0）；临场档（T1 多家中位数）有实盘样本后再核对档位命中率。
- 多家中位数的准确度：报告已改用 OddsPortal 多家中位数（只有 5 家美国公司），它与 football-data 平均赔率哪个更准，等 `horizon_report` 和赛前存档有足够已评分场次后再比；赛前存档仍用赛程表赔率。
- `web/`：Vite + React + TypeScript。见 `docs/stack.md`。
- `server/`：FastAPI。见 `docs/stack.md`。
- `football_prediction/services/`：中间层。写 `server/` 时和 `live.py`、`explain.py`、`main.py`、`output/pipeline.py` 的编排一起落地。见 `docs/modules.md`。
- `football_prediction/model_nn/`：还没有神经网络。`requirements.txt` 里还没有 `torch`、`fastapi`、`uvicorn`。

## 版本记录

### 1.7.0（当前）

主模型、存档和比分算法不变。报告与 explain 的定价赔率改由 `pipeline.latest_odds` 选：OddsPortal 多家中位数在 24 小时内、≥3 家、1X2 与大小 2.5 都齐时用它，否则用 football-data 赛程表快照（赛程表约每周更新一次，常比多家赔率旧）。报告新增「赔率来源」列，explain 第 [1] 段写明来源。盘口变动仍只在赛程表快照之间比，不跨来源。赛前存档（`live._predict_upcoming`）仍用赛程表赔率，存档口径不变（output 1.4.0）。

### 1.6.0

主模型、存档模型和比分算法不变。信心档改用 Shin 去水的首选概率分档，在 5 联赛 1213–2425 上重标定（高 72%/89%、中 52%/79%、低 41%/71%；2526 留出一致），意甲法甲不再借用三联赛的数字；报告与 explain 加「本场估计（首选/双选）」。阵容合并规则（model_lineup 1.1.0）：系数分 `COEF_PRE`（赔率早于首次看到正式首发）与 `COEF_POST`（赔率不早于首发），一场只叠一次；两套系数都定为 0（FotMob 历史补完后 2526 留出 1214 场：对赛前 +0.0008±0.0010、对收盘 +0.0007±0.0007，无增益），`lineup_t1` 仍等于 `lineup_base_t1`。`live --near`（1.7.0）改为先抓阵容再抓赔率，每场打印临场最终看法（不存档）。建了临场计划任务 `FootballPredictNear`，`init_db` 加 120 秒锁等待。比分形状研究（25k 场）：固定 rho −0.05 的比分 log loss 最好，自由 rho 与 −0.10 只在 1X2 / BTTS 上好 0.0004–0.0005，留出期都不显著，不改 rho（`_diag/explore/score_shape.log`）。

### 1.5.0

报告与主模型不变，新增并行存档和临场档。并行存档：`market_shin`（Shin 去水）、`dc_market`（历史赔率 λ 估强度的 DC，候选兜底）。`live --near` 在开球前 1.5 小时内用多家中位数赔率（≥3 家、90 分钟内）存 `market_avg_t1` / `market_implied_t1` / `market_shin_t1`；有正式首发时另存 `lineup_t1` 与配对基准 `lineup_base_t1`。成绩单新增 `horizon_report`（临场档对赛前档同场配对），`_t1` 不进 `promotion_check`。数据新增 FotMob（阵容、伤停、球员 xG，单独的 `fotmob.db`），understat 缺 xG 时用它补。实盘联赛加意甲 I1、法甲 F1（data 1.6.0 / live 1.6.0）：与另外三联赛同为 2122 起，模型按联赛分别拟合，原三联赛的预测不变；信心档命中率仍是三联赛标定的，用在意甲法甲上待实盘核对。

### 1.4.0

判断流程改为以市场为底：去水 → 市场隐含比分 → 自研分歧提示 → 盘口变动 → 风险 → 倾向 / 双选 / 信心档。主模型改为 `market_implied`（2324–2627 三联赛 n=3411，相对 dc_xg 1X2 −0.0163±0.0025，各赛季同向），无赔率回退 dc_xg。新增 explain 单场说明、Elo 1.1.0、dc_xg + Elo 融合存档。数据层 1.5.0 加入 OddsPortal 多家赔率（未接入判断流程）。

### 1.3.0

数据层写入 understat xG。Dixon-Coles 对单队参数做收缩。实盘输出主模型报告，成绩单含命中率，并检查能否替换主模型。主模型定为 xG 版 Dixon-Coles。

更早的层版本写在 `version.py` 各条目的注释里。这里不重复。

## 更新这份文件时

1. 开头的系统版本改成 `version.py` 里的 `SYSTEM_VERSION`。
2. 改「当前」和「已完成」里变了的行。
3. 系统版本变了，就在「版本记录」顶部加一节，只写这次行为变化。
4. 只改变「已约定，尚未写代码」的状态时，改那一节，不升 `SYSTEM_VERSION`。
5. 日期用改动当天。
