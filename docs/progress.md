# 项目进度

系统版本：2.1.0，与 `football_prediction/version.py` 的 `SYSTEM_VERSION` 一致。

更新日期：2026-10-28。

这份文件只描述当前状态。规则在 `AGENTS.md`、`docs/stack.md`、`docs/modules.md`、`docs/ml-stack.md`。问题记录在 [issues.md](issues.md)。

## 当前

命令行预测可以跑。网站 `/` 是深色全息首页，预测、关注、详情和成绩单共用同一套深色业务页。中间层 `services/` 已建立，实盘每轮写快照 `reports/latest_round.json`；只读接口 `python -m server`（FastAPI，无鉴权，默认只听本机）读快照和首次存档。网站配置 `API_URL` 时显示本机实盘数据，不配置时显示演示数据。账号服务尚未建立；问答页 `/chat` 用邀请码单独登录（P6，配置 `AGENT_SERVE_URL` 与 `AGENT_SERVICE_TOKEN` 才显示）。

- 联赛：英超 E0、德甲 D1、西甲 SP1、意甲 I1、法甲 F1、英冠 E1、荷甲 N1、葡超 P1、苏超 SC0、比甲 B1、土超 T1（实盘库都从 2122 起；后六个没有 understat xG）。研究库 `research.db` 只有前 5 联赛 9394–2526（赔率从 0001 起，xG 从 1415 起）。
- 主模型：`dc_dyn` / `model_dc_dyn` 1.0.0（动态攻防 DC，2.0.0 起；用户 2026-10-28 决定不等 `promotion_check` 直接换，是规则的例外）。有没有赔率都用它，不再有兜底。市场隐含 `market_implied`（1.4.0–1.13.0 的主模型）改为 `version.MARKET_MODEL`：照常存档（含临场档），报告里作市场对照与分歧提示，在 `promotion_check` 里作挑战者。`dc_market` 只在读 2.0.0 之前、没有 dc_dyn 存档的场次时用。已知代价：留出 n=4590 dc_dyn 对同场赛前市场胜平负 +0.0051±0.0015、亚盘 +0.0034±0.0015（市场更准）。
- 分析重心：亚盘为主，胜平负 / 比分 / 大小球为辅（output 2.0.0）。每场都给结论和把握程度，另给亚盘稳妥线（dc_dyn 在各线上赢盘 ≥ 65% 的最近一条线）；dc_dyn 胜平负档为高的场次标「★ 重点」（有没有赔率都算）。报告和 explain 先列市场线亚盘（数字盘口，如 主-0.75），赢盘概率按 dc_dyn；dc_dyn 在市场线上的选择方命中只有约 0.51，亚盘只给一档「低」。成绩单另列亚盘评分；亚盘评分只作参考，替换主模型仍只看 1X2 的 `promotion_check`。
- 实盘：`python -m football_prediction.live`；单场说明：`python -m football_prediction.explain 英超 Arsenal Chelsea`
- 多家赔率：`python -m football_prediction.data.oddsportal --hours 30`
- 临场档：`python -m football_prediction.live --near`（`run_near.bat`）；阵容 / 伤停：`python -m football_prediction.data.fotmob`
- FotMob 库：仓库根目录 `fotmob.db`（gitignore，可由 `_cache/fotmob/` 重建）
- 回测：`python -m football_prediction.main`
- 报告：`reports/预测_YYYY-MM-DD.csv`
- 数据库：仓库根目录 `football.db`
- 定时：Windows 任务计划每天 18:07、23:37 跑 `run_daily.bat`（live + oddsportal + fotmob 阵容），日志 `logs/daily.log`；`FootballPredictNear` 每天 18:13–05:43 每 30 分钟跑 `run_near.bat`，存 `*_t1`（开球前 1.5 小时内）与 `*_t2`（0.6 小时内），开球前 23–25 小时的场次另存 `*_t24`（市场三档 + 自研三档同一时刻），日志 `logs/near.log`（需开机）。
- 成绩单：每行对同一档的市场基准（赛前档对 `market_avg`，临场档对 `market_avg_t24` / `_t1` / `_t2`）；另列对收盘平均赔率的参照（`live` 的 [5b]、快照与接口的 `closing`），不进替换检查。`live` 最后打印 [8] 实盘体检（只读）。

## 已完成

### 实盘体检、同档成绩单、收盘参照与 T24 档（2026-10-28，2.1.0）

- 体检（`services/monitor.py`，只读）：`live` 一轮最后打印 [8]：开球超过 3 天仍无赛果的存档、48 小时内缺赛程表赔率 / 缺主模型开球前存档的场数、各联赛 football-data 最近赛果日期、`book_odds` 最近抓取离现在多久（> 36 小时提示）、近 30 天已评分场次上主模型对 `market_avg` / `market_implied` 的同场差（显著更差时提示）。体检出错只打印，不影响本轮。
- 同档成绩单（review 1.9.0）：`live_report` 每行加 `base`，临场档对同档的 `market_avg_t24` / `_t1` / `_t2` 比，赛前档仍对 `market_avg`；此前临场档也对赛前 `market_avg`，混了时点。快照（`SNAPSHOT_SCHEMA` 2）、接口 `ScorecardRow.base`、网站成绩单「对比基准」列同步。
- 收盘参照：`closing_report` 用 football-data 收盘平均 1X2（`avgc_*`，按比例去水）在同一批已评分场次上配对，`live` 的 [5b] 打印，快照与接口 `/api/review` 加 `closing`，网站「对收盘赔率（参照）」一节。收盘在存档时看不到，只作参照，不进 `promotion_check`。截至 2026-10-28 的 59 场已评分：收盘 LL 0.9254，赛前 `market_avg` 对收盘 +0.0132±0.0082。
- T24 档（`services/near_round.py`）：`live --near` 遇到开球前 23–25 小时、还没有 `market_avg_t24` 的场次时，只对这些场次抓多家赔率（`oddsportal.collect` 加 `from_hours` / `match_ids`，默认行为不变，data 层不升版本），≥3 家、90 分钟内时存 `market_avg_t24` / `market_implied_t24` / `market_shin_t24`；有市场行时同一时刻再存 `dc_dyn_t24`（extra 记所用多家赔率）/ `dc_dyn_shots_t24` / `dc_market_t24`。用意是让自研与市场在同一信息时点比（赛前档的赛程表赔率约每周更新）。dc_dyn 只用历史，同日存的 `dc_dyn_t24` 通常等于赛前 `dc_dyn`。T24 档不进替换检查；不抓阵容、不重写快照。代价：有待抓场次时每次临场档多一组 OddsPortal 抓取，计入 40 分钟单次上限；每场只抓一次。
- Agent 跟上 2.0.0 / 2.1.0（只改 `agent/`，预测不变）：成绩单块加 `is_primary`（按 `version.PRIMARY_MODEL`）；`scorecard(closing=true)` 返回对收盘参照块（kind `closing`），`diff_vs_close` 登记进字段表；系统提示按 `version` 现拼主模型名，并说明 `_t24` / `_t1` / `_t2` 与 `base`；评测集 `agent.jsonl` 改掉以 market_implied 为主模型的两题，新增主模型对市场隐含、对收盘、T24 档三题（29 题）。知识库要等这些文档进 main 后 `--update` 才检索得到；`retrieval.jsonl` 没加新题。真实评测没有重跑。
- 验证：Python 离线测试 415 passed / 12 skipped，`.venv-ml` 494 passed；web typecheck / lint / Vitest 67 项 / build / e2e 29 项通过；OpenAPI 与 `schema.d.ts` 重新导出。

### 主模型换成 dc_dyn（2026-10-28，2.0.0）

