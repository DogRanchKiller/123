# 项目进度

系统版本：1.3.0，与 `football_prediction/version.py` 的 `SYSTEM_VERSION` 一致。

更新日期：2026-10-24。

这份文件只描述当前状态。规则在 `AGENTS.md`、`docs/stack.md`、`docs/modules.md`、`docs/ml-stack.md`。问题记录在 [issues.md](issues.md)。

## 当前

命令行预测可以跑。网页、HTTP 接口和 `services/` 中间层还没有写。

- 联赛：英超 E0、德甲 D1、西甲 SP1。
- 主模型：`dc_xg` / `model_xg` 1.0.0。报告只展示它。
- 实盘：`.venv/bin/python -m football_prediction.live`
- 回测：`.venv/bin/python -m football_prediction.main`
- 报告：`reports/预测_YYYY-MM-DD.csv`
- 数据库：仓库根目录 `football.db`

## 已完成

| 层 | 版本 | 状态 |
|---|---|---|
| data | 1.3.0 | 赛果、赔率、射正、赛程、understat xG |
| features | 1.0.0 | 截止日之前的特征 |
| model_dc | 1.3.0 | Dixon-Coles，`shrink=0.5` |
| model_sot | 1.0.0 | 射正版，进球权重 `w=0.7` |
| model_xg | 1.0.0 | xG 版，`w=0.3`，当前主模型 |
| model_elo | 1.0.0 | Elo，并行存档 |
| model_lgbm | 1.1.0 | 在 Dixon-Coles 上做残差修正，滚动样本外 |
| calibration | 1.0.0 | Platt；2425 上没有增益，不进实盘 |
| output | 1.1.0 | 比分矩阵分解、主模型报告 |
| validation | 1.1.0 | 时间外回测、市场基准、同场配对 |
| review | 1.2.0 | 首次预测落库、赛后评分、`promotion_check` |
| live | 1.3.0 | 更新数据、评分、预测、报告、成绩单 |

`2526` 留出，不在该季上重选 shrink 和权重。替换主模型只看实盘 `promotion_check`，场数至少 1000。

## 已约定，尚未写代码

- `web/`：Vite + React + TypeScript。见 `docs/stack.md`。
- `server/`：FastAPI。见 `docs/stack.md`。
- `football_prediction/services/`：中间层。写 `server/` 时和 `live.py`、`main.py` 的编排一起落地。见 `docs/modules.md`。
- `football_prediction/model_nn/`：还没有神经网络。`requirements.txt` 里还没有 `torch`、`fastapi`、`uvicorn`。

## 版本记录

### 1.3.0（当前）

数据层写入 understat xG。Dixon-Coles 对单队参数做收缩。实盘输出主模型报告，成绩单含命中率，并检查能否替换主模型。主模型定为 xG 版 Dixon-Coles。

更早的层版本写在 `version.py` 各条目的注释里。这里不重复。

## 更新这份文件时

1. 开头的系统版本改成 `version.py` 里的 `SYSTEM_VERSION`。
2. 改「当前」和「已完成」里变了的行。
3. 系统版本变了，就在「版本记录」顶部加一节，只写这次行为变化。
4. 只改变「已约定，尚未写代码」的状态时，改那一节，不升 `SYSTEM_VERSION`。
5. 日期用改动当天。
