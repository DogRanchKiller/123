# 项目进度

系统版本：1.4.0，与 `football_prediction/version.py` 的 `SYSTEM_VERSION` 一致。

更新日期：2026-10-24。

这份文件只描述当前状态。规则在 `AGENTS.md`、`docs/stack.md`、`docs/modules.md`、`docs/ml-stack.md`。问题记录在 [issues.md](issues.md)。

## 当前

命令行预测可以跑。网页、HTTP 接口和 `services/` 中间层还没有写。

- 联赛：英超 E0、德甲 D1、西甲 SP1。研究库 `research.db` 另含意甲 I1、法甲 F1。
- 主模型：`market_implied` / `model_market` 1.0.0（市场赔率反推比分）。无赔率时回退 `dc_xg` / `model_xg` 1.0.0。
- 实盘：`python -m football_prediction.live`；单场说明：`python -m football_prediction.explain 英超 Arsenal Chelsea`
- 多家赔率：`python -m football_prediction.data.oddsportal --hours 30`
- 回测：`python -m football_prediction.main`
- 报告：`reports/预测_YYYY-MM-DD.csv`
- 数据库：仓库根目录 `football.db`
- 定时：Windows 任务计划每天 18:07、23:37 跑 `run_daily.bat`（live + oddsportal），日志 `logs/daily.log`。

## 已完成

| 层 | 版本 | 状态 |
|---|---|---|
| data | 1.5.0 | 赛果、赔率（含亚盘 / Pinnacle / 赛程大小球）、射正、赛程、赔率快照、understat xG、OddsPortal 多家赔率 `book_odds` |
| features | 1.0.0 | 截止日之前的特征 |
| model_dc | 1.3.0 | Dixon-Coles，`shrink=0.5` |
| model_sot | 1.0.0 | 射正版，进球权重 `w=0.7` |
| model_xg | 1.0.0 | xG 版，`w=0.3`，无赔率时的兜底 |
| model_market | 1.0.0 | 由 1X2 + 大小 2.5 + 亚盘反推 λ，当前主模型 |
| model_elo | 1.1.0 | 净胜球加权更新 + 有序 logit，并行存档 |
| model_blend | 1.0.0 | dc_xg 0.77 + Elo 0.23 的 1X2 融合，并行存档 |
| model_lgbm | 1.1.0 | 在 Dixon-Coles 上做残差修正，滚动样本外 |
| calibration | 1.0.0 | Platt；2425 上没有增益，不进实盘 |
| output | 1.2.0 | 判断流程（`analysis.py`）、报告、explain 单场说明、亚盘五种结算、信心档按市场重标定 |
| validation | 1.1.0 | 时间外回测、市场基准、同场配对 |
| review | 1.3.0 | 首次预测落库、赛后评分（含大小 2.5 / 精确比分）、`promotion_check` |
| live | 1.4.0 | 更新数据、评分、预测、报告、成绩单；存档 market_implied / blend |

`2526` 留出，不在该季上重选 shrink 和权重。替换主模型只看实盘 `promotion_check`，场数至少 1000。

扩样本结论（`research.db`，5 联赛 × 1718–2526 样本外 16k 场）：自研模型每个联赛、每个赛季都不如赛前市场。提高准确率要靠赔率里还没有的信息。

## 已约定，尚未写代码

- `book_odds` 接入判断流程：多家临场赔率已入库（`book_consensus()`），报告和 explain 仍用 football-data 赛程赔率。
- `web/`：Vite + React + TypeScript。见 `docs/stack.md`。
- `server/`：FastAPI。见 `docs/stack.md`。
- `football_prediction/services/`：中间层。写 `server/` 时和 `live.py`、`explain.py`、`main.py`、`output/pipeline.py` 的编排一起落地。见 `docs/modules.md`。
- `football_prediction/model_nn/`：还没有神经网络。`requirements.txt` 里还没有 `torch`、`fastapi`、`uvicorn`。

## 版本记录

### 1.4.0（当前）

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