- 决定：用户 2026-10-28 明确选择不等实盘同场 `promotion_check`，直接把 `PRIMARY_MODEL` 换成 `dc_dyn`。依据只有回测：留出 2526+2627 n=4590 对 dc_market 胜平负 −0.0069±0.0016、亚盘 −0.0068±0.0017；对同场赛前市场仍差（胜平负 +0.0051±0.0015、亚盘 +0.0034±0.0015，`_diag/dev_model/result_v02.txt`）。`AGENTS.md` 记为唯一例外。
- `version.py`：`PRIMARY_MODEL = ("dc_dyn", "model_dc_dyn")`；新增 `MARKET_MODEL = ("market_implied", "model_market")`；`FALLBACK_MODEL`（dc_market）只给读旧存档用。
- 判断流程（output 2.0.0，`analysis.py` / `report.py` / `derive.py` 同步版本）：胜平负、比分、大小球、亚盘赢盘概率都来自 dc_dyn 比分矩阵，有没有赔率一样；市场去水与市场隐含只作对照，胜平负任一结果或同线主队赢盘差 > 8pp 时提示，其余自研模型只列出。报告加列「市场 主/平/客」，explain 同步。
- 重标定（`_diag/primary_dyn/tiers.py` → `tiers.txt`，11 联赛 2324–2526 n=11395 标定、2627 n=829 留出）：`PRIMARY_TIERS` 按 dc_dyn 首选概率，高 ≥0.60：0.726 / 0.903（留出 0.732 / 0.923），中 ≥0.45：0.516 / 0.775（0.512 / 0.759），低：0.411 / 0.710（0.399 / 0.708）。亚盘市场线选择方命中 0.512（留出 0.495），按概率分档不单调（高档标定 0.531、留出 0.645；中档 0.506 / 0.465），所以 `PRIMARY_AH_TIERS` 只给一档「低」0.512。稳妥线按 dc_dyn 各线：标定命中 0.667、留出 0.635。重点 = dc_dyn 档高（约 25% 场次）。旧的 `MARKET_TIERS` / `MODEL_TIERS` / `AH_TIERS` 保留，给旧存档分档。
- 实盘（live 2.0.0）：报告、快照、推荐都按 dc_dyn；dc_dyn 存档的 extra 另记存档时的赛程表赔率 `odds`（亚盘评分用的线、页面显示存档时市场线）。market_implied 及 `_t1` / `_t2` 照常存档。快照每场加 `market_probabilities`（市场去水，无赔率时空）和亚盘 `implied_home_cover`（市场隐含矩阵同线主队赢盘）；`model_name` 有没有赔率都是 dc_dyn。
- 读存档（`services/match_read.py`）：首次存档按 dc_dyn → market_implied → dc_market 的顺序取（`ARCHIVE_MODELS`），分档按存档的模型选档表；临场档仍是 `market_implied_t1`。修了一处：无赔率场次的 dc_dyn 存档里 `odds` 是全空列，原来会挡住公平线回退、亚盘为空，现在先去掉空值。
- 接口与网站：OpenAPI 与 `schema.d.ts` 重新导出（新增两个字段）。网站主模型名「动态攻防模型」（`dc_dyn_shots` 为「动态攻防（射门）」）；详情页胜平负下加「市场对照（去水）」，亚盘加「市场同线主队赢盘（对照）」；说明文字、预测页的主模型说明、演示样本都按 dc_dyn 改；旧存档是市场隐含时仍标「市场（存档时赔率）」。`zhText` 换中文模型名时去掉紧挨中文的空格。
- 验证：Python 离线测试 404 passed / 12 skipped，`.venv-ml` 483 passed；web typecheck / lint / Vitest 64 项 / build / e2e 29 项通过（Node 24.19.0；e2e 原先会读到本机 `web/.env.local` 的 `API_URL`，见 issues 已解决一条）。
- 之后：2026-10-28 18:07 那一轮是第一次按 dc_dyn 出报告和存档，跑完核对 dc_dyn 存档行、快照和网站；实盘评分够 `PROMOTE_MIN_N` 场后看 `promotion_check` 里 market_implied 对 dc_dyn，市场显著更好时由用户决定是否换回。

### 动态攻防 DC 进实盘并行存档（2026-10-27，1.13.0）

- 把开发线 dev v0.2（`_diag/dev_model/dynamic.py`）与无赔率变体（`no_market.py`）搬进 `football_prediction/model_dc/dynamic_dc.py`（`model_dc_dyn` 1.0.0）：按比赛日先预测、再用当天赛果更新各队攻防（扩展卡尔曼近似），过程噪声按两场间隔天数加；换季时 c=1（不收缩）、方差加 `V_SEASON`，新来球队取离开球队的均值；ρ 用赛前滤波 λ 与实际进球按时间衰减拟合。两版：`dc_dyn`（观测 = 历史赔率反推 λ，w=0、q=0.016；留出 2526+2627 n=4590 对 dc_market 胜平负 −0.0069±0.0016）和 `dc_dyn_shots`（进球 0.7 + 射门 0.3，不用赔率，q=3e-5；对 dc_market +0.0015±0.0013，不显著）。
- 实盘：`LeagueModels` 多拟合这两个，`predict_upcoming` 每场多存两行（含比分、亚盘、大小的 extra），自动进成绩单与 `promotion_check`；报告、主模型、兜底、`inputs()` 分歧提示都不变。新赛季还没有完赛场次时按 fixtures 里新赛季的球队先换季；回测（cutoff 之后已有完赛）不读 fixtures。
- 核对：在 football.db 内存副本上，生产版 λ 与 dev `run_league` 逐场差 0.0（E0 / T1 / SC0 / D1 多个 cutoff，两版都核）；`_diag/dev_model/smoke_archive.py` 在内存副本上跑 `predict_upcoming`，16 场未开赛各多存 dc_dyn / dc_dyn_shots 一行，其余模型不变，真实库 md5 不变。
- 之后：2.0.0 起 dc_dyn 直接成为主模型，见上一节。
- 验证：Python 离线测试 402 项通过（新增 `tests/test_dynamic_dc.py` 5 项）；OpenAPI 重新导出（只变版本号），`schema.d.ts` 无变化。

### 兜底换 dc_market、第二临场档、只用亚盘的对照研究（2026-10-26，1.12.0）

- 兜底：`_diag/fallback/`（`compute.py` 11 联赛 2324–2627 月度重拟合回测，`analyze.py` → `result.txt`，`tiers.py` → `tiers.txt`）。n=12224：dc_market 对 blend（此前无赔率时的胜平负）−0.00597±0.00096，老五联赛 −0.00216±0.00110（不显著）、新六联赛 −0.00919±0.00150，2324 / 2425 / 2526 / 2627 四季都显著；对 dc_xg −0.00923±0.00110；dc_market 再融 Elo 只多 −0.00038±0.00033（不显著），所以不融。`FALLBACK_MODEL` 改为 `dc_market`，无赔率时比分、大小球和胜平负都用它，亚盘同线对照与 8pp 分歧提示也换成 dc_market。`MODEL_TIERS` 按 dc_market 在 2324–2526 标定（高 ≥0.60：0.74 / 0.90，中 ≥0.45：0.52 / 0.78，低：0.40 / 0.71），2627 留出 829 场一致（0.753 / 0.540 / 0.378）。网站文案、演示样本同步。
- 第二临场档 `*_t2`：`predict_near` 存 `_t1` 之后，存档时离开球 ≤ `T2_HOURS`（0.6）小时、且多家赔率在 `T2_FRESH_MIN`（30）分钟内抓到（即本轮抓的）时再存 `market_avg_t2` / `market_implied_t2` / `market_shin_t2`。临场任务每 30 分钟一轮、抓取加拟合约 5–20 分钟，`_t2` 大约在开球前 0.3–0.6 小时存档。不存阵容模型（系数仍为 0）。亚盘参照线按（场次, 档）分组；`_t2` 不进 `promotion_check`；`horizon_report` 里 `_t2` 对赛前档和 `_t1` 各配对一次。接口和网站仍只读 `_t1`，`_t2` 只存档和进成绩单；网站模型名 `_t2` 显示「（临场，近开球）」。
- 只用亚盘的对照（`_diag/ah_only/`，`result.txt`）：反推 λ 时只用亚盘 + 大小球（ahou），或亚盘与 1X2 加权（ah1x2h），对现行等权（1X2 + 大小 + 亚盘）。标定期（开球日 < 2025-07-01，n=44429）各项差值都在 ±0.0001 内；留出期 n=4157：ahou 1X2 −0.00167±0.00132、亚盘 LL +0.00032±0.00025、亚盘命中 +0.000，ah1x2h 1X2 −0.00098±0.00086，都不显著，亚盘 LL 反而略差。主模型不改。
- 实盘临场档对首次存档（截至 2026-10-26）：已评分 40 场，`market_implied_t1` 对 `market_implied` +0.0185±0.0087（临场更差，约 2.1 SE），去水 1X2 +0.0137±0.0086；40 场都只有 FotMob 比分、还没有 football-data 收盘赔率，样本太小，不下结论。
- 不做的：Pinnacle 亚盘（用户 2026-10-26 决定不用）；football-data `HxG` / `AxG`（2627 起 11 个联赛 FotMob 已补齐 xG，HxG 没有历史赛季，兜底也不再依赖 xG）。
- 验证：Python 离线测试 218 项；web typecheck / lint / Vitest 39 项 / build / e2e 20 项通过；OpenAPI 与 `schema.d.ts` 重新导出（只变版本号和一句说明）。

### 只读接口与网站实盘数据（2026-10-26，预测版本不变）

