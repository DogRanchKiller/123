# 足球预测系统

仓库根目录的可运行项目是 `football_prediction`（实盘联赛：英超 E0 / 德甲 D1 / 西甲 SP1）。在仓库根目录工作，数据库与报告路径都相对 cwd。

目标是预测比赛赛果（胜平负 / 比分 / 大小球），不是找价值投注。主模型是市场赔率反推（`market_implied`），自研模型（Dixon-Coles 系、Elo）只作对照和无赔率时的兜底：5 联赛 × 9 赛季、16k 场样本外回测里，自研模型每个联赛、每个赛季都不如赛前市场，融合只改善约 0.002 log loss，命中率不变。要提高准确率，靠的是赔率里还没有的信息（临场赔率、阵容），而不是改进球模型。

`大模型项目/` 只作**训练方式参考**（微调、P-Tuning / PET、RAG、Function Call 等写法）。它不是足球预测模型的代码、数据或依赖，不参与 `football_prediction` 的训练、预测和评分。

- 用户问训练做法、或要给本系统加新的训练流程时，可以读它借鉴步骤和结构，然后在 `football_prediction` 里用本系统的比赛数据实现。
- 不要把它的模型权重、数据集、checkpoint 或包引进预测链路，也不要把它的结果写进 `football.db` 或 `reports/`。
- 不要改这个目录，除非用户明确要改参考材料本身。

## 检索

前后端与训练的选型在 [`docs/stack.md`](docs/stack.md)。模块边界、前后端分隔、中间层、单文件长度在 [`docs/modules.md`](docs/modules.md)。训练和分析的实现规则在 [`docs/ml-stack.md`](docs/ml-stack.md)。

新增目录、拆文件、加 HTTP 接口，或让命令行和接口走同一条流程时，先读 `docs/modules.md`。遇到下面任一情况时先读 `docs/ml-stack.md`，再读对应技能并按其步骤做完：

| 情况 | 技能文件 |
|---|---|
| 训练、PyTorch、训练循环、checkpoint、新的神经网络 | [`.agents/skills/pytorch-training/SKILL.md`](.agents/skills/pytorch-training/SKILL.md) |
| 分析、NumPy、矩阵、分布、Log Loss、Brier、回测数值 | [`.agents/skills/numpy-analysis/SKILL.md`](.agents/skills/numpy-analysis/SKILL.md) |
| Transformers、Hugging Face、Trainer、tokenizer、预训练权重 | [`.agents/skills/transformers-framework/SKILL.md`](.agents/skills/transformers-framework/SKILL.md) |

技能正文是步骤，规则以 `docs/ml-stack.md` 为准。Codex 读 `.agents/skills/`，Claude Code 读 `.claude/skills/`。`.agents/skills/` 是唯一源；`.claude/skills/` 是它的真实副本（不用符号链接，Windows 检出会坏），Mac 和 Windows 都能直接用。

- 只在 `.agents/skills/` 里改技能，改完运行 `python .agents/sync_skills.py`，两边一起提交。
- 不要直接改 `.claude/skills/`。`tests/test_skills_sync.py` 检查两边一致，不一致时测试失败。

## 进度与问题

当前做到哪，只看 [`docs/progress.md`](docs/progress.md)。问题的现象、原因和处理，只看 [`docs/issues.md`](docs/issues.md)。不要另建进度文件或问题文件。

两份文档描述的系统以 `football_prediction/version.py` 为准。进度开头的系统版本必须等于 `SYSTEM_VERSION`。文档和代码不一致时，先把文档改到代码的版本，再继续新工作。

