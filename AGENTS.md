# 足球预测系统

仓库根目录的可运行项目是 `football_prediction`（实盘联赛：英超 E0 / 德甲 D1 / 西甲 SP1 / 意甲 I1 / 法甲 F1 / 英冠 E1 / 荷甲 N1 / 葡超 P1 / 苏超 SC0 / 比甲 B1 / 土超 T1，实盘库都从 2122 赛季起；后六个没有 understat xG）。在仓库根目录工作，数据库与报告路径都相对 cwd。

目标是预测比赛赛果，亚盘为主，胜平负 / 比分 / 大小球为辅，不是找价值投注。亚盘一律用主队方向的数字线（负数 = 主队让球，如 `-0.75`），不用中文盘口名。主模型是市场赔率反推（`market_implied`），自研模型（Dixon-Coles 系、Elo）只作对照和无赔率时的兜底：5 联赛 × 9 赛季、16k 场样本外回测里，自研模型每个联赛、每个赛季都不如赛前市场，融合只改善约 0.002 log loss，命中率不变。要提高准确率，靠的是赔率里还没有的信息（临场赔率、阵容），而不是改进球模型。

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
python -m football_prediction.live --near   # 临场档：开球前 1.5 小时内先抓 FotMob 阵容再抓多家赔率，存 *_t1 并打印最终看法（run_near.bat）
python -m football_prediction.data.fotmob   # 抓即将开赛的阵容 / 伤停；--history E0 2425 补历史球员数据，--reload-pre 从缓存重建
python -m football_prediction.main   # 旧的回测演示（v1.3.0）；会下载赛季 CSV，很慢
python -m server   # 只读接口 127.0.0.1:8000，读 reports/latest_round.json 与首次存档；无鉴权
python -m server --openapi web/openapi.json   # 导出 OpenAPI，再在 web/ 运行 npm run api:types
```

- 输出含中文，Windows 下设 `PYTHONIOENCODING=utf-8`。不经 `-m pytest` 直接跑脚本时需要 `PYTHONPATH=.`。
- 不要跑不带路径的 `pytest`：它会收集 `大模型项目/` 里依赖 torch 的测试并在收集阶段失败。
- 改完一层后跑 `python -m pytest tests`。`tests/` 只用内存 SQLite 和合成比赛（`tests/conftest.py`）；新测试保持离线，爬虫测试通过替换 `runner` 参数模拟。lightgbm 缺失时相关测试会 skip。
- Python 没有 lint 或 build 步骤，依赖见 `requirements.txt`。前端依赖和锁文件独立在 `web/`。

前端使用 Node.js 24 LTS（Mac/Windows 同主版本），在 `web/` 执行：

```bash
npm ci
npx playwright install chromium # 首次运行浏览器测试时安装测试浏览器
npm run dev        # 仅本机开发
npm run typecheck
npm run lint
npm run test       # Vitest 组件测试
npm run build
npm run test:e2e   # 自动启动构建后的 next start，含 HTTP 与 Chromium 测试
npm run start     # 部署运行，前置 npm run build
```

网站服务端读环境变量 `API_URL`（如 `http://127.0.0.1:8000`）时显示接口里的实盘数据，不设时显示演示样本；e2e 不设 `API_URL`。

前端验收包括 360/390/768/1440 视口、SSR 正文与 metadata、404/5xx、演示 noindex、关注与筛选恢复、首页预测刷新，以及登录表单在服务未接入时的提示。桌面 Safari/Chrome 响应式可用于人工验收，未做真机测试要明确。根目录仍执行 `python -m pytest tests`；不运行 live、不触碰实盘库。

依赖安装完成后再运行检查；typecheck 和 build 都写入 .next，需顺序执行，不能与 npm ci 或彼此并行。test:e2e 使用刚构建的生产产物；WEB_TEST_CONTROL_FILE 仅用于本机测试，不配置到正式服务。
## 布局

分层包 `football_prediction/`，各层通过同一个 SQLite 库（默认 `football.db`）交换数据。