- `server/`：FastAPI 只读接口 `GET /api/matches`（快照里尚未开球的场次 + `recent`：最近 `recent_days` 天（默认 3，上限 14）已开球、有首次存档的场次和比分）、`/api/matches/{id}`（快照看法 + 首次存档与赛后评分）、`/api/review`（快照成绩单）。只调 `services`；库以只读方式打开，无快照 503，未知比赛 404。没有鉴权，默认 127.0.0.1。依赖 fastapi 0.149.0、pydantic 2.14.1、uvicorn 0.54.0，测试用 httpx 0.28.1。
- `services/match_read.py`：读函数从 `live_round.py` 移出；`read_recent` 给列表附带最近已开球场次；`open_readonly` 在 `fotmob.db` 存在时只读挂上，football-data 赛果没到时用 `fotmob_results` 的比分（与评分同一顺序，`score_source` 标来源）。之前详情页只读 `football.db`，FotMob 先评分的场次比分为空。赛程表 `fixtures` 每次刷新整表替换，所以赛前存档的 extra 里另记对阵 `match`（联赛、主客队、日期；只是元数据，概率不变），matches / fixtures 都查不到时从存档取；记对阵之前的旧存档若已被换掉仍查不到，列表里跳过。快照每场加 `model_name` / `model_version` / `recommended` / `recommendation_note`（1.11.0 起 `recommended` 改为「有市场赔率且胜平负信心档为高」，见版本记录）。
- 网站：`web/openapi.json` → `src/api/schema.d.ts`（openapi-typescript）；`API_URL` 有值时各页经服务端读取接口并转成展示契约，标「本机实盘」与本轮生成时间，否则仍是演示样本（e2e 走演示模式）。关注页和「进行中 / 已完赛」筛选用 `recent`；关注里超出窗口的场次提示场数。`API_URL` 无效时报出地址错误；接口不可用时首页仍标「本机实盘」。快照替换在 Windows 上被读取占用时重试 5 次。TanStack Query 暂缓，见 `docs/stack.md`。
- 常驻脚本：`run_api.bat`（接口只听 127.0.0.1:8000）、`run_site.bat`（build 后 `next start` 只听本机 Tailscale IPv4，`SITE_BIND` 可覆盖），崩溃后 30 秒重启；`setup_site.ps1`（管理员跑一次）注册开机任务和只放行 100.64.0.0/10 的防火墙规则。已在本机验证：接口脚本起服务、杀进程后自动重启；网站脚本在没装 Tailscale 时等待并写日志，`SITE_BIND=127.0.0.1` 时 build + start 约 12 秒后页面显示本机实盘。`setup_site.ps1` 只做了语法检查，没有管理员权限，未注册。
- 临场档写快照：`live --near` 在 1.5 小时窗口内有场次时，存档之后用 `refresh_snapshot` 按最新赔率重算全部未开赛场次并重写快照（窗口内多为多家中位数，成绩单按现有评分重算；不存档、不写报告 CSV）。窗口内没场次时不动快照。真实库副本上 6 场约 10 秒。之前快照只在每日两次 `live` 时更新，网站看不到开球前的多家赔率。
- 两份存档：`read_match` 和 `read_recent` 另给主模型临场档 `near_archived`（`market_implied_t1`，开球前 1.5 小时内的多家中位数；`horizon` / `n_books` / `hours_to_ko`），两份存档都不计开球后才存的行。网站开球后卡片优先显示临场档，没有时用首次存档，并标明是哪一份；详情页两份都列出，临场档的「盘口变动」写出首次存档 → 临场的亚盘线变化（按让球方说：主队让球加深 / 变浅、受让变多 / 变少、让球方换边）。官方评分仍只看首次存档。真实库上最近 3 天 53 场已开球场次里有 40 场有临场档。
- 中文显示与队徽：网站把本库队名换成中文名（`web/src/features/match/teams.ts`，11 个联赛 2627 赛季 204 队），模型名换成中文（`web/src/lib/models.ts`，原名放在 title；后端提示里的模型名和 pp 一并换），页面上的英文标签都换成中文。队徽由 `_diag/web_crests.py` 从 FotMob 当前赛季赛程页取球队 id（只抓 HTML，间隔 `fotmob.DELAY`），一次性下载 150px 图到 `web/public/crests/`（204 张，约 2.2 MB），`crests.json` 记队名 → id；没有队徽的队显示中文名前两个字。只改显示，接口与预测都不变。新升班马要重跑脚本并在 `teams.ts` 补中文名。

### 中间层 services（2026-10-26，预测版本不变）

- `football_prediction/services/`：`live_round.py`（实盘一轮、快照；读函数后来移到 `match_read.py`）、`near_round.py`（临场档）、`match_analysis.py`（原 `output/pipeline.py`，加报告与 explain 的串联）、`backtest_run.py`（原 `main.py` 的串联）。`live.py`、`explain.py`、`main.py` 只剩参数、打印和调用；`output/pipeline.py` 已删除，`output/report.py` 不再拟合模型。
- 实盘一轮只拟合一次：同一份单场判断同时写报告 CSV 和快照 `reports/latest_round.json`（schema 1，原子替换；每场看法亚盘在前，含成绩单行）。没有场次时也写空快照。
- 读函数（给接口用，不按请求拟合）：`read_current`（快照里尚未开球的场次）、`read_match`（本轮看法 + 主模型首次存档，没有时用 dc_xg + 赛果）、`read_scorecard`。快照不存在时返回 None。
- 验证：`tests/test_services.py` 7 项（实盘一轮写报告与快照、已开球剔除、首次存档不被覆盖、兜底存档、成绩单 NaN、领域包不反向引用 services）；Python 离线测试 195 项通过。真实库只读冒烟：explain 土超一场输出正常；6 场未开赛写临时快照约 12 KB、14 秒，全部是市场线；`football.db` 前后 md5 不变。（之后 2026-10-26 12:48 手动跑过一轮真实 `live`，已生成 `reports/latest_round.json`。）

### 网站演示骨架（web 0.1.0）

- Next.js 16.4.3 + React 19 + TypeScript strict，Node.js 24 LTS；npm 锁文件与前端检查命令已加入，依赖审计 0 vulnerabilities。
- 预测列表、高信心推荐、比赛详情、首次预测存档、手动关注和成绩单页面；全部使用固定演示数据，明确标识。
- 展示契约已按报告字段改为亚盘为主（2026-10-26）：卡片、详情、首页先显示亚盘线 / 选择 / 亚盘信心，再显示胜平负；成绩单先列亚盘场次、亚盘 Log Loss、亚盘命中，并显示与 market_avg 的同场差值 ± SE。联赛筛选扩到 11 个（与 `live.LEAGUES` 同序），演示数据加了一场土超。
- 全站深色语义主题；独立 `/` 入口壳层与 3D 全息球场，业务页使用静态背景；关注 localStorage、筛选/滚动 sessionStorage，挂载后恢复。
- 首页预测卡片来自当前演示预测，按推荐优先选场；可见时每 60 秒刷新，失败保留旧值并提示延迟，场景与概率刷新隔离。
- 首页 3D 使用 Three.js / React Three Fiber、程序化球场和粒子；WebGL/减少动态效果可降级静态海报。邮箱和手机登录注册仅有校验表单，不接账号服务、不持久化凭据。
- 比赛详情按请求渲染；稳定 ID、北京时间展示、来源/获取/预测三类时间；无赔率来源直接显示契约字段。
- 演示站整站 noindex、robots 禁止抓取，不发布 sitemap，不建 /api；真实比分、滚球能力只展示未接入状态。
- 验收通过（2026-10-26）：TypeScript、ESLint、19 项组件测试（含亚盘文字与 Python 写法一致）、Next.js 生产构建、20 项生产 Chromium 测试；覆盖首页选场/刷新失败恢复/超时后重试/Canvas 稳定、登录键盘与校验、SSR/metadata/404/5xx、关注/筛选/滚动恢复及 360/390/768/1023/1024/1440 页面溢出与平板折叠菜单。Python 离线测试 189 项通过；预测版本不变。
- 已在桌面 Google Chrome 与 Safari 打开检查首页，Playwright Chromium 覆盖六种视口；手机为响应式模拟，未做真机测试。球场帧率未做设备级测量，60/30fps 仍是优化目标。尚未正式部署。