- 用户问进度、下一步，或动手做「已约定，尚未写代码」里的事情之前，先读 `docs/progress.md`。
- 用户报错、排查异常，或怀疑是已知问题时，先读 `docs/issues.md`。
- 行为变化并升了 `SYSTEM_VERSION` 或任一 `LAYER_VERSION` 时，同一次改动按 `docs/progress.md` 末尾的步骤更新它。
- 预测行为没变，但这份改动改变了「已完成」或「尚未写代码」时，只更新进度里的对应小节，不升版本。
- 发现或解决一个会影响预测、数据、训练或运行命令的问题时，按 `docs/issues.md` 开头的格式写一条。解决后把该条从「未解决」移到「已解决」。
- 纯注释、格式，以及不改变上述状态的文档润色，不改这两份文件。

## 命令

Python 3.12+。有 `.venv` 时用 `.venv` 里的解释器（Linux/macOS `.venv/bin/python`，Windows `.venv\Scripts\python`），否则用当前环境的 `python`。从仓库根目录：

```bash
python -m pytest tests   # 离线单测，不联网、不碰 football.db
python -m pytest tests/test_oddsportal.py::test_collect_survives_scrape_failure   # 单条测试
python -m football_prediction.live   # 实盘一轮：更新数据 → 评分 → 存档预测 → 报告 → 成绩单 → 替换检查
python -m football_prediction.explain 英超 Arsenal Chelsea   # 单场判断说明，只读库；可加 --odds/--ou/--ah 手动输入赔率
python -m football_prediction.data.oddsportal --hours 30   # 抓多家公司赔率写入 book_odds，约 15–25 分钟；--no-scrape 只打印对比表
python -m football_prediction.main   # 旧的回测演示（v1.3.0）；会下载赛季 CSV，很慢
```

- 输出含中文，Windows 下设 `PYTHONIOENCODING=utf-8`。不经 `-m pytest` 直接跑脚本时需要 `PYTHONPATH=.`。
- 不要跑不带路径的 `pytest`：它会收集 `大模型项目/` 里依赖 torch 的测试并在收集阶段失败。
- 改完一层后跑 `python -m pytest tests`。`tests/` 只用内存 SQLite 和合成比赛（`tests/conftest.py`）；新测试保持离线，爬虫测试通过替换 `runner` 参数模拟。lightgbm 缺失时相关测试会 skip。
- 没有 lint 或 build 步骤。依赖见 `requirements.txt`。
## 布局

分层包 `football_prediction/`，各层通过同一个 SQLite 库（默认 `football.db`）交换数据。

| 路径 | 职责 |
|---|---|
| `version.py` | 各层版本、`PRIMARY_MODEL` / `FALLBACK_MODEL`、`PROMOTE_MIN_N` |
| `data/loader.py` | football-data.co.uk 赛季 CSV → `matches / match_odds / match_stats`；`fixtures.csv` → `fixtures`，每次刷新追加 `odds_snapshots` |
| `data/understat.py` | understat xG → `match_xg`；已结束赛季缓存在 `_cache/understat/` |
| `data/oddsportal.py` | 调 OddsHarvester（独立 venv `.venv-scrape`，可用环境变量 `ODDSHARVESTER` 覆盖）抓未开赛比赛的多家赔率 → `book_odds`；`book_consensus()` 返回与 fixtures 同键名的多家中位数 |
| `features/builder.py` | 特征；只用截止日之前的比赛 |
| `model_market/implied.py` | 由 1X2 + 大小 2.5 + 亚盘去水概率反推 λ，再套 DC 比分矩阵；当前主模型 |
| `model_dc/` | Dixon-Coles、射正版 `sot_dc`、xG 版 `xg_dc`（无赔率时的兜底） |
| `model_elo/` `model_blend/` `model_lgbm/` | Elo；dc_xg + Elo 的 1X2 融合；LightGBM 残差修正 |
| `calibration/platt.py` | Platt；2425 验证无增益，不进实盘主流程 |
| `output/analysis.py` | 判断流程，纯函数、不读库，报告与 explain 共用：市场去水 → 市场隐含比分 → 自研分歧提示（8pp）→ 盘口变动（5pp 或亚盘线变化）→ 风险 → 倾向 / 双选 / 信心档 |
| `output/pipeline.py` | `ModelCache` 按联赛懒加载并拟合模型，`analyse_match` 把库里的数据接到 `analysis` |
| `output/derive.py` `output/report.py` | 比分矩阵 → 各盘口（含亚盘五种结算）；报告写到 `reports/预测_YYYY-MM-DD.csv` |
| `review/store.py` | `predictions` 表的存档、赛后评分、实盘成绩单（同场对比 `market_avg`）、`promotion_check` |
| `validation/backtest.py` | `run_backtest`（`refit_freq="monthly"`）、`run_market_backtest`、`paired_compare`（同场差值 + SE） |
| `live.py` | 实盘入口。`services/` 建立后只保留命令行，编排规则见 [`docs/modules.md`](docs/modules.md) |
| `explain.py` | 单场说明入口。同上 |
| `main.py` | 回测演示入口。同上 |