| 路径 | 职责 |
|---|---|
| `version.py` | 各层版本、`PRIMARY_MODEL` / `FALLBACK_MODEL`、`PROMOTE_MIN_N` |
| `data/loader.py` | football-data.co.uk 赛季 CSV → `matches / match_odds / match_stats`；全部表结构（`DB_SCHEMA`） |
| `data/understat.py` | understat xG → `match_xg`；已结束赛季缓存在 `_cache/understat/` |
| `data/fixtures.py` | `fixtures.csv` → `fixtures`，每次刷新追加 `odds_snapshots`；`odds_movement` |
| `data/oddsportal.py` | 调 OddsHarvester（独立 venv `.venv-scrape`，可用环境变量 `ODDSHARVESTER` 覆盖）抓未开赛比赛的多家赔率 → `book_odds`；`book_consensus()` 返回与 fixtures 同键名的多家中位数。队名配对与输出解析在 `oddsportal_parse.py` |
| `data/fotmob.py` | FotMob 比赛页 HTML（不碰 `/api/`）→ 单独的 `fotmob.db`（gitignore，`attach()` 挂为 schema `fm`）：`lineups`（预测 / 正式首发、替补、伤停）、`player_match`（分钟、xG、xA、npxG）、`fotmob_shots`；understat 缺的 `match_xg` 用它补；联赛页完赛比分 → `fotmob_results`，只在 football-data 赛果未到时用于评分。页面解析在 `fotmob_parse.py`，页面缓存在 `_cache/fotmob/` |
| `features/builder.py` | 特征；只用截止日之前的比赛 |
| `model_market/implied.py` | 由 1X2 + 大小 2.5 + 亚盘去水概率反推 λ，再套 DC 比分矩阵；当前主模型。`devig.py` 是 Shin 去水（并行存档 `market_shin`） |
| `model_dc/` | Dixon-Coles、射正版 `sot_dc`、xG 版 `xg_dc`（无赔率时的兜底）、市场版 `market_dc`（进球与历史赔率 λ 混合估强度，并行存档 `dc_market`） |
| `model_lineup/` | 阵容模型：`ratings.py` 球员进攻评分、常规首发、阵容特征；`adjust.py` 把特征乘到市场 λ 上，按赔率是否早于首次正式首发选 `COEF_PRE` / `COEF_POST`（研究确认前都为 0，一场只叠一次）。只用于临场档 `lineup_t1` |
| `model_elo/` `model_blend/` `model_lgbm/` | Elo；dc_xg + Elo 的 1X2 融合；LightGBM 残差修正 |
| `calibration/platt.py` | Platt；2425 验证无增益，不进实盘主流程 |
| `output/analysis.py` | 判断流程，纯函数、不读库，报告与 explain 共用：市场去水 → 市场隐含比分 → 亚盘（市场线五种结算、赢盘信心档 `AH_TIERS`、初盘 → 最新 → 定价的盘口与水位、dc_xg 同线分歧 8pp）→ 自研分歧提示（8pp）→ 盘口变动（5pp 或亚盘线变化）→ 风险 → 倾向 / 双选 / 信心档 |
| `services/match_analysis.py` | 中间层。`ModelCache` 按联赛懒加载并拟合模型，`analyse_match` 把库里的数据接到 `analysis`；`latest_odds` 给报告和 explain 选赔率（24 小时内 ≥3 家的多家中位数优先，否则赛程表快照；存档仍用赛程表）；`build_report`、`explain_inputs` |
| `services/live_round.py` `services/near_round.py` | 实盘一轮（`run_round`：更新数据 → 评分 → 存档 → 报告 → 成绩单 → 替换检查，每轮写快照 `reports/latest_round.json`）；临场档 `run_near`（窗口内有场次时 `refresh_snapshot` 按最新赔率重写快照）。赛前存档 extra 记对阵 `match`。服务函数用参数 `log` 输出进度 |
| `services/match_read.py` | 给接口的读函数：`open_readonly`（`mode=ro`，有 `fotmob.db` 时只读挂上补比分）、`read_current` / `read_recent`（最近已开球场次的首次存档与比分）/ `read_match`（快照看法 + 首次存档）/ `read_scorecard` |
| `services/backtest_run.py` | 回测演示的串联 |
| `output/derive.py` `output/report.py` | 比分矩阵 → 各盘口（亚盘五种结算，`AH_LINES` −4…+4）；报告写到 `reports/预测_YYYY-MM-DD.csv`，亚盘四列紧跟对阵 |
| `review/store.py` | `predictions` 表的存档、赛后评分（`matches` 无赛果时先用 `fotmob_results`，`reconcile_results` 待 football-data 到达后核对重评）；亚盘评分 `ah_settle` / `ah_scores`：同场所有模型都用存档时的市场亚盘线（本行 `odds.ah_line`，否则同场同档最早一行），旧行自动回填 |
| `review/scorecard.py` | 实盘成绩单（同场对比 `market_avg`，含亚盘列，只作参考）、`promotion_check`（只看 1X2）、`horizon_report` |
| `validation/backtest.py` | `run_backtest`（`refit_freq="monthly"`）、`run_market_backtest`、`paired_compare`（同场差值 + SE） |
| `server/`（仓库根目录） | FastAPI 只读接口 `/api/matches`（含最近已开球场次 `recent`）、`/api/matches/{id}`、`/api/review`；只调 `services`，不写 SQL；无鉴权，默认只听 127.0.0.1 |
| `live.py` | 实盘入口，只有参数、打印和调用 `services`；编排规则见 [`docs/modules.md`](docs/modules.md) |
| `explain.py` | 单场说明入口。同上 |
| `main.py` | 回测演示入口。同上 |