| 层 | 版本 | 状态 |
|---|---|---|
| data | 1.9.0 | 赛果、赔率（含亚盘 / Pinnacle / 赛程大小球）、射正、赛程、赔率快照、understat xG、OddsPortal 多家赔率 `book_odds`；意甲 / 法甲与英冠 / 荷甲 / 葡超 / 苏超 / 比甲 / 土超 2122–2627 已入实盘库；入库前剔除隐含概率之和 < 1 的赔率组（`clean_odds`） |
| data_fotmob | 1.2.1 | FotMob HTML 页：阵容（预测 / 正式）、伤停、球员分钟与 xG / xA、射门；understat 缺时补 `match_xg`；联赛页完赛比分 `fotmob_results`（只用于先评分）。11 个联赛都已登记，历史赛季队名已核对（1.2.1）。实盘 `fotmob.db` 历史有 E0 / D1 / SP1 2324 起，其余只有 2627；其余联赛 2122–2526 与三联赛 2122–2223 正在补抓到单独的 `fotmob_hist.db`（研究用，不进 `match_xg`，2026-10-27 起） |
| features | 1.0.0 | 截止日之前的特征 |
| model_dc | 1.3.0 | Dixon-Coles，`shrink=0.5` |
| model_sot | 1.0.0 | 射正版，进球权重 `w=0.7` |
| model_xg | 1.0.0 | xG 版，`w=0.3`，并行存档（1.12.0 前是无赔率时的兜底） |
| model_dc_market | 1.0.0 | 进球与历史赔率 λ 混合估强度（w=0.3），并行存档 `dc_market`；1.12.0–1.13.0 是无赔率时的兜底，2.0.0 起只用于读旧存档；11 联赛 2324–2627 对 blend −0.0060±0.0010，仍比市场差 |
| model_dc_dyn | 1.0.0 | 动态攻防 DC（按比赛日扩展卡尔曼更新）；`dc_dyn`（历史赔率信号）2.0.0 起是主模型，`dc_dyn_shots`（射门信号，不用赔率）并行存档；留出 2526+2627 对 dc_market 胜平负 −0.0069±0.0016 / +0.0015±0.0013，dc_dyn 对赛前市场 +0.0051±0.0015 |
| model_market | 1.0.0 | 由 1X2 + 大小 2.5 + 亚盘反推 λ；1.4.0–1.13.0 的主模型，2.0.0 起是市场对照 `MARKET_MODEL`，照常存档 |
| model_market_shin | 1.0.0 | Shin 去水的市场隐含，并行存档 `market_shin`；选参期 1X2 −0.00025±0.00007，2526 留出 −0.00028±0.00028 |
| model_lineup | 1.1.0 | 球员评分、常规首发、阵容特征、λ 调整；合并规则按赔率与首发先后选 `COEF_PRE` / `COEF_POST`，两套都为 0（3 联赛 2526 留出 1214 场无增益，见 issues） |
| model_elo | 1.1.0 | 净胜球加权更新 + 有序 logit，并行存档 |
| model_blend | 1.0.0 | dc_xg 0.77 + Elo 0.23 的 1X2 融合，并行存档 |
| model_lgbm | 1.1.0 | 在 Dixon-Coles 上做残差修正，滚动样本外 |
| calibration | 1.0.0 | Platt；2425 上没有增益，不进实盘 |
| output | 2.0.0 | 主模型 dc_dyn：胜平负 / 比分 / 亚盘赢盘都按 dc_dyn，信心档 `PRIMARY_TIERS` / `PRIMARY_AH_TIERS`，市场作对照与 8pp 分歧提示，报告加「市场 主/平/客」；（1.7.0）无赔率兜底与亚盘同线对照用 dc_market，`MODEL_TIERS` 按 dc_market 重标定；亚盘稳妥线（`analysis.safe_line`，`SAFE_TARGET=0.65`）与重点标记（`highlight` = 有市场赔率且胜平负档高），报告加「亚盘稳妥」「重点」列；亚盘为主：报告列「亚盘 / 亚盘选择 / 亚盘信心 / 亚盘变动」紧跟对阵，explain 第 [2] 段为亚盘，`AH_LINES` 覆盖 −4…+4；判断流程（`analysis.py`）、报告、explain 单场说明、亚盘五种结算；信心档按 Shin 概率在 5 联赛重标定，报告与 explain 列本场命中估计；报告与 explain 优先用多家中位数赔率（`services.latest_odds`），列赔率来源 |
| validation | 1.1.0 | 时间外回测、市场基准、同场配对 |
| review | 1.8.0 | 首次预测落库、赛后评分（含亚盘：按存档时的市场线算五种结算 log loss 与赢盘命中，`ah_line` / `ah_log_loss` / `ah_hit`；成绩单代码在 `scorecard.py`）（含大小 2.5 / 精确比分；football-data 未到时先用 FotMob 比分，到达后 `reconcile_results` 核对）、`promotion_check`（跳过 `_t1` / `_t2`）、`horizon_report` 临场对赛前（`_t2` 另对 `_t1`）；开球后才存的行不计 |
| live | 2.0.0 | 11 联赛；报告 / 快照 / 推荐按主模型 dc_dyn，快照加 `market_probabilities` 与 `implied_home_cover`，dc_dyn 存档另记存档时赔率；并行存档 dc_dyn / dc_dyn_shots；快照与接口每场带稳妥线 `safe_line` / `safe_cover` 和重点标记；成绩单加亚盘场数 / LL / 赢盘命中；更新数据（含 FotMob 完赛比分）、评分、预测、报告、成绩单；存档 market_implied / blend / market_shin / dc_market；`--near` 临场档 `*_t1` 与 lineup_t1 / lineup_base_t1、开球前 0.6 小时内的 `*_t2`，先抓阵容再抓赔率，打印临场最终看法 |

`2526` 留出，不在该季上重选 shrink 和权重。替换主模型只看实盘 `promotion_check`，场数至少 1000（2.0.0 换 dc_dyn 是用户决定的唯一例外）。

扩样本结论（`research.db`，5 联赛 × 1718–2526 样本外 16k 场）：自研模型每个联赛、每个赛季都不如赛前市场。提高准确率要靠赔率里还没有的信息。

## 已约定，尚未写代码