联赛列表 `LEAGUES` 分别在 `live.py`、`explain.py` 中定义。模型统一用 `fit(conn, league, cutoff_date)`。

`football.db` 每次实盘都会变，已纳入版本库；需要备份时由用户决定是否提交。不要为了"清理工作区"还原或覆盖它。`reports/`、`_cache/`、`_diag/`（诊断与研究脚本及输出）同样是运行产物，按惯例纳入版本库作备份。`research.db` 已 gitignore。

## 数据规则

- 入库只补不改：`matches` 用 `INSERT OR IGNORE`；`match_odds` 已有值永不覆盖，只补空列；`match_xg` 只 `INSERT OR IGNORE`；`book_odds` 以 `(match_id, fetched_at, bookmaker, market, line)` 为键，每次抓取是一个新批次。
- 不要把历史赛季加进 `football.db`：Elo 会遍历全部历史，加入老赛季会让实盘模型在版本号不变的情况下改变结果。扩样本研究用 `research.db`（5 联赛 1415–2526），由 `_diag/expand/build_research_db.py` 从 `_cache/fd_research` 重建；老 CSV 的 `BbAv*` 列在该脚本里映射为 `Avg*`。
- 数据下载失败时沿用本地库，不要把空结果写成"已更新"。xG 必须在该赛季 `matches` 写入之后再拉。
- 新联赛队名先走 `data/loader.py` 的 `TEAM_ALIASES`。understat 队名靠同日 ±1 天且同比分投票，不要手写第二套映射。OddsPortal 新队名对不上时在 `oddsportal.NAME_ALIASES` 里补别名。
- football-data 的 `fixtures.csv` 大约每周更新，不是临场更新；临场赔率靠 OddsPortal 爬虫。
- OddsPortal：本机出口 IP 在美国，只能看到 5 家美国公司。robots.txt 禁止抓赛季归档和 ajax 接口，因此只抓即将开赛的比赛，不能用来补历史。列表页开球时间不准，配对靠"日期 ±1 天 + 队名"；链接 slug 里两队按字母顺序排列，真实主队以记录里的 `home_team` 为准。
- 500.com 有 WAF，球探（titan007）的 robots.txt 禁止抓赔率页，都没有采用。不要绕过反爬机制。
## 预测规则

- 拟合一律 `match_date < cutoff`。实盘 cutoff 是当天（UTC），只预测尚未开球的场次。
- 每场、每个 `model_name` + `model_ver` 只保留开赛前**首次**预测（`has_prediction` 去重）。`save_prediction` 不覆盖旧行。改算法必须升版本，不能靠重跑改历史。报告按最新赔率现算，与存档互不影响。
- 市场基准名 `market_avg`，版本是 `live.MARKET_VER`（算法变才改，不跟数据层走）。
- 报告以 `version.PRIMARY_MODEL`（现为 `market_implied` / `model_market`）为准；没有赔率的场次回退到 `version.FALLBACK_MODEL`（`dc_xg` / `model_xg`）。其余模型并行存档。
- 替换主模型只走 `promotion_check`：同一批已评分实盘上，场数 ≥ `PROMOTE_MIN_N`（1000）且（差值 + 2×SE）< 0。不要用回测事后改 `PRIMARY_MODEL`。
- 回测禁止随机 KFold。`2526` 是留出赛季：shrink、射正权重、xG 权重都不在该季上重选。当前选参：DC `shrink=0.5`，射正版进球权重 `w=0.7`，xG 版 `w=0.3`，融合 Elo 权重 `0.23`。
- 评价用 Log Loss，辅以 Brier。同场差值为负表示前者更好；`|差| < 2×SE` 视为无显著差异。

