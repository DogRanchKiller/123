# 项目进度

系统版本：1.11.1，与 `football_prediction/version.py` 的 `SYSTEM_VERSION` 一致。

更新日期：2026-10-26。

这份文件只描述当前状态。规则在 `AGENTS.md`、`docs/stack.md`、`docs/modules.md`、`docs/ml-stack.md`。问题记录在 [issues.md](issues.md)。

## 当前

命令行预测可以跑。网站 `/` 是深色全息首页，预测、关注、详情和成绩单共用同一套深色业务页。中间层 `services/` 已建立，实盘每轮写快照 `reports/latest_round.json`；只读接口 `python -m server`（FastAPI，无鉴权，默认只听本机）读快照和首次存档。网站配置 `API_URL` 时显示本机实盘数据，不配置时显示演示数据。账号服务尚未建立。

- 联赛：英超 E0、德甲 D1、西甲 SP1、意甲 I1、法甲 F1、英冠 E1、荷甲 N1、葡超 P1、苏超 SC0、比甲 B1、土超 T1（实盘库都从 2122 起；后六个没有 understat xG）。研究库 `research.db` 只有前 5 联赛 9394–2526（赔率从 0001 起，xG 从 1415 起）。
- 主模型：`market_implied` / `model_market` 1.0.0（市场赔率反推比分）。无赔率时回退 `dc_xg` / `model_xg` 1.0.0。
- 分析重心：亚盘为主，胜平负 / 比分 / 大小球为辅（output 1.6.0）。每场都给结论和把握程度，另给亚盘稳妥线（选择方赢盘 ≥ 65% 的最近一条线）；胜平负市场档为高的场次标「★ 重点」。报告和 explain 先列市场线亚盘（数字盘口，如 主-0.75），成绩单另列亚盘评分；亚盘评分只作参考，替换主模型仍只看 1X2 的 `promotion_check`。
- 实盘：`python -m football_prediction.live`；单场说明：`python -m football_prediction.explain 英超 Arsenal Chelsea`
- 多家赔率：`python -m football_prediction.data.oddsportal --hours 30`
- 临场档：`python -m football_prediction.live --near`（`run_near.bat`）；阵容 / 伤停：`python -m football_prediction.data.fotmob`
- FotMob 库：仓库根目录 `fotmob.db`（gitignore，可由 `_cache/fotmob/` 重建）
- 回测：`python -m football_prediction.main`
- 报告：`reports/预测_YYYY-MM-DD.csv`
- 数据库：仓库根目录 `football.db`
- 定时：Windows 任务计划每天 18:07、23:37 跑 `run_daily.bat`（live + oddsportal + fotmob 阵容），日志 `logs/daily.log`；`FootballPredictNear` 每天 18:13–05:43 每 30 分钟跑 `run_near.bat`，日志 `logs/near.log`（需开机）。

## 已完成

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
| data_fotmob | 1.2.0 | FotMob HTML 页：阵容（预测 / 正式）、伤停、球员分钟与 xG / xA、射门；understat 缺时补 `match_xg`；联赛页完赛比分 `fotmob_results`（只用于先评分）。11 个联赛都已登记；历史补抓 E0 / D1 / SP1 2324 起，新增六个联赛只有 2627 |
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
| output | 1.6.0 | 亚盘稳妥线（`analysis.safe_line`，`SAFE_TARGET=0.65`）与重点标记（`highlight` = 有市场赔率且胜平负档高），报告加「亚盘稳妥」「重点」列；亚盘为主：报告列「亚盘 / 亚盘选择 / 亚盘信心 / 亚盘变动」紧跟对阵，explain 第 [2] 段为亚盘，`AH_LINES` 覆盖 −4…+4；判断流程（`analysis.py`）、报告、explain 单场说明、亚盘五种结算；信心档按 Shin 概率在 5 联赛重标定，报告与 explain 列本场命中估计；报告与 explain 优先用多家中位数赔率（`services.latest_odds`），列赔率来源 |
| validation | 1.1.0 | 时间外回测、市场基准、同场配对 |
| review | 1.6.0 | 首次预测落库、赛后评分（含亚盘：按存档时的市场线算五种结算 log loss 与赢盘命中，`ah_line` / `ah_log_loss` / `ah_hit`；成绩单代码在 `scorecard.py`）（含大小 2.5 / 精确比分；football-data 未到时先用 FotMob 比分，到达后 `reconcile_results` 核对）、`promotion_check`（跳过 `_t1`）、`horizon_report` 临场对赛前 |
| live | 1.11.0 | 11 联赛；快照与接口每场带稳妥线 `safe_line` / `safe_cover` 和重点标记；成绩单加亚盘场数 / LL / 赢盘命中；更新数据（含 FotMob 完赛比分）、评分、预测、报告、成绩单；存档 market_implied / blend / market_shin / dc_market；`--near` 临场档 `*_t1` 与 lineup_t1 / lineup_base_t1，先抓阵容再抓赔率，打印临场最终看法 |