- 临场档信心档：`MARKET_TIERS` 已按 Shin 赛前概率重标（output 1.3.0）；临场档（T1 多家中位数）有实盘样本后再核对档位命中率；`_t2` 有足够已评分场次后，看它对赛前档和 `_t1` 是否更好。T24 档（2.1.0）有已评分场次后，看成绩单里 `dc_dyn_t24` 对 `market_avg_t24` 的同时点差距，与赛前档对比。
- 多家中位数的准确度：报告已改用 OddsPortal 多家中位数（只有 5 家美国公司），它与 football-data 平均赔率哪个更准，等 `horizon_report` 和赛前存档有足够已评分场次后再比；赛前存档仍用赛程表赔率。
- 网站数据刷新：接口只反映最近一次写快照的运行（每天两次定时 `live`、窗口内有场次的临场档 `--near`、手动）；首页每 60 秒重读。需要更快刷新或客户端轮询时再引入 TanStack Query。
- 账号与短信：顶栏已有登录/注册表单（邮箱密码、确认密码、手机验证码）和校验。提交、验证码和找回密码只提示服务未接入。账号服务、短信和登录会话尚未实现。
- 数据更新：先评估免费 API 的覆盖、授权与额度，再实现赛前赔率持续更新；目标 1–5 分钟，以数据源实际能力为准。
- 实时比分与比赛状态：未接入。
- 滚球预测（inplay）：未实现，需独立模型与数据链路，不能复用赛前结果冒充。
- 正式部署与搜索收录：尚未上线；真实数据上线后才开放指定页面并建立 sitemap。
- 网站上线给群友：`run_api.bat`、`run_site.bat`、`setup_site.ps1` 已写好（Tailscale、无口令，见 `docs/stack.md`），还要用户装好并登录 Tailscale、把本机共享给群友，再用管理员 PowerShell 跑一次 `setup_site.ps1`。开机任务和防火墙规则尚未注册；S4U 任务能否正常找到 node / python 未验证。2026-10-26 核对：本机未装 Tailscale，会话也没有管理员权限，只能由用户操作。
- 自研模型单独开发线（2026-10-27 起，不进实盘）：在 `_diag/dev_model/` 里以 dc_market 为底开发，`compute.py` 在 football.db 内存副本上出逐场样本外 λ，`evaluate.py` 在胜平负、亚盘、大小 2.5、比分上打分（`result.txt`）。基线 11 联赛 2324–2627 n=12224：dc_market 对赛前市场亚盘 LL +0.0114±0.0012，亚盘命中 0.499 对 0.518。dev v0.1（dc_market × 阵容调整，E0 / D1 / SP1，2526 留出 1038 场）对 dc_market 各盘口都不显著。dev v0.2（`dynamic.py`，`result_v02.txt`）：按比赛日更新的动态攻防（扩展卡尔曼近似，换季收缩，新来球队取离开球队均值），选参 2324–2425 选出 w=0（只用历史赔率反推 λ、不用进球）、q=0.016、c=1.0；留出 2526+2627 n=4590 对 dc_market 胜平负 LL −0.0069±0.0016、亚盘 LL −0.0068±0.0017，都显著，亚盘命中 0.506 对 0.502 不显著；对赛前市场仍差（胜平负 +0.0051±0.0015）。dc_market 是月度重拟合，部分增益可能来自更新频率。负二项比分分布在 r=5…50 都不如泊松，不采用。v0.2 与同一时点赛前市场按比分矩阵线性混合（`combine.py`，`result_combine.txt`）：选参期最优权重为 0（不混），留出期 a=0.05…0.5 对市场都不显著（亚盘 LL 最好 −0.00009±0.00014），有赛前赔率时 v0.2 不添信息。完全不用赔率的变体（`no_market.py`，`result_nomarket.txt`）：同一滤波，观测换成 进球 + k·射正 / 射门 / xG；选参期射门最好（w=0.7、q=3e-5），留出 n=4590 对纯进球胜平负 −0.0025±0.0010、亚盘 −0.0045±0.0010，显著；对 dc_market 胜平负 +0.0015±0.0013、亚盘 −0.0002±0.0014 不显著，大小、比分显著差；对 v0.2 胜平负 +0.0084±0.0017、对赛前市场 +0.0134±0.0019，都显著差。即无赔率时射门 / 射正能追平 dc_market，但历史赔率里的信息比赛内数据多。v0.2 与射门变体已进 `model_dc/dynamic_dc.py` 并行存档（1.13.0），v0.2 在 2.0.0 成为主模型（见「已完成」）。下一步 dev v0.3：以 v0.2 的 λ 为底做受约束修正。确认有效后才进 `model_dc` 并升版本，再走并行存档。
- Agent 与训练模块（`agent/`、`football_prediction/model_nn/`）：方案 [agent-plan.md](agent-plan.md) 第 5 稿于 2026-10-27 审核通过，按 [agent-dev.md](agent-dev.md) 分 P0–P6 阶段开发，每阶段验收后再进入下一阶段。`agent/` 现有 P1 的工具层与 MCP、P2 的知识库、P3 的 Agent 图与命令行、P6 的网站对话服务（P5 暂缓）；`model_nn` 有 P4 的研究代码，未过 G1。`requirements.txt` 里还没有 `torch`，要等 `model_nn` 过了 G1 才加。方案第 12 节的其余决定，到各阶段入口时再定。
  - P0（环境与规范，2026-10-27 完成并验收）：新增 `requirements-ml.txt`（直接依赖 10 个，都钉 `==`，不含编排框架）、`constraints-ml.txt`（与 `.venv` 重叠的包取实际版本，另钉 tokenizers / safetensors 等）、`.env.example`（只有变量名）；`.gitignore` 加 `.venv-ml/`、`.venv-poc*/`、`.env`、`agent_data/`、`checkpoints/`。Mac 上 `.venv-ml`（Python 3.14.6）装好：`pip check` 无冲突，torch 2.14.1 的 MPS 可用；`.venv` 的 `pip freeze` 在安装 ML 包前后一致；`pytest tests` 起初在 `.venv` 210 passed / 1 skipped（缺 httpx，接口测试跳过，见 issues 已解决一条）；经用户同意给 `.venv` 补装 httpx 0.28.1 / httpcore 1.0.9 后，`.venv` 和 `.venv-ml` 都是 218 passed（验收时复跑仍是这个数字）。Windows：Python 3.12 / AMD64 已于 2026-10-27 在实盘机上核对（3.12.10，系统 Python，那台机器没有 `.venv`），用 `uv pip compile` 按目标平台解析，128 个包都有可装的 wheel。2026-10-27 在实盘机建好 `.venv-ml`（129 个包，`pip check` 无冲突，torch 2.14.1+cpu，PyPI 默认 wheel 不带 CUDA），`pytest tests` 474 passed；系统 Python 395 passed / 12 skipped。实盘机的系统 Python 与 `constraints-ml.txt` 第一组（按 Mac `.venv` 定）有三处不同：pandas 3.0.6 对 3.1.0、certifi 2026.10.19 对 2026.10.23、starlette 1.9.0 对 1.10.0，`.venv-ml` 装的是约束里的版本，两个环境在这台机器上不完全一致；没有改约束文件，也没有动系统 Python。规则已并入 `docs/ml-stack.md`、`docs/stack.md`、`docs/modules.md`、`AGENTS.md`，交接手册 [`handover.md`](handover.md) 写了 `.venv-ml` 和拉取后的核对。
  - P1（工具层与 MCP，2026-10-27 完成并验收，提交 `8b93a82`）：`services` 新增 `team_read.py`（队名解析、某队最近几场 / 下一场、阵容、评分行）和 `explain_detail`（`match_analysis.py` 只重构，预测行为不变、不升版本）；`agent/config.py`、`agent/tools/`（7 个比赛工具 + `kb_search` 假实现，返回都是块）、`agent/mcp_server.py`（stdio，`python -m agent.mcp_server`）。测试 `test_agent_tools.py`（含只读 md5）、`test_agent_boundary.py`、`test_agent_mcp.py`（`.venv` 里跳过）、`test_team_read.py`：`.venv` 235 passed / 1 skipped，`.venv-ml` 237 passed。决定 6（中文队名表）未定，按 `agent-dev.md` 第 3 节只用 `TEAM_ALIASES`，中文名查不到。MCP 注册命令由用户自己执行。
  - P1.5（框架概念验证，2026-10-27 完成，用户选定 LangGraph）：用户直接选 LangGraph，没有做和 OpenAI Agents SDK 的对比（偏离 `agent-dev.md` 第 6 节）。决定 2 定为 OpenAI 兼容中转站 + `DeepSeek-v4.1-flash-1017`。概念验证的代码（`agent/poc/`、`agent/eval/poc.jsonl`、`tests/test_agent_poc.py`、`requirements-poc.txt`）在分支 `agent/p15-poc`，不合入 main。离线测试覆盖了打回重答、四个次数上限、HTTP 重试和 SqliteSaver 中断恢复。经用户同意真实跑了 20 条：17 条 passed、2 条 passed_retry、1 条 degraded，按单价估算约 0.10 美元。Claude 和本地 Ollama 两条路未实测。收尾时 LangGraph 这组 5 个直接依赖移进 `requirements-ml.txt`，关键间接依赖钉进 `constraints-ml.txt`；`.venv-poc` 已删，`.venv-ml` 已重建，共 152 个包，与旧环境比只多了 LangGraph 这组，旧包版本都没变。`pip check` 无冲突；`.venv` 的 freeze 没变；`pytest tests` 在 `.venv` 是 235 passed / 1 skipped，在 `.venv-ml` 是 237 passed；Windows 3.12 的 wheel 解析成功（153 个）。要做 P2 还需要先定决定 8（下载 bge-m3）。
  - P2（向量知识库，2026-10-27 完成并提交 `c2858f8`，检索评测集的抽查还没做）：决定 8 定为本地 bge-m3（`checkpoints/bge-m3`，约 2.1 GB，下载方式见 `docs/stack.md`）。用户选定 Milvus Lite 替代方案里的 Chroma（`pymilvus==3.0.2`、`milvus-lite==3.2.2`、`sentence-transformers==6.2.0`；BM25 用 Milvus 自带的 BM25 函数，中文按字二元组切词），文档里的 Chroma 已全部改成 Milvus Lite。新增 `agent/kb/`（`whitelist.toml` / `whitelist.py` 白名单、`sources.py` 按 git 第一父提交取各版文档、`match_chunks.py` 只经 `services` 取比赛块、`embed.py`、`index.py` 时间点过滤与 dense + BM25 的 RRF 融合、`build.py` / `__main__.py` 的 `--rebuild` / `--update` / `--stats` / `--eval`）、`agent/eval/retrieval.py` 与 `retrieval.jsonl`（100 条，88 条有标注，17 条泄漏用例），`kb_search` 换成真实检索；`services/team_read.py` 加 `read_archived_ids`、`read_scores`（只读，预测行为不变、不升版本）。
    - 白名单：规则 6 份（`AGENTS.md`、`docs/stack.md`、`docs/modules.md`、`docs/ml-stack.md`、`docs/api.md`、`docs/handover.md`），状态 2 份（`docs/progress.md`、`docs/issues.md`），研究 7 份（`_diag/fallback/result.txt`、`_diag/fallback/tiers.txt`、`_diag/ah_only/result.txt`、`_diag/explore/ah_clean_recheck.log`、`score_shape.log`、`ah_confidence_line.log`、`lineup_fotmob_eval.log`）。`score_shape.log` 的锚点较弱，`lineup_fotmob_eval.log` 是命令行重定向出来的，待用户确认。`algo_sweep`、`new_league_tiers`、`reliability`、`ah_baseline` 四个候选没收。
    - 基线（`python -m agent.kb --eval`，k=20）：dense recall@5 0.909 / recall@1 0.784 / MRR 0.849；bm25 0.909 / 0.625 / 0.743；hybrid 0.955 / 0.739 / 0.832；hybrid+rerank 未跑（没有下载重排模型）。hybrid 漏掉 r06、r24、r44、r82，标注核对无误。泄漏 0 条（17 条泄漏用例）。
    - 开发中发现并修掉一处泄漏：存档块原来用 `read_match` 的返回，其中信心档、历史命中率、亚盘档位、稳妥线是按当前规则现算的，早期存档会带出后来版本才有的稳妥线。现在存档块只留存档时写下的字段，快照看法块不变；索引布局 `LAYOUT` 升到 2，布局不符时 `--update` 拒绝、要求 `--rebuild`。另修了新进程打开时集合处于 released 状态、查询失败的问题；评分块正文的赛果映射原来按 `home` / `away` 取，与 `actual_outcome` 的 `home_win` / `away_win` 对不上，主胜、客胜会写成「赛果 -」，已改正并加了正文断言。
    - 索引：395 块（文档 290、快照看法 6、首次存档 57、临场存档 42；活跃 279），4.2 MB，`--rebuild` 约 50 秒，无变化的 `--update` 约 7 秒。Mac 上没有 `fotmob.db`，没有比分和评分块。知识库只手动更新，不进 `run_daily.bat`。
    - 环境：`.venv-ml` 按新的 requirements 重建，127 个包（原 156 个，去掉 chromadb、rank-bm25、onnxruntime 等 31 个；未钉版本的 jsonpatch / jsonpointer 小版本漂移），`pip check` 无冲突；Windows 3.12 的 wheel 解析成功（129 个），Windows 上 Milvus Lite 未实测。`pytest tests`：`.venv` 240 passed / 2 skipped，`.venv-ml` 247 passed；`football.db` 前后 md5 不变。
    - Windows 实盘机（2026-10-27）：Milvus Lite 可用。bge-m3 从 HF 取 `5617a9f` 版的 sentence-transformers 文件和 `pytorch_model.bin`，本地转成 `model.safetensors`。`--rebuild` 925 块（文档 392，比分 118，评分 253，阵容 59，首次存档 57，临场存档 46），8.6 MB，CPU 上约 8 分钟。`--eval` 起初核对不通过：7 条题（r17、r23、r24、r31、r39、r57、r79）的 as_of 是 10-27 05:00，按 fork 的线性历史定。main 上 PR #4 的内容在合并提交 13:47 才进第一父历史，所以这些题的 as_of 改到 15:00（合并之后、16:24 撤回之前）。改后 dense recall@5 0.864 / recall@1 0.773 / MRR 0.826；bm25 0.886 / 0.568 / 0.699；hybrid 0.932 / 0.716 / 0.810；泄漏 0。hybrid 漏掉的除原来 4 条外多了 r56、L01，可能是语料变了（多了比分 / 评分块，撤回再恢复又多出几版文档），没有细查。
    - 已处理（2026-10-27）：P1 的 `get_match` 原来同样会显示按现行规则现算的存档档位和稳妥线。现在 `agent/tools/blocks.py` 的 `stored_only` 由存档块与知识库共用，知识库正文不变，`LAYOUT` 不升。
  - P3（Agent 图、结构化事实与命令行，2026-10-27 完成，两轮真实评测已跑，用户验收后从分支 `agent/p3-graph` 合入 main）：用户定个人日额度 2 美元（北京日），`agent/prices.toml` 先填 `DeepSeek-v4.1-flash-1017`（格式可加别的模型）。新增 `agent/facts/`（`numbers.py` 第 1 条、`units.py` 单位对照表、`verify.py` 第 1–8 条、`render.py` 渲染与降级）、`llm.py`、`budget.py`、`prices.toml`、`graph.py`（LangGraph，SqliteSaver 存 `agent_data/state.db`）、`prompts.py`、`__main__.py`（`python -m agent "问题" [--thread ID] [--check] [--usage]`）、`agent/eval/agent.py` 与 `agent.jsonl`（26 题）；`config.py` 加 `Limits`（各上限可由 `.env` 改）和用量库 / 状态库 / 价格表路径。
    - 与方案、开发文档不同的做法（用户 2026-10-27 同意）：单位表多一个 `brier`；每轮工具返回总量上限 12000 token，超出的那次返回不交给模型；第 8 条在没有事实时也查，只认工具结果里出现过的队名；`budget.py` 是 `agent/` 里唯一可以写 SQL 的文件（只碰 `agent_data/usage.db`）；5xx 按 `usage_unknown` 记满预留额；高峰倍率只按周一至周五的时段，不认节假日和调休；小数按工具结果的写法严格比对；`max_tokens` 默认 6000（含思考 token），回复因长度上限被截断时单独提示；知识库打开失败重试一次；放行表增补 15 个词（北京、参照、参考、另一、下一场、上一场、下一轮、上一轮、最后一轮、最后一场、最近一场、下一步、下一阶段、两者、两队）。校验在 `agent/facts/` 包里，不是方案写的单文件 `facts.py`。
    - 真实评测（`python -m agent.eval.agent --run`，个人额度内）：第一轮首次通过 0.292、通过 0.654、降级 0.346、放行表打回 0.486，0.3057 美元。按结果修了上面最后三项并 `--update` 知识库（索引早于 P2 提交，说 P2 还没做），第二轮首次通过 0.423、通过（含重答）0.808、降级 0.192、措辞与 `kind` 不符 0（启发式）、放行表打回 0.316（38 次提交），0.2389 美元、114 个请求，全部按实际用量结算。中转站接受 `max_completion_tokens` 并返回完整用量。`--check`：一轮最坏约 0.95 美元。
    - 测试：`.venv` 370 passed / 5 skipped，`.venv-ml` 425 passed；`football.db` md5 不变。Claude 和本地模型两条路没有实测。
    - 已处理（2026-10-27）：措辞检查原来只查「过去的 kind 配现在时措辞」。现在 `wording_mismatch` 按占位前 12 个字内最近的时点词判断，「现在」类、首次存档、临场、最后一轮四种看法写反都会被查出；评分和比分只查是否写成「现在」。渲染时，同一句里连着的同来源数只在最后一个后面标一次来源；时间值等于块时间时，来源注里不再重复这个时间。
    - 未处理：校验只管数字对不对，管不住答得全不全（psg_kickoff 只查赛程就答「查不到」）；第二轮 5 题降级里有模型自起占位名、`path` 写成 `blocks[0].x` 提示后仍不改。
  - P4（`model_nn`，2026-10-27 完成：G1 四个检验都不通过，不进实盘）：决定 7 定为登记 T1–T4（m = 4，z = 2.54）；B 的市场 λ 直接引用 `model_market.implied`（`docs/modules.md` 第二处例外）；在 main 上做。
    - 冻结副本 `checkpoints/g1/football_20261027.db`（backup 接口，只读，md5 `741fe073a526afce46fb55e50420904a`，最晚一场 2026-10-21）；`football.db` 的 md5 前后不变。
    - 代码：`football_prediction/model_nn/`（`dataset.py` 逐场时点特征：本地 Elo、收缩到联赛均值的 EWM 球队统计、休息天数、B 的去水概率与市场隐含 λ，缓存 `checkpoints/nn_features/`；`net.py` softplus λ + 可学的 rho，DC 比分矩阵 NLL；`train.py` 训练窗口最后 120 天早停后全窗口按最佳轮数重训；`model.py` `NNModel.fit(conn, league, cutoff_date)`，同组联赛合并训练），模块顶层不 import torch；`model_nn` 0.1.0 登记进 `LAYER_VERSIONS` 与 `tests/test_versions.py`，`SYSTEM_VERSION` 不变。测试 `tests/test_model_nn.py`（时点、λ 为正、矩阵和为 1、B 起点等于市场、同种子同结果、无顶层 torch）。
    - 选参（`_diag/model_nn/select.py`，2425，五联赛 1752 场，按月）：基准 dc_market 1X2 LL 0.98157（逐比赛日重拟合 0.97919），market_implied 0.96397。每个变体 48 个配置，种子 0；前几名再跑种子 1、2。选定：B/no_xg h32 d0.3 对 market_implied 三个种子 −0.00324 / −0.00284 / −0.00308（SE 约 0.001）；A/full h128-64 d0.1 lr3e-4 对 dc_market（按月）−0.0067 到 −0.0083（SE 约 0.003），对逐日 dc_market −0.00434±0.00292；A/no_xg h64-32 d0.1 对按月 −0.0037 到 −0.0041，对逐日 −0.00173±0.00294。B 输入全置 0 只得 −0.0007，只留市场列 −0.001。A 对 market_implied 仍差约 +0.011。网格 96 个配置，有选择偏差。全部在 `select.log`，每次评估在 `eval_log.md` 一行。
    - 实测：每个配置 10 次月度拟合约 6–11 秒（CPU，M 系列 Mac），峰值内存约 500 MB；MPS 慢约 2.5 倍（27.6 s 对 10.9 s），结果不逐位相同，定用 CPU。
    - 与方案不同、用户批准：留出时 `dc_market` 每个比赛日重拟合，不按月（理由写在 `prereg.md`）。
    - 预注册：代码与选参提交 `04ec864`，`prereg.md` 单独提交 `94d7205`（2026-10-27）。
    - G1 留出（`holdout.py`，2526，只跑一次，`holdout.log`；z = 2.54，判据差值 + z×SE < 0）：

      | 检验 | n | Δ1X2 LL | SE | 差值 + z×SE | 结果 |
      |---|---|---|---|---|---|
      | T1 五联赛 B 对 market_implied | 1747 | +0.00060 | 0.00125 | +0.00378 | 不通过 |
      | T2 五联赛 A 对 dc_market（逐日） | 1752 | +0.00266 | 0.00268 | +0.00948 | 不通过 |
      | T3 六联赛 B 对 market_implied | 2009 | +0.00808 | 0.00760 | +0.02738 | 不通过 |
      | T4 六联赛 A 对 dc_market（逐日） | 2009 | +0.00433 | 0.00307 | +0.01212 | 不通过 |

      四个差值都是正的（候选更差），Brier、比分、亚盘的参考差值也都是正的。2425 上 B 约 −0.003、A 约 −0.004 的领先在 2526 没有出现，与「自研模型不如赛前市场」的已有结论一致。按联赛、按月的结果只作描述，见 `holdout.log`：T3 的差值主要来自 N1（+0.050）和 2026-04（+0.061），个别场次的损失很大，原因没有查（再查要在 2526 上重算候选，属于第二次评估）。
    - 已知缺陷（不改变结论）：T1 有 5 场候选的 1X2 log loss 是 NaN，被 `paired_compare` 的配对剔除（n 1747，对照 1752）；运行时 `implied.dc_matrix` 报了一次除零告警。推断是候选的 λ 与 rho 让 DC 修正项为负或矩阵和为 0，训练损失里有截断，评估用的 `dc_matrix` 没有。剔除的是候选最差的那类场次，只会让 T1 看起来更好，结论不变。
    - G1 用过的留出集：1 个（`football.db` 冻结副本的 2526），预算已用完。之后要再检验 `model_nn`，只能用它没评估过的数据（如 2627 在新预注册日期之后完赛的部分），另写 `prereg`、先提交再跑。`model_nn` 保持研究状态：`LAYER_VERSION` 0.1.0，不升 `SYSTEM_VERSION`，`requirements.txt` 不加 torch。
  - P5（LoRA）：用户 2026-10-27 决定先放一放，先做 P6；还没有代码。
  - P6（网站对话，2026-10-27 代码与离线验收完成，未在 Windows 实盘机部署）：决定 3 定为每人每日 2、全站每日 10、全站每月 100 美元（北京时间），全站并发 3、每人 1；决定 5 定为做法 A（邀请码 + 会话 Cookie），直接在 main 上开发。
    - Python：`agent/access.py`（邀请码与会话，`agent_data/access.db` 只存 SHA-256；会话 14 天、可吊销；CSRF 是绑定会话的 HMAC，24 小时过期；`python -m agent.access add / revoke / list`）；`agent/serve.py`（FastAPI，只听 127.0.0.1:8100，`X-Service-Token` 校验后才看会话，请求体里的用户 id 不读；`/login`、`/session`、`/logout`、`/chat`，对话 NDJSON 流式返回，15 秒无进度发 ping，一轮在单独线程里跑完再释放并发占用；对话键 `site:用户:thread_id`）；`budget.py` 加网站一档（每人当日、全站当日、全站当月三道上限）、`quota()`、并发占用表（过期清理）；`graph.ask` 加 `key` 和逐步回调；`config.py` 加 `access_path` 与四个额度 / 并发上限。依赖没变（fastapi / uvicorn 已在 `requirements.txt`）。
    - 网站：唯一的 Route Handler `web/src/app/api/chat/route.ts`（只收 POST；先查 Origin、Host、JSON、CSRF 头、会话 Cookie，不过不转发；只转发 `question` / `thread_id`）；登录 / 退出是 Server Action（`features/chat/actions.ts`），Cookie `fp_chat` 为 `HttpOnly`、`SameSite=Strict`、`Path=/`、带过期时间，http 下不加 `Secure`；问答页 `/chat`（未接入 / 不可用 / 邀请码 / 对话四种状态，回答按纯文本显示并标「数字已核对」或降级原因，右栏额度），导航加「问答」。新增 `run_agent.bat`；`run_site.bat` 默认设 `AGENT_SERVE_URL` 和 `SITE_URL=http://<Tailscale IPv4>:3000`。
    - 与方案不同的做法：方案写「Next.js 转发已认证的用户 id」；实际是 Next.js 只转发 Cookie 里的会话 id 和 CSRF 头，由 `agent.serve` 自己查会话、核对 CSRF，用户 id 不经过 Next.js。登录用 Server Action，不另建路由，所以 `app/api` 下仍只有对话一个路由。
    - 验收（`docs/agent-plan.md` 第 10.4 节「共同」+ A 组）：`tests/test_agent_serve.py`（18 项：服务令牌、请求体用户 id 被忽略、只听回环、余额不足调用前拒绝、每人 / 全站 429、崩溃后释放占用、重启后当日已用不变、12 次超时全记 `usage_unknown`、429 后重试两笔第一笔为 0、一直要工具时 6 次调用、第 2 次提交不过即降级、CSRF / 格式拒绝不产生预留、会话吊销与过期、对话按用户隔离、ping）、`test_agent_budget.py`（三道上限与次日 / 次月恢复、多线程 / 多进程原子预留）、`test_agent_access.py`（9 项，库里只有哈希）；Vitest 新增 21 项（转发检查、NDJSON 解析、对话面板）；Playwright 新增 9 项（用假 `agent.serve` `web/tests/fake-agent.mjs`：邀请码错不发 Cookie、Cookie 属性看响应头、别的 Origin / 缺 Origin / Host 不对 / 非 JSON / 表单 / 缺 CSRF / GET 405 / 无 Cookie 401 都不转发、别的会话的 CSRF 被拒、退出后旧会话失效、360/390/768/1440 无横向溢出）。另用真实 `agent.serve`（假模型、合成库）接 Next.js 生产构建跑了一轮：回答通过核对、额度更新、伪造 CSRF 403、用量库只有 site / alice 的行（临时脚本，已删）。
    - 检查：`.venv-ml` 474 passed，`.venv` 395 passed / 12 skipped；web typecheck / lint / Vitest 60 项 / build / e2e 29 项通过（Node 24.22.1；本机 PATH 默认的 Node 26 下 Vitest 的 `localStorage` 不可用，要用 Node 24）；`football.db` md5 不变。
    - Windows 实盘机（2026-10-27）：web 在 Node 24.19.0 下 typecheck / lint / Vitest 60 / build / e2e 29 通过；用假模型和临时库在本机起 `agent.serve`，netstat 显示只有 `127.0.0.1:8100` 在监听，不带令牌的请求返回 401（临时脚本，已删，没读 `.env`）。
    - 没验证的：「在 Tailscale 地址上扫不到 `agent.serve` 端口」还没测，因为实盘机未装 Tailscale；真实模型下的网站对话没跑（会花钱）；手机真机未测，只做了 Chromium 视口；`run_agent.bat` 没登记开机任务，`setup_site.ps1` 未改；`.env` 和 `web/.env.local` 的 `AGENT_SERVICE_TOKEN` 要用户自己生成填写。
