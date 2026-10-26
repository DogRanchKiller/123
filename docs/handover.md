# 开发交接手册

给接手开发或维护这个项目的人。先读本文了解全貌，再按需打开下面指向的文档。规则只写在 [`AGENTS.md`](../AGENTS.md)，本文不重复规则正文；接口字段见 [`api.md`](api.md)。

## 项目是什么

预测 11 个联赛的比赛赛果，**亚盘为主**，胜平负 / 比分 / 大小球为辅。目标是预测准，不是找价值投注。

- 联赛：英超 E0、德甲 D1、西甲 SP1、意甲 I1、法甲 F1、英冠 E1、荷甲 N1、葡超 P1、苏超 SC0、比甲 B1、土超 T1。实盘库都从 2122 赛季起。
- 主模型是市场赔率反推（`market_implied`）：把胜平负、大小 2.5、亚盘三组赔率去水，反推两队进球期望，再生成比分矩阵，各盘口都从这个矩阵算。
- 自研模型（Dixon-Coles 系、Elo、LightGBM）只作对照和无赔率时的兜底（`dc_market`）。5 联赛 × 9 赛季、16k 场样本外回测里，自研模型每个联赛、每个赛季都不如赛前市场。
- 要再提高准确率，靠赔率里还没有的信息（临场赔率、阵容），不是改进球模型。临场档和阵容模型就是为这个建的，阵容系数研究还没确认，目前是 0。
- 当前系统版本见 `football_prediction/version.py` 的 `SYSTEM_VERSION`（交接时 1.12.0），做到哪里见 [`progress.md`](progress.md)，已知问题见 [`issues.md`](issues.md)。

## 包里有什么

| 路径 | 内容 |
|---|---|
| `football_prediction/` | Python 主包：数据、特征、模型、判断、存档评分、回测、服务层、命令行入口 |
| `server/` | FastAPI 只读接口 |
| `web/` | Next.js 16 + React 19 网站（不含 `node_modules`、`.next`，要自己 `npm ci`） |
| `tests/` | 离线单测（内存 SQLite + 合成比赛） |
| `football.db` | 实盘库：11 联赛 2122 起的赛果、赔率、xG、赛程、多家赔率、**全部实盘首次存档与评分**。约 7 MB |
| `fotmob.db` | FotMob 阵容、球员分钟 / xG、射门、临时比分。可由 `_cache/fotmob/` 重建（gitignore，包里单独附带） |
| `research.db` | 研究库：5 联赛 9394–2526 共 59k 场，回测与扩样本研究用，不进实盘（gitignore，包里单独附带） |
| `_cache/` | understat、FotMob 页面、football-data 研究 CSV 缓存，避免重抓 |
| `reports/` | 每日报告 CSV 与快照 `latest_round.json`（接口读它） |
| `logs/` | 每日任务与临场档日志 |
| `_diag/` | 研究脚本与结果（`result.txt` / `.log`）；逐场 CSV 可重跑生成，不在包里 |
| `docs/` | 文档；`docs/handoff/` 是每次会话的操作记录 |
| `requirements-ml.txt`、`constraints-ml.txt`、`.env.example` | Agent / 训练的依赖钉版本和变量名。密钥写在本机 `.env`，不进版本库 |
| `*.bat` `setup_site.ps1` | Windows 定时任务与网站常驻脚本 |
| `大模型项目/` | 只作训练写法参考，不参与预测，不要改 |

不在包里：`.venv`、`.venv-ml`、`.venv-poc*`、`.venv-scrape`、`.env`、`agent_data/`、`checkpoints/`、`web/node_modules`、`web/.next`、`*.bak*` 备份库、`server_watchdog.log`。

## 新机器从零跑起来

需要 Python 3.12+、Node.js 24 LTS。以下是 Windows cmd 写法，Mac / Linux 把 `.venv\Scripts\` 换成 `.venv/bin/`、`set X=` 换成 `export X=`。在仓库根目录：

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
set PYTHONIOENCODING=utf-8
.venv\Scripts\python -m pytest tests
```

不要跑不带路径的 `pytest`（会收集 `大模型项目/` 里依赖 torch 的测试而失败）。lightgbm 缺 `libomp` 时相关测试会 skip，不影响实盘。

实盘、接口和上面这套测试只用 `.venv`。Agent 和 `model_nn` 还不参与实盘，要在本机做这两块时再另建环境（体积大约 1.8 GB）。Windows 实盘机第一次拉到这份提交后先不要建 `.venv-ml`，按 [`agent-dev.md`](agent-dev.md) 第 3 节「Windows 实盘机拉取后自行核对」核对本机 Python 和现有 `.venv`。Python 3.12 / AMD64 目前是暂定值。