`2526` 留出，不在该季上重选 shrink 和权重。替换主模型只看实盘 `promotion_check`，场数至少 1000。

扩样本结论（`research.db`，5 联赛 × 1718–2526 样本外 16k 场）：自研模型每个联赛、每个赛季都不如赛前市场。提高准确率要靠赔率里还没有的信息。

## 已约定，尚未写代码

- 兜底模型：建议把 `FALLBACK_MODEL` 换成 `dc_market`（回测在 4/5 联赛优于 dc_xg），由用户决定；按规则也可等实盘配对。
- 临场档信心档：`MARKET_TIERS` 已按 Shin 赛前概率重标（output 1.3.0）；临场档（T1 多家中位数）有实盘样本后再核对档位命中率。
- 多家中位数的准确度：报告已改用 OddsPortal 多家中位数（只有 5 家美国公司），它与 football-data 平均赔率哪个更准，等 `horizon_report` 和赛前存档有足够已评分场次后再比；赛前存档仍用赛程表赔率。
- 网站数据刷新：接口只反映最近一次写快照的运行（每天两次定时 `live`、窗口内有场次的临场档 `--near`、手动）；首页每 60 秒重读。需要更快刷新或客户端轮询时再引入 TanStack Query。
- 账号与短信：顶栏已有登录/注册表单（邮箱密码、确认密码、手机验证码）和校验。提交、验证码和找回密码只提示服务未接入。账号服务、短信和登录会话尚未实现。
- 数据更新：先评估免费 API 的覆盖、授权与额度，再实现赛前赔率持续更新；目标 1–5 分钟，以数据源实际能力为准。
- 实时比分与比赛状态：未接入。
- 滚球预测（inplay）：未实现，需独立模型与数据链路，不能复用赛前结果冒充。
- 正式部署与搜索收录：尚未上线；真实数据上线后才开放指定页面并建立 sitemap。
- 网站上线给群友：`run_api.bat`、`run_site.bat`、`setup_site.ps1` 已写好（Tailscale、无口令，见 `docs/stack.md`），还要用户装好并登录 Tailscale、把本机共享给群友，再用管理员 PowerShell 跑一次 `setup_site.ps1`。开机任务和防火墙规则尚未注册；S4U 任务能否正常找到 node / python 未验证。
- `football_prediction/model_nn/`：还没有神经网络。`requirements.txt` 里还没有 `torch`。
- 亚盘研究（第 3 步）：在 `research.db` 上看哪些信息能改进市场线上的赢盘概率（盘口与水位变动、Pinnacle 对平均、四分之一线结算形状），沿用同场配对与 2526 留出规则。
- Pinnacle 亚盘（第 4 步）：先核对本机能否看到、服务条款与 robots.txt，允许才接入；不绕过反爬。
- 用户定的顺序（2026-10-25）：扩联赛（1.9.0 已做六个一级联赛）→ 网页 + 接口（局域网 / 群友内网访问）→ 神经网络穿插进行 → 新信息源持续做。
- 杯赛档（欧冠、国内杯赛）：football-data 没有杯赛数据，需另找赛果与赔率来源；有加时 / 点球，评分要先定按 90 分钟还是最终结果；跨联赛对阵不能用按联赛拟合的 Elo / DC，只能用市场赔率。
- 新增六个联赛的 xG：football-data 2627 起有 `HxG` / `AxG` 列，可作为 understat 之外的来源（见 issues）。

## 版本记录

### 1.11.1（当前）

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