- 用户定的顺序（2026-10-25）：扩联赛（1.9.0 已做六个一级联赛）→ 网页 + 接口（局域网 / 群友内网访问）→ 神经网络穿插进行 → 新信息源持续做。
- 杯赛档（欧冠、国内杯赛）：football-data 没有杯赛数据，需另找赛果与赔率来源；有加时 / 点球，评分要先定按 90 分钟还是最终结果；跨联赛对阵不能用按联赛拟合的 Elo / DC，只能用市场赔率。

## 版本记录

### 2.1.0（当前）

报告、主模型和赛前存档不变。成绩单每行对同一档的市场基准（临场档对 `market_avg_t1` / `_t2` / `_t24`），新增对收盘平均赔率的参照（只作参照）；`live` 末尾打印只读体检。`live --near` 加 T24 档 `*_t24`：开球前 23–25 小时用多家赔率存三个市场模型，并在同一时刻存 dc_dyn / dc_dyn_shots / dc_market，不进替换检查（review 1.9.0、live 2.1.0）。快照 schema 2 加 `closing` 与成绩单 `base`。依据见「已完成」第一节。

### 2.0.0

主模型从 `market_implied` 换成自研 `dc_dyn`（用户决定，未经 `promotion_check`）：有赔率场次的胜平负、比分、大小球、亚盘赢盘概率和信心档都变了（改按 dc_dyn，`PRIMARY_TIERS` / `PRIMARY_AH_TIERS`），无赔率场次也不再用 dc_market 兜底；重点改为 dc_dyn 档高。市场去水与市场隐含只作对照和 8pp 分歧提示。存档行为只多一项：dc_dyn 存档另记存档时赔率；其余模型照常存档（output 2.0.0、live 2.0.0）。接口快照加 `market_probabilities`、`implied_home_cover`，首次存档按 dc_dyn → market_implied → dc_market 读。依据与代价见「已完成」第一节。