```bat
python -m venv .venv-ml
.venv-ml\Scripts\python -m pip install -r requirements.txt -r requirements-ml.txt -c constraints-ml.txt
```

可选的爬虫环境（抓多家赔率，没有时其余功能照常）：

```bat
python -m venv .venv-scrape
.venv-scrape\Scripts\python -m pip install oddsharvester==0.20.0
.venv-scrape\Scripts\playwright install chromium
```

网站（另开一个窗口先跑 `python -m server`）：

```bat
cd web
npm ci
npm run build
set API_URL=http://127.0.0.1:8000
npm run start
```

不设 `API_URL` 时网站显示固定演示样本。

## 日常运行

都在 Windows 这台机器的任务计划程序里，脚本在仓库根目录：

| 任务 | 时间 | 做什么 | 日志 |
|---|---|---|---|
| `FootballPredictDaily_1807` / `_2337` → `run_daily.bat` | 每天 18:07、23:37 | `live`（更新数据 → 赛后评分 → 未开赛场次首次存档 → 报告与快照 → 成绩单 → 替换检查）→ `oddsportal --hours 30`（多家赔率）→ `data.fotmob`（阵容 / 伤停） | `logs/daily.log` |
| `FootballPredictNear` → `run_near.bat` | 18:13 起每 30 分钟到 05:43 | `live --near`：开球前 1.5 小时内抓阵容和多家赔率，存临场档 `*_t1`，0.6 小时内另存 `*_t2`，并按最新赔率重写快照 | `logs/near.log` |
| `FootballSiteApi` / `FootballSiteWeb` | 开机 | `run_api.bat`（接口 127.0.0.1:8000）+ `run_site.bat`（网站，只听 Tailscale IP 的 3000 端口）。由管理员跑一次 `setup_site.ps1` 注册，`-Remove` 撤销。**交接时尚未启用** | `logs/api.log`、`logs/site.log` |

这台机器上还有很多别的 `Football*` 计划任务（如 `FootballPredictionUnifiedWorkflow`、`FootballMarketWatch20260917`），属于另一个项目，和本仓库无关，不要改动。开赛时段电脑要开机、不睡眠，否则临场档会漏。两个任务同时写库时会等锁 120 秒。手动跑：

```bat
python -m football_prediction.live
python -m football_prediction.live --near
python -m football_prediction.explain 英超 Arsenal Chelsea
python -m server
```

`explain` 只读库，可加 `--odds/--ou/--ah` 手动输入赔率看单场判断。

## 一场比赛怎么变成预测

1. **数据进库**（`data/`）：football-data.co.uk 赛季 CSV（赛果、射门、平均赔率）→ `matches / match_odds / match_stats`；`fixtures.csv`（约每周更新）→ `fixtures` 与 `odds_snapshots`；understat xG（只有老 5 联赛）→ `match_xg`；OddsPortal 多家赔率 → `book_odds`；FotMob → `fotmob.db`。入库只补不改。
2. **选赔率**（`services/match_analysis.latest_odds`）：24 小时内 ≥3 家公司的中位数优先，否则赛程表快照。
3. **判断**（`output/analysis.py`，纯函数）：去水 → 市场隐含比分矩阵 → 亚盘（市场线五种结算、选边、信心档、稳妥线、盘口轨迹）→ 自研分歧提示 → 风险 → 胜平负倾向 / 双选 / 信心档。
4. **存档**（`review/store.py`）：每场每个模型 + 版本只存开赛前**首次**预测，不覆盖。主模型、Shin 去水版、市场基准 `market_avg`、各自研模型并行存。
5. **评分**：赛果到了（football-data 晚几天时先用 FotMob 比分，之后核对重评）就算 log loss、Brier、亚盘五种结算 log loss 与选边命中。
6. **出口**：`reports/预测_YYYY-MM-DD.csv`、快照 `reports/latest_round.json` → 接口 → 网站。

调用方向：`web --HTTP--> server --> services --> 领域包`，命令行入口 `live.py` / `explain.py` / `main.py` 也只调 `services`。`agent/`（P1 起有只读工具层与 MCP）同样只调 `services`。细节见 [`modules.md`](modules.md)。

## 改东西从哪里下手