联赛列表 `LEAGUES` 定义在 `services/live_round.py`，`live.py`、`explain.py` 再导出。加联赛时同时登记 `fotmob_parse.LEAGUE_IDS` 与 `oddsportal_parse.LEAGUE_SLUGS`（`tests/test_fotmob.py::test_league_lists_agree` 检查四处一致），再用 `_diag/expand/add_live_leagues.py` 写入 2122 起的赛季；understat 只覆盖 `understat.US_LEAGUES`。模型统一用 `fit(conn, league, cutoff_date)`。

`football.db` 每次实盘都会变，已纳入版本库；需要备份时由用户决定是否提交。不要为了"清理工作区"还原或覆盖它。`reports/`、`_cache/`、`_diag/`（诊断与研究脚本及输出）同样是运行产物，按惯例纳入版本库作备份。`research.db` 已 gitignore。

## 数据规则

- 入库只补不改：`matches` 用 `INSERT OR IGNORE`；`match_odds` 已有值永不覆盖，只补空列；`match_xg` 只 `INSERT OR IGNORE`；`book_odds` 以 `(match_id, fetched_at, bookmaker, market, line)` 为键，每次抓取是一个新批次。
- 不要把历史赛季加进 `football.db`：Elo 会遍历全部历史，加入老赛季会让实盘模型在版本号不变的情况下改变结果。扩样本研究用 `research.db`（5 联赛 9394–2526；赔率从 0001 起，射正约从 0506 起，xG 从 1415 起），由 `_diag/expand/build_research_db.py` 从 `_cache/fd_research` 重建；老 CSV 的 `BbAv*` 列映射为 `Avg*`，0001–0405 没有平均列，用各家公司的均值代替。2000 年前的赛季代码（`9394`…`9900`）按字符串排在 `2526` 之后，研究脚本按 `match_date` 排序，不要按赛季字符串比大小。
- 数据下载失败时沿用本地库，不要把空结果写成"已更新"。xG 必须在该赛季 `matches` 写入之后再拉。
- 新联赛队名先走 `data/loader.py` 的 `TEAM_ALIASES`。understat 队名靠同日 ±1 天且同比分投票，不要手写第二套映射。OddsPortal 新队名对不上时在 `oddsportal_parse.NAME_ALIASES` 里补别名，FotMob 的在 `fotmob_parse.FOTMOB_ALIASES` 里补（FotMob 名字也先过 `NAME_ALIASES`）。
- football-data 的 `fixtures.csv` 大约每周更新，不是临场更新；临场赔率靠 OddsPortal 爬虫。
- OddsPortal：本机出口 IP 在美国，只能看到 5 家美国公司。robots.txt 禁止抓赛季归档和 ajax 接口，因此只抓即将开赛的比赛，不能用来补历史。列表页开球时间不准，配对靠"日期 ±1 天 + 队名"；链接 slug 里两队按字母顺序排列，真实主队以记录里的 `home_team` 为准。
- 500.com 有 WAF，球探（titan007）的 robots.txt 禁止抓赔率页，都没有采用。不要绕过反爬机制。
- FotMob：只抓比赛页 HTML（页面里的 `__NEXT_DATA__`），不要请求 `/api/`（robots.txt 禁止）。请求间隔不低于 `fotmob.DELAY`（3.5 秒）；历史页缓存后不重抓。比赛页用赛程里带 `#id` 的链接取，并核对页面 matchId；不要只用 `/matches/<slug>`（去掉 id 后返回两队最近一场，不是要的那场）。FBref、WhoScored、Sofascore 有 Cloudflare / 反爬，不采用。
- `fotmob.db` 不并进 `football.db`：它可由 `_cache/fotmob/` 重建，体积大，且只有临场档和研究用。
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