### 1.13.0

报告、主模型、兜底和分歧提示都不变。每场未开赛比赛多存两个并行模型：`dc_dyn`（动态攻防 DC，观测为历史赔率反推 λ）和 `dc_dyn_shots`（观测为进球 + 射门，不用赔率），进成绩单与替换检查（model_dc_dyn 1.0.0、live 1.13.0）。依据见「已完成」第一节。

### 1.12.0

有赔率场次的主模型概率不变。无赔率时回退 `dc_market`（比分、大小球、胜平负都用它；此前比分 dc_xg、胜平负 blend），亚盘同线对照与分歧提示也用 dc_market，`MODEL_TIERS` 重标定（output 1.7.0）。`live --near` 加第二临场档 `*_t2`（存档时离开球 0.6 小时内、用本轮抓的多家赔率），`_t2` 不进替换检查，`horizon_report` 对赛前档与 `_t1` 各配对（review 1.8.0、live 1.12.0）。依据见「已完成」第一节。

### 1.11.1

主模型、存档模型和概率算法不变，修数据层的坏赔率。入库前检查每组赔率（`loader.clean_odds` / `bad_market`）：胜平负、大小 2.5、亚盘（赛前 / 收盘 / Pinnacle / B365）各项隐含概率之和 < 1 时整组当作缺失，亚盘连盘口线一起；赛程表赔率同样处理；多家中位数的胜平负 / 大小 2.5 也这样处理，亚盘不选这样的线。用本地 2526 / 2627 CSV 核对，剔除的正好是库里已有的坏行（亚盘 78 行等），别的行不动；库里旧行按「只补不改」保留，研究脚本照旧过滤。赛程表、快照和多家赔率当前都没有这种行，现有场次的存档不受影响。版本：data 1.9.0（见 issues「football-data 2526 起部分场次的赛前平均亚盘客队水位错误」，已解决）。