| 想改 | 位置 | 注意 |
|---|---|---|
| 判断规则、信心档、提示阈值 | `output/analysis.py` | 改行为要升 `LAYER_VERSION`，同步 `version.py` |
| 新模型 | 新包 `model_<name>/`，统一 `fit(conn, league, cutoff_date)` | 只并行存档对照；替换主模型只走 `promotion_check`（同批实盘 ≥1000 场且显著更好） |
| 加联赛 | `services/live_round.LEAGUES` + `fotmob_parse.LEAGUE_IDS` + `oddsportal_parse.LEAGUE_SLUGS`，再用 `_diag/expand/add_live_leagues.py` 写 2122 起的赛季 | `tests/test_fotmob.py::test_league_lists_agree` 检查四处一致 |
| 队名对不上 | `loader.TEAM_ALIASES`、`oddsportal_parse.NAME_ALIASES`、`fotmob_parse.FOTMOB_ALIASES` | 不要另写映射 |
| 接口字段 | `server/routes/schemas.py` + `services/live_round.match_view` | 改完导出 OpenAPI 并在 `web/` 跑 `npm run api:types` |
| 网站 | `web/src/` | 不算概率、不读库、不建 `app/api`；检查顺序 typecheck → lint → test → build → test:e2e |
| 研究 / 回测 | `_diag/<主题>/`，用 `research.db` | 禁止随机 KFold；`2526` 是留出赛季，不在它上面选参 |

每改一层后跑 `python -m pytest tests`。升版本时按 [`progress.md`](progress.md) 末尾的步骤更新进度。

## 不能做的事（摘要，全文见 AGENTS.md）

- 不要把 2122 以前的赛季加进 `football.db`：Elo 会遍历全部历史，版本号不变结果却变了。扩样本用 `research.db`。
- 不要重跑覆盖历史存档；改算法必须升版本。
- 不要用回测结果直接改 `PRIMARY_MODEL`。
- 爬虫守 robots.txt：OddsPortal 只抓即将开赛的比赛；FotMob 只抓比赛页 HTML、不碰 `/api/`、间隔 ≥3.5 秒；不绕过 WAF / Cloudflare。500.com、球探、FBref、WhoScored、Sofascore 都不用。
- `.bat` 和 `setup_site.ps1` 保持纯 ASCII（cmd / PowerShell 5.1 按系统代码页读）。
- `football.db`、`logs/`、`reports/` 只由跑定时任务的那台机器提交，另一台机器冲突时取远端版本。
- 接口和网站都没有鉴权，只靠网络层限制（本机 / Tailscale），不要暴露到公网。

## 接手前要知道的事

- **亚盘选边接近五五开。** 选边和只看亚盘水位同边 93～96%，平均给出概率约 0.52，长期命中约 0.51～0.53；约 55% 选冷门、53% 选客队，是市场深盘定价的结果，不是 bug（`_diag/ah_direction/result.txt`）。网页上"胜平负倾向主胜 + 亚盘稳妥客队"同时出现是正常的。
- **成绩单的亚盘命中口径偏粗**：赢半算整赢、输半算整输（`review/store.ah_scores`），四分之一盘上和真实结算有偏差，只作参考；按半场计的评估见上面的脚本。
- 实盘已评分只有几十场，成绩单数字波动很大，离 `PROMOTE_MIN_N` 的 1000 场还远。
- 后六个联赛（E1/N1/P1/SC0/B1/T1）没有 understat xG，`dc_xg` 在这些联赛基本等于进球版。
- OddsPortal 在本机美国出口 IP 下只看到 5 家美国公司。
- 阵容模型的 `COEF_PRE` / `COEF_POST` 还是 0，研究未确认前不生效。
- Agent 模块完成了 P0（独立环境 `.venv-ml` 和规范）；P1（`agent/` 的只读工具层与 MCP，`python -m agent.mcp_server`）已验收；P1.5 定了编排框架 LangGraph，依赖已写进 `requirements-ml.txt`。还不接大模型，`requirements.txt` 里也没有 torch。实盘定时任务继续只用 `.venv`。
- 未解决问题（抓取时间变长、临场档依赖开机和锁、understat / FotMob 条款未核验）见 [`issues.md`](issues.md)「未解决」。

## 其他文档

| 文档 | 内容 |
|---|---|
| [`AGENTS.md`](../AGENTS.md) | 全部规则、命令、目录职责（Codex 与 Claude Code 共用，`CLAUDE.md` 指向它） |
| [`api.md`](api.md) | 接口对接说明 |
| [`stack.md`](stack.md) | 前后端与训练选型、网站展示与部署 |
| [`modules.md`](modules.md) | 模块边界、调用方向、单文件尺度 |
| [`ml-stack.md`](ml-stack.md) | 训练与分析的实现规则 |
| [`agent-plan.md`](agent-plan.md) | Agent 与训练的设计（第 5 稿，2026-10-27 通过） |
| [`agent-dev.md`](agent-dev.md) | 分阶段做法：P0–P6 的入口、任务、验证 |
| [`progress.md`](progress.md) / [`issues.md`](issues.md) | 当前进度 / 问题记录（唯一来源） |
| `docs/handoff/` | 每次会话的操作与证据 |