## 改一层时

1. 更新该模块的 `LAYER_VERSION`（模型类还有 `MODEL_VER` 的，一起改），并在文件头 docstring 写这一版的说明。
2. 同步 `version.py` 的 `LAYER_VERSIONS`。行为变化才升版本；纯注释不必升。
3. 改 `live.py` 时，模块文档第二行要含 `v{live 版本}`，`tests/test_versions.py` 会检查。
4. 新增带 `LAYER_VERSION` 的模块时，把它登记进 `tests/test_versions.py` 的 `MODULES`。
5. 按「进度与问题」更新 `docs/progress.md`。这次改动修了会影响运行的问题时，同时更新 `docs/issues.md`。

## 两人协作：Mac 与 Windows

环境（各自建，`.venv` 和 `.venv-scrape` 都不进版本库）：

| | Windows | Mac |
|---|---|---|
| 主环境 | `python -m venv .venv` → `.venv\Scripts\python -m pip install -r requirements.txt` | `python3 -m venv .venv` → `.venv/bin/python -m pip install -r requirements.txt` |
| 爬虫环境（可选） | `python -m venv .venv-scrape` → `.venv-scrape\Scripts\python -m pip install oddsharvester==0.20.0` → `.venv-scrape\Scripts\playwright install chromium` | 同左，路径换成 `.venv-scrape/bin/` |

- Mac 上导入 lightgbm 报缺 `libomp` 时，`brew install libomp`；不装也能跑实盘和测试（相关测试 skip）。
- 没有爬虫环境时，`data.oddsportal` 打印提示后只显示已有数据，`live` 不受影响。
- 不需要改 `core.autocrlf` 或 `core.symlinks`：行尾由 `.gitattributes` 管，技能目录是普通文件。

谁写什么：

- `football.db`、`logs/`、`reports/` 只由跑定时任务的那台 Windows 机器提交。SQLite 是二进制，两边都提交时 git 无法合并，实盘存档也会分叉。
- 另一台机器可以本地跑 `live` 看结果，但不提交 `football.db`；提交代码时只 `git add` 具体文件。`git pull` 若在 `football.db` 上冲突，取远端版本：`git checkout --theirs football.db` 后再 `git add football.db`。
- fork 协作时，开新分支前先把 fork 的 main 同步到本仓库 main（GitHub 的 Sync fork，或 `git fetch upstream && git merge upstream/main`），否则 PR 会在 `CLAUDE.md`、`.claude/skills/` 上冲突。

## 运行环境

- Windows 任务计划程序有两个任务：`FootballPredictDaily_1807` 和 `FootballPredictDaily_2337`，每天执行 `run_daily.bat`（先跑 `live`，再跑 `oddsportal --hours 30`），日志写到 `logs/daily.log`。
- `run_daily.bat` 必须保持纯 ASCII + CRLF：cmd 按 GBK 解析，含 UTF-8 中文会出错。CRLF 由 `.gitattributes` 保证（`*.bat eol=crlf`），与各人的 `core.autocrlf` 无关。
- 定时任务只在 Windows 这台机器上跑。Mac 上手动跑 `python -m football_prediction.live`；`data/oddsportal.py` 会按系统找 `.venv-scrape/bin` 或 `.venv-scrape\Scripts` 下的 OddsHarvester。
- 行尾：仓库里一律存 LF（`.gitattributes` 的 `* text=auto`），检出按平台转换。