### 1.11.0

主模型、存档模型和概率算法不变，只改怎么呈现结论。每场照常给倾向、亚盘选择和把握程度，另加两项。

- 亚盘稳妥线：从市场线往选择方每次让 0.25，取第一条选择方赢盘 ≥ 65% 的线（`analysis.safe_line`，最多 12 步），报告列「亚盘稳妥」，explain、快照、接口（`safe_line` / `safe_cover`）和网站卡片 / 详情都显示；首次存档用存档里的 `extra_markets` 现算。依据 `_diag/explore/ah_confidence_line.py`（`research.db`，选参 1213–2425，留出 2526）：偏离市场线的亚盘隐含赢盘概率是校准的（各档偏差选参 ≤ 1.4pp、留出 ≤ 3pp）；T=0.65 时命中选参 0.682、留出 0.674（T=0.60：0.639 / 0.628；T=0.70：0.731 / 0.735）。命中更高是因为让步了，判断本身没有更准。
- 重点标记：有市场赔率且胜平负信心档为高（Shin 首选概率 ≥ 60%）的场次标「★ 重点」，报告列「重点」，网站「重点比赛」区。高档首选命中选参 0.722（占 28.4%）、留出 0.725（占 26.6%）。原来按亚盘信心档挑推荐，但亚盘高档在留出赛季只有 11 场、命中 0.273，没有得到确认，所以改按胜平负档（据 issues「2526 起部分场次赛前平均亚盘客队水位错误」，这一档留出样本多为坏行，剔除后只剩个位数，仍无法确认）。无赔率的兜底模型场次不标重点。
- 剔除坏行复核（`_diag/explore/ah_clean_recheck.py`，按 `analysis.asian` 原样计算）：稳妥线留出 2526 命中 0.677±0.012（n=1559，平均概率 0.684），football.db 11 联赛 2526–2627 为 0.672±0.007（n=4094），各联赛 0.651–0.711；胜平负高档留出 0.728 / 0.722，不受坏行影响。亚盘高档剔除后 2122 起只有 7 场，近年市场线上选择方赢盘概率几乎都在 0.56 以下；中档实际 0.599 / 0.586，`AH_TIERS` 中档标签因此由 0.562 改为 0.60（下限不变，高 / 低档标签不变）。「★ 重点」场次在市场线上的亚盘选择方命中只有 0.52–0.55，与全体相当：重点只表示胜平负把握高，不表示亚盘把握高，explain 与网站首页、详情页都加了这句说明。1.11.0 下只跑过 10-26 18:43–20:13 的临场档，每次 1.5 小时内 0 场，没有存档也没有重写快照；档位标签只用于显示、不进存档，所以这些改动并入 1.11.0 / output 1.6.0，不另升版本。
- 版本：output 1.6.0（analysis / report / explain / derive）、live 1.11.0；`reports/latest_round.json` 要等下一轮 `live` 或临场档重写后才有新字段，之前网站不显示稳妥线。

### 1.10.1

主模型、存档模型和概率算法不变，修存档时间。每轮用随真实时间走的时钟（`services.round_clock`），赛前档与临场档存档前按它判断，已开球不存；`predictions.generated_at` 记真实存档时刻（此前是一轮开始的时刻），`extra.kickoff_utc` 不晚于它时 `save_prediction` 不存。OddsPortal 的 `fetched_at` 改为每组抓回时刻，抓回时已开球的不入库，临场档 90 分钟新鲜度按存档时刻算。旧库里开球后才存的 2 行（一场的 `lineup_t1` / `lineup_base_t1`）不删，成绩单与 `promotion_check` 不计开球后的存档。版本：data 1.8.0、review 1.7.0、live 1.10.1（见 issues「临场档在开球后才存档」）。

### 1.10.0

分析重心改为亚盘，主模型、存档模型和比分算法不变。报告与 explain 先列市场线亚盘：数字盘口（主队方向，负数 = 主让），赢盘 / 赢半 / 走 / 输半 / 输，选择方与等效赢盘概率，亚盘信心档，初盘 → 最新快照 → 定价的盘口与水位（升盘 / 降盘），dc_xg 在同一线上的赢盘分歧（8pp 提示）。没有市场亚盘时用比分矩阵的公平线，不分档。`AH_LINES` 扩到 −4…+4，存档的 `extra_markets` 从此多出 ±2.25…±4 的线，已有线的概率不变（output 1.5.0）。

亚盘信心档 `AH_TIERS` 在 research.db 5 联赛 1213–2425 标定（不含走盘 21564 场）：赢盘概率 ≥56% 高（历史命中 60.7%，n=1414）、54–56% 中（56.2%，n=2286）、<54% 低（51.7%，n=17864）。2526 留出：中 57.4%（n=61）、低 51.4%（n=1517），高 45.7%（n=35，±8.4%）未确认。市场线上的赢盘概率多数在 50–54%（留出期 94%），隐含模型与该线去水水位平均只差 0.003，五种结算 log loss 标定期 0.983、留出 0.984（`_diag/explore/ah_baseline.py`）。

成绩单加亚盘评分（review 1.6.0）：同场所有模型都在存档时的市场亚盘线上评五种结算 log loss 与赢盘命中（走盘不计），写入 `predictions.ah_line / ah_log_loss / ah_hit`，以前已评分的行自动回填。没有亚盘概率的模型（market_avg、elo、blend）这三列为空。亚盘评分只作参考，`promotion_check` 仍只看 1X2。成绩单代码从 `review/store.py` 拆到 `review/scorecard.py`。版本：output 1.5.0、review 1.6.0、live 1.10.0。

### 1.9.0

实盘联赛从 5 个加到 11 个：英冠 E1、荷甲 N1、葡超 P1、苏超 SC0、比甲 B1、土超 T1，赛季 2122–2627 共 10740 场写入 `football.db`（`_diag/expand/add_live_leagues.py`）。赔率只有 T1 2223 缺 29 场，其余全有；`MARKET_TIERS` 在六个联赛 2122–2526 的 10228 场上核对过（高 73.6% / 90.4%、中 52.0% / 79.1%、低 41.1% / 71.9%），与现有档位一致，不重标（`_diag/explore/new_league_tiers.log`）。Elo / DC 按联赛分别拟合，原五联赛的预测不变。FotMob 登记六个联赛的 id 与队名别名，2627 全部球队都能映射；OddsPortal 登记 slug 与队名别名（含 Wolves、Dundee Utd）。understat 没有这六个联赛，`live` 跳过 `load_xg`，xG 只靠 FotMob 补。`data.oddsportal` 和 `data.fotmob` 的默认联赛改为全部已登记联赛。成绩单和 `promotion_check` 也计入 FotMob 先评分的场次（review 1.5.0 内修正）。版本：data 1.7.0、data_fotmob 1.2.0、live 1.9.0。

### 1.8.0

预测、存档模型和模型拟合不变。football-data 的赛季 CSV 常在完赛几天后才有赛果，实盘评分因此一直落后。`live` 更新数据时另抓 FotMob 5 个联赛页（每联赛 1 次请求，HTML 的 `__NEXT_DATA__`），把完赛比分写入 `fotmob.db` 的 `fotmob_results`（判负 / 取消的场次跳过，按队名相似度与日期 ±1 天算 match_id）。`score_predictions` 在 `matches` 还没有赛果时先用它评分，`predictions.result_src` 记 `fotmob`；football-data 赛果到达后 `reconcile_results` 核对，一致只改标记为 `fd`，不一致按 football-data 重评并打印。`fotmob_results` 不进 `matches`，Elo / DC 拟合只用 football-data 赛果（data_fotmob 1.1.0、review 1.5.0、live 1.8.0）。

### 1.7.0

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
