# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目目标

预测比赛赛果（胜平负 / 比分 / 大小球），不是找价值投注。实盘联赛：英超 E0、德甲 D1、西甲 SP1。
主模型是市场赔率反推（`market_implied`），自研模型（Dixon-Coles 系、Elo）只作对照和无赔率时的兜底。
5 联赛 × 9 赛季、16k 场样本外回测里，自研模型每个联赛、每个赛季都不如赛前市场，融合也只改善约 0.002 log loss，命中率不变。
所以要提高准确率，靠的是赔率里还没有的信息（临场赔率、阵容），而不是改进球模型。

## 常用命令

所有命令都在仓库根目录运行，需要 `PYTHONPATH=.`。输出含中文，Windows 下加 `PYTHONIOENCODING=utf-8`。

```bash
PYTHONPATH=. python -m pytest -q
```

```bash
PYTHONPATH=. python -m pytest -q tests/test_oddsportal.py::test_collect_survives_scrape_failure
```

```bash
PYTHONPATH=. PYTHONIOENCODING=utf-8 python -u -m football_prediction.live
```

```bash
PYTHONPATH=. python -m football_prediction.explain 英超 Arsenal Chelsea
```

```bash
PYTHONPATH=. PYTHONIOENCODING=utf-8 python -u -m football_prediction.data.oddsportal --hours 30
```

- `live`：实盘闭环。更新数据（含赔率快照）→ 赛后评分 → 未开赛场次存档预测 → 报告（`reports/预测_YYYY-MM-DD.csv`）→ 实盘成绩单 → 主模型替换检查。
- `explain`：单场判断说明，只读库；可加 `--odds/--ou/--ah` 手动输入赔率。
- `data.oddsportal`：抓多家公司赔率写入 `book_odds`，约 15–25 分钟，适合放后台跑；`--no-scrape` 只打印对比表。
- `python -m football_prediction.main`：旧的回测演示（v1.3.0），训练 2122–2425、测试 2526。
- 没有配置 lint 或 build 步骤。依赖见 `requirements.txt`（lightgbm 是可选依赖，缺失时相关测试会 skip）。

## 架构

分层包 `football_prediction/`，各层通过同一个 SQLite 库（默认 `football.db`）交换数据：

- `data/`：数据层。
  - `loader.py`：football-data.co.uk 的赛季 CSV（赛果、赔率、射正）写入 `matches / match_odds / match_stats`；`fixtures.csv` 写入 `fixtures`，每次刷新同时追加 `odds_snapshots`。
  - `understat.py`：xG 写入 `match_xg`，队名用"日期±1天 + 比分相同"投票自动对齐，不手工维护映射。
  - `oddsportal.py`：调用 OddsHarvester（独立 venv `.venv-scrape`，路径可用环境变量 `ODDSHARVESTER` 覆盖）抓即将开赛比赛的多家赔率写入 `book_odds`；`book_consensus()` 返回与 fixtures 同键名的多家中位数。
- `model_dc/`（`dixon_coles`、`sot_dc` 射正版、`xg_dc` xG 版）、`model_elo/`、`model_blend/`（dc_xg + Elo）、`model_market/implied.py`（由 1X2 + 大小 2.5 + 亚盘去水概率反推 λ，再套 DC 比分矩阵）、`model_lgbm/`、`calibration/`：模型层。模型统一用 `fit(conn, league, cutoff_date)`，只用 cutoff 之前的已完赛比赛。
- `output/`：
  - `analysis.py`：判断流程，纯函数、不读库，报告与 explain 共用。流程：市场去水 → 市场隐含比分 → 自研分歧提示（8pp）→ 盘口变动（5pp 或亚盘线变化）→ 风险 → 倾向 / 双选 / 信心档。
  - `pipeline.py`：`ModelCache` 按联赛懒加载并拟合模型，`analyse_match` 把库里的数据接到 `analysis`。
  - `report.py`：生成报告；`derive.py`：从比分矩阵派生各盘口。
- `review/store.py`：`predictions` 表的存档、赛后评分、实盘成绩单（同场对比 `market_avg`）、`promotion_check`。
- `validation/backtest.py`：`run_backtest`（`refit_freq="monthly"`）、`run_market_backtest`、`paired_compare`（同场差值 + SE）。
- `live.py` / `explain.py`：入口。联赛列表 `LEAGUES` 分别在 `live.py`、`explain.py` 中定义。

## 必须遵守的约定

- **版本登记**：每个模块有 `LAYER_VERSION`，必须与 `version.py` 的 `LAYER_VERSIONS` 一致（`tests/test_versions.py` 会检查）。改了模块的行为就要同时升这两处版本号，并更新文件头 docstring 的版本说明。这样新旧预测不会混在同一个版本号下。`live.py` docstring 第二行的版本也要和 `version.get("live")` 一致。
- **预测存档不可覆盖**：每场、每个 (model_name, model_ver) 只保存开赛前的首次预测（`has_prediction` 去重），之后重跑不覆盖、不追加。报告按最新赔率现算，与存档互不影响。
- **无未来信息**：拟合只用 `match_date < cutoff` 的已完赛比赛，只对未开球的比赛预测。
- **主模型替换规则**：`version.PRIMARY_MODEL` / `FALLBACK_MODEL`；挑战者模型要在同场 ≥ `PROMOTE_MIN_N`（1000）场上满足 `差值 + 2×SE < 0` 才能替换主模型。
- **入库只补不改**：`matches` 用 INSERT OR IGNORE；`match_odds` 已有值永不覆盖，只补空列；`book_odds` 以 `(match_id, fetched_at, bookmaker, market, line)` 为键，每次抓取是一个新批次。
- **不要把历史赛季加进 `football.db`**：Elo 会遍历全部历史，加入老赛季会让实盘模型在版本号不变的情况下改变结果。扩样本研究用 `research.db`（5 联赛 1415–2526，已 gitignore），由 `_diag/expand/build_research_db.py` 从 `_cache/fd_research` 重建。老 CSV 的 `BbAv*` 列在该脚本里映射为 `Avg*`。
- 测试用内存 SQLite 和合成数据（`tests/conftest.py`），不联网、不碰 `football.db`；爬虫测试通过替换 `runner` 参数模拟。

## 数据源要点

- football-data 的 `fixtures.csv` 大约每周更新，并不是临场更新，所以临场赔率要靠 OddsPortal 爬虫。
- OddsPortal：本机出口 IP 在美国，只能看到 5 家美国公司。robots.txt 禁止抓赛季归档和 ajax 接口，因此只抓即将开赛的比赛，不能用来补历史。
  - 列表页给出的开球时间不准，配对靠"日期±1天 + 队名"。
  - 链接 slug 里的两队按字母顺序排列，真实主队以记录里的 `home_team` 为准。
  - 新队名对不上时在 `oddsportal.NAME_ALIASES` 里补别名。
- 500.com 有 WAF，球探（titan007）的 robots.txt 禁止抓赔率页，都没有采用；不要绕过反爬机制。

## 运行环境

- Windows 任务计划程序有两个任务：`FootballPredictDaily_1807` 和 `FootballPredictDaily_2337`，每天执行 `run_daily.bat`（先跑 `live`，再跑 `oddsportal --hours 30`），日志写到 `logs/daily.log`。
- `run_daily.bat` 必须保持纯 ASCII + CRLF：cmd 按 GBK 解析，含 UTF-8 中文会出错。
- `_diag/` 是诊断与研究脚本及其输出，`_cache/` 是下载缓存。按项目惯例两者都纳入版本库作备份，`football.db` 需要备份时手动提交。