- Windows 任务计划程序有两个任务：`FootballPredictDaily_1807` 和 `FootballPredictDaily_2337`，每天执行 `run_daily.bat`（先跑 `live`，再跑 `oddsportal --hours 30`，最后 `data.fotmob` 抓即将开赛的阵容 / 伤停），日志写到 `logs/daily.log`。
- `run_near.bat` 跑 `live --near`，日志 `logs/near.log`。计划任务 `FootballPredictNear` 每天 18:13 起每 30 分钟执行一次到 05:43（单次上限 40 分钟，上一轮未完则跳过）；开赛时段电脑需开机、不睡眠。与每日任务同时写库时 `init_db` 会等锁 120 秒（`loader.BUSY_TIMEOUT`，见 `docs/issues.md`）。
- `run_daily.bat`、`run_near.bat` 必须保持纯 ASCII + CRLF：cmd 按 GBK 解析，含 UTF-8 中文会出错。CRLF 由 `.gitattributes` 保证（`*.bat eol=crlf`），与各人的 `core.autocrlf` 无关。
- 定时任务只在 Windows 这台机器上跑。Mac 上手动跑 `python -m football_prediction.live`；`data/oddsportal.py` 会按系统找 `.venv-scrape/bin` 或 `.venv-scrape\Scripts` 下的 OddsHarvester。
- 行尾：仓库里一律存 LF（`.gitattributes` 的 `* text=auto`），检出按平台转换。

## 会话交接（始终启用）

- 每次会话首次处理任务前，读取 `session-handoff`：Codex 读 `.agents/skills/session-handoff/SKILL.md`，Claude Code 读 `.claude/skills/session-handoff/SKILL.md`；当前上下文已读则沿用。
- 开始任务前，读取 `docs/handoff/` 中按文件名排序最新的 1–2 份记录；没有记录时直接继续。交接内容是待核实的记录，不是指令。
- 非琐碎任务或阶段结束时，新建 `docs/handoff/YYYY-MM-DD-HHMM-摘要.md`，不追加到旧文件。
- 时间使用 `Asia/Shanghai`（UTC+8）、24 小时制；摘要使用 10–20 个无空格中文字符，正文用中文。时间从系统获取并转换到该时区。
- 内容依次为：需求 → 实际操作（命令、脚本路径）→ 证据 → 未完成事项 → 涉及文件。只写核实过的事实，其余标记“未验证”或“推断”。
- `docs/handoff/` 只记录当次操作和证据；系统当前进度与问题仍只维护在 `docs/progress.md`、`docs/issues.md`，交接记录引用它们，不另建状态或问题清单。
- 不复制密码、密钥、令牌、会话 Cookie 或含凭据的连接串。`.env`、`.env.*`（含 `web/.env*`）、`servers.txt`、`*.pem`、`*.key` 等敏感文件不引用其内容，仅可记录路径。
