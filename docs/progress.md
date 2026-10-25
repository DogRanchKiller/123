# 项目进度

系统版本：1.4.0，与 `football_prediction/version.py` 的 `SYSTEM_VERSION` 一致。

更新日期：2026-10-25。

这份文件只描述当前状态。规则在 `AGENTS.md`、`docs/stack.md`、`docs/modules.md`、`docs/ml-stack.md`。问题记录在 [issues.md](issues.md)。

## 当前

命令行预测可以跑。网站 `/` 是深色全息首页，预测、关注、详情和成绩单共用同一套深色业务页。页面数据仍是演示数据。真实 HTTP 接口、账号服务和 `services/` 中间层尚未建立。

- 联赛：英超 E0、德甲 D1、西甲 SP1。研究库 `research.db` 另含意甲 I1、法甲 F1。
- 主模型：`market_implied` / `model_market` 1.0.0（市场赔率反推比分）。无赔率时回退 `dc_xg` / `model_xg` 1.0.0。
- 实盘：`python -m football_prediction.live`；单场说明：`python -m football_prediction.explain 英超 Arsenal Chelsea`
- 多家赔率：`python -m football_prediction.data.oddsportal --hours 30`
- 回测：`python -m football_prediction.main`
- 报告：`reports/预测_YYYY-MM-DD.csv`
- 数据库：仓库根目录 `football.db`
- 定时：Windows 任务计划每天 18:07、23:37 跑 `run_daily.bat`（live + oddsportal），日志 `logs/daily.log`。

## 已完成

### 网站演示骨架（web 0.1.0）

- Next.js 16.4.3 + React 19 + TypeScript strict，Node.js 24 LTS；npm 锁文件与前端检查命令已加入，依赖审计 0 vulnerabilities。
- 预测列表、高信心推荐、比赛详情、首次预测存档、手动关注和成绩单页面；全部使用固定演示数据，明确标识。
- 全站深色语义主题；独立 `/` 入口壳层与 3D 全息球场，业务页使用静态背景；关注 localStorage、筛选/滚动 sessionStorage，挂载后恢复。
- 首页预测卡片来自当前演示预测，按推荐优先选场；可见时每 60 秒刷新，失败保留旧值并提示延迟，场景与概率刷新隔离。
- 首页 3D 使用 Three.js / React Three Fiber、程序化球场和粒子；WebGL/减少动态效果可降级静态海报。邮箱和手机登录注册仅有校验表单，不接账号服务、不持久化凭据。
- 比赛详情按请求渲染；稳定 ID、北京时间展示、来源/获取/预测三类时间；无赔率来源直接显示契约字段。
- 演示站整站 noindex、robots 禁止抓取，不发布 sitemap，不建 /api；真实比分、滚球能力只展示未接入状态。
- 验收通过：TypeScript、ESLint、12 项组件测试、Next.js 生产构建、20 项生产 Chromium 测试；覆盖首页选场/刷新失败恢复/超时后重试/Canvas 稳定、登录键盘与校验、SSR/metadata/404/5xx、关注/筛选/滚动恢复及 360/390/768/1023/1024/1440 页面溢出与平板折叠菜单。Python 离线测试 98 项通过；预测版本不变。
- 已在桌面 Google Chrome 与 Safari 打开检查首页，Playwright Chromium 覆盖六种视口；手机为响应式模拟，未做真机测试。球场帧率未做设备级测量，60/30fps 仍是优化目标。尚未正式部署。

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
- 网站真实数据：FastAPI 接入后生成 OpenAPI 类型，加入 TanStack Query 和同域 /api 代理。首页现在每 60 秒重读演示数据；演示内容不变时，卡片数字不会变。
- 账号与短信：顶栏已有登录/注册表单（邮箱密码、确认密码、手机验证码）和校验。提交、验证码和找回密码只提示服务未接入。账号服务、短信和登录会话尚未实现。
- 数据更新：先评估免费 API 的覆盖、授权与额度，再实现赛前赔率持续更新；目标 1–5 分钟，以数据源实际能力为准。
- 实时比分与比赛状态：未接入。
- 滚球预测（inplay）：未实现，需独立模型与数据链路，不能复用赛前结果冒充。
- 正式部署与搜索收录：尚未上线；真实数据上线后才开放指定页面并建立 sitemap。
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
