# 模块化规范

本文件是目录边界、调用方向和单文件尺度的唯一规范。技术选型见 [stack.md](stack.md)。训练、版本和预测规则见 [ml-stack.md](ml-stack.md) 与 `AGENTS.md`。

两人同时改这个仓库时，按目录认领，按下面的箭头调用。不要把规则记在聊天里。

## 三层

调用只有一个方向：

```
web  --HTTP-->  server  -->  services  -->  领域包
live.py / main.py  --------^
```

| 层 | 目录 | 做什么 | 不做什么 |
|---|---|---|---|
| 前端 | `web/` | 展示、发请求、把 OpenAPI 类型交给页面 | 不算概率，不读 `football.db`，不引用 Python |
| 后端 | `server/` | FastAPI 路由、Pydantic 校验、HTTP 状态 | 不写 SQL，不 `fit`，不编排多个模型 |
| 中间层 | `football_prediction/services/` | 一个用例一份编排：实盘一轮、回测一轮、给接口读的报告和成绩单 | 不 import FastAPI，不渲染页面 |
| 领域 | `football_prediction/` 里除 `services/` 以外的包 | 数据、特征、模型、校准、市场分解、落库、回测指标 | 不 import `server`、`web`、`services` |

前端和后端是两个目录、两个进程。中间层是两边的唯一业务入口：`server/` 的路由和命令行入口都调用它，不再各写一套「更新数据 → 评分 → 预测 → 报告」。

`services/` 已建立：`live.py`、`explain.py`、`main.py` 只保留参数、打印和调用，原 `output/pipeline.py` 已并入 `services/match_analysis.py`。`server/` 已建立（只读）：路由只调 `services` 的读函数（`services/match_read.py`：只读打开库、读快照与首次存档），不在路由里抄编排；`tests/test_server.py` 检查 `server/` 只 import `football_prediction.services` / `version` 且不写 SQL。

服务函数不直接 `print`，进度通过参数 `log`（默认 `print`）交给调用方；命令行传 `print`，接口可以传日志函数或空操作。

现有的两处例外，不要新增同类引用：

- `model_market/implied.py` 引用 `output/derive.py` 的亚盘结算函数（`margin_pmf`、`ah_outcome`、`ah_fair_prob`）来拟合市场隐含 λ。
- `model_nn/` 引用 `model_market/implied.py`（`fit_lambdas`、`fair_probs`、`dc_matrix`、`DEFAULT_RHO`）：变体 B 的输入是市场隐含 λ，比分矩阵也用同一个 DC 矩阵（用户 2026-10-27 定）。`model_nn` 不引用别的模型族，Elo 等特征在 `model_nn/dataset.py` 里自己算。

## Agent 模块

`agent/` 在仓库根目录，与 `server/` 并列，按 [agent-dev.md](agent-dev.md) 分阶段写。它只在 `.venv-ml` 里运行（见 [stack.md](stack.md)）。现有（P1、P2、P3）：

| 文件 | 做什么 |
|---|---|
| `agent/config.py` | 库、快照、FotMob 库、知识库目录、向量模型目录与时钟；环境变量 > `.env` 的 `AGENT_DB_PATH` / `AGENT_SNAPSHOT_PATH` / `AGENT_FOTMOB_PATH` / `AGENT_KB_PATH` / `AGENT_EMBED_MODEL` > 默认值，相对路径按仓库根目录；`connect()` 只读打开；测试用 `override()`（可注入假的向量函数） |
| `agent/tools/blocks.py` | 把 `services` 的返回包成块（开头 `scope`、主体键、`kind`、`at`）；开球后的快照看法改标 `last_pre_kickoff`，快照不早于开球的整块丢弃 |
| `agent/tools/matches.py` | 比赛类只读工具：`list_upcoming`、`get_match`、`recent_results`、`explain_fixture`、`scorecard`、`resolve_team`、`team_news` |
| `agent/tools/knowledge.py` | `kb_search`：调 `agent/kb/index.py` 检索，结果包成块；缺 pymilvus、索引没建或正在重建时返回空块和说明 |
| `agent/mcp_server.py` | 用 MCP（stdio）注册 `agent.tools.TOOLS` 里的同一批函数，`ValueError` 转成工具错误 |
| `agent/kb/whitelist.toml` `whitelist.py` | 入库文件白名单（四级 `authority`）和它的核对（路径、不收名单、研究文件的 `cited_in` / `basis` / `generated_by` / 锚点、有提交） |
| `agent/kb/sources.py` | 白名单文件按 git 提交历史切块（每块的可见与被替代时间取提交时间，未提交的改动不收） |
| `agent/kb/match_chunks.py` | 比赛类块（看法、存档、比分、评分、阵容），只经 `services` 的读函数取 |
| `agent/kb/embed.py` | 预切词（中文字二元）、bge-m3 向量函数、测试用的假向量函数 |
| `agent/kb/index.py` | Milvus Lite 索引：建库、增量（替代时间、评分指纹）、按 `as_of` 过滤的向量 + BM25 + RRF 检索、来源标签 |
| `agent/kb/build.py` `__main__.py` | 收齐资料交给 index；`python -m agent.kb --rebuild / --update / --stats / --eval` |
| `agent/eval/retrieval.py` `retrieval.jsonl` | 检索评测集与脚本：三种方式的 recall@5 / MRR 和泄漏检查 |
| `agent/facts/` | 结构化事实：`numbers.py`（第 1 条，数字写法「默认拦、放行表放」）、`units.py`（字段 → 单位对照表与比对）、`verify.py`（第 1–8 条）、`render.py`（占位换成工具结果里的值、来源标签、降级表）。纯 Python，不 import LangChain |
| `agent/llm.py` | 按 `AGENT_PROVIDER` 建模型（SDK 重试设为 0）；`Caller` 每次 HTTP 请求先预留、再调用、再结算，只对超时、429、5xx 重试 1 次 |
| `agent/budget.py` `prices.toml` | 用量库 `agent_data/usage.db`：每次请求 `BEGIN IMMEDIATE` 预留，结算为 settled / failed / usage_unknown；`model_calls`、HTTP 请求数和个人日额度三道上限；价格表按 provider + 模型名 + 生效日取，带高峰倍率时段 |
| `agent/graph.py` `prompts.py` | LangGraph 图（agent ⇄ tools → verify → render / degrade → finish）、四个计数各自判定、单轮超时；`agent_data/state.db` 存对话，每轮只留问题和最终输出。系统提示含北京时间和字段表 |
| `agent/__main__.py` | `python -m agent "问题" [--thread ID] [--check] [--usage]` |
| `agent/access.py` | 网站对话的邀请码与会话：`agent_data/access.db` 只存邀请码和会话 id 的 SHA-256；会话 14 天、可吊销；CSRF 令牌是绑定会话的 HMAC（密钥存在同一库里），24 小时过期；`python -m agent.access add / revoke / list` |
| `agent/serve.py` | 网站对话服务（FastAPI，只听 127.0.0.1:8100）：服务令牌 → 会话 → CSRF → 请求体 → 并发占用 → 一轮；NDJSON 流式返回；记账走 `budget.SITE`（每人当日、全站当日、全站当月），并发每人 1、全站 `AGENT_MAX_CONCURRENCY` |
| `agent/eval/agent.py` `agent.jsonl` | Agent 评测集（26 题）：`--estimate` 预计花费，`--run` 真实跑并算一次通过率、降级率、措辞与 `kind` 不符、放行表打回率和花费 |

工具是普通函数（类型注解 + 中文说明），不 import `mcp`；MCP 和以后的编排框架包装同一个函数，不写两份。

```
agent  -->  football_prediction.services  -->  领域包
```

- `agent/` 只调 `football_prediction.services` 的公开函数和 `version`，不直接 import 领域包，不写 SQL，库一律用 `open_readonly` 打开，不写 `football.db` / `fotmob.db`。需要的新读法加到 `services`（和接口共用）。
- `football_prediction/` 和 `server/` 都不 import `agent`。`server/` 仍只 import `services` / `version`；对话服务是 `agent/serve.py` 单独一个进程，不挂在 `server/` 上。这两条和「`agent/` 里没有 SQL 字符串、不调用 `.execute`」由 `tests/test_agent_boundary.py`（AST 扫描）检查。例外只有两个：`agent/budget.py` 只写用量库 `agent_data/usage.db`，`agent/access.py` 只写邀请码库 `agent_data/access.db`，测试检查它们不碰别的库。FastAPI / uvicorn 只有 `agent/serve.py` 引用。
- 网站对话只有一个转发路由 `web/src/app/api/chat/route.ts`（见「前端文件」）；只读接口仍不经 Next.js 转发。

## 领域包

一个包一种修改理由。新能力优先放进已有的包；只有出现第二种修改理由时才新开包。

| 包 | 修改理由 | 可以引用 | 不可以引用 |
|---|---|---|---|
| `data/` | 外部赛果、赔率、赛程、xG 如何进库 | 同包模块 | 特征、模型、报告、评分 |
| `features/` | 截止日之前的特征 | `data` 的表 | 模型、报告、评分 |
| `model_*/` | 一种预测模型怎么拟合和出概率 | `features`；同族变体可继承同包里的模型 | `review`、`output`、`live`、`server` |
| `calibration/` | 概率校准 | 已算好的概率 | 实盘主流程以外的新入口 |
| `output/` | 比分矩阵和报告长什么样 | 矩阵和已落库的预测 | 拟合、下载 |
| `review/` | 预测怎么落库、怎么赛后评分 | 已写入的概率 | 模型类、`output`（亚盘结算 `ah_settle` 在 `review/store.py` 自带一份，不引用 `output.derive`） |
| `validation/` | 时间外回测和同场比较 | 模型、`output`、指标函数 | `save_prediction` |
| `services/` | 用例怎么把上面几包串起来 | 领域包的公开函数 | FastAPI、页面 |

同族变体留在同包。`model_dc/` 里的 Dixon-Coles、射正版、xG 版是同一比分模型的三种强度估计。新的模型族用新包 `model_<name>/`，不要塞进 `model_dc/`。

领域包之间的箭头不能反向。`data` 不能为了方便去调用模型。两个模型族需要同一段计算时，先让调用留在各自文件里；第二处真正出现后，再抽到一个用职责命名的模块。不要先建 `common.py`。

`大模型项目/` 不在这张依赖图里。任何层都不 import 它。

## 中间层的文件

按用例分文件，不按领域名词再切一层。

| 文件 | 用例 |
|---|---|
| `services/live_round.py` | 实盘一轮：更新数据、赛后评分、未开赛预测存档、主模型报告、成绩单、替换检查；每轮写快照 `reports/latest_round.json`；读函数 `read_current` / `read_match` / `read_scorecard` |
| `services/near_round.py` | 临场档：开球前 1.5 小时内抓阵容和多家赔率，存 `*_t1`（0.6 小时内另存 `*_t2`）并给最终看法 |
| `services/match_analysis.py` | 单场判断的取数与拟合：`ModelCache`、`latest_odds`、`analyse_match`，以及报告（`build_report`）和 explain（`explain_detail`，带赔率获取时间；`explain_inputs` 是它的元组版）共用的串联 |
| `services/team_read.py` | 按队名的只读用例（Agent 工具层用，接口也可用）：`league_code`、`resolve_team_name`（原样 → 别名表 → 部分匹配 → 近似拼写）、`read_team_recent`、`read_next_fixture`、`read_lineups`（只读挂上的 `fotmob.db`）、`read_grading`（评分行，含 `result_src` 与指标列）；知识库建块用的 `read_archived_ids`（有开球前存档的场次）、`read_scores`（按来源分开的比分，各带获取时间） |
| `services/backtest_run.py` | 回测演示：原 `main.py` 里的串联 |

读接口只送出这一轮已经算好的结果，不按请求拟合模型：实盘一轮把每场看法（亚盘在前）和成绩单原子写进快照，`read_current` 剔除快照后已开球的场次，`read_match` 把快照里的本轮看法、`predictions` 里主模型的首次存档（没有时用兜底 dc_market）和赛果拼在一起。快照字段改名或删字段时升 `live_round.SNAPSHOT_SCHEMA`，并同时改路由和测试。`live_round.py` 超过下面的行数上限，或出现第二种读法时，把读函数拆到新的用例文件。

`services/__init__.py` 只做再导出。路由和命令行从 `football_prediction.services` 引用用例函数，不从领域包里自己拼流程。

## 后端文件

```
server/app.py            创建应用、挂上路由
server/routes/<资源>.py  一个资源一个文件，例如 report、review
```

一个路由函数只做三件事：校验请求、调用一个用例函数、把结果或错误变成 HTTP。Pydantic 模型写在使用它的路由文件里。两个路由共用同一个模型，或路由文件超过行数上限时，再把模型挪到 `server/routes/schemas.py`。

## 前端文件

```text
web/src/app/          Next.js 路由、布局、metadata、Provider；页面只组装
web/src/features/     entry、auth、predictions、match、following、review、chat；按业务分模块
web/src/components/   多模块共用展示组件
web/src/lib/          按职责命名的基础能力；服务端模块标明 server-only
web/src/styles/       主题变量、全局样式
web/src/api/          OpenAPI 生成物 schema.d.ts（npm run api:types），禁止手改，ESLint 忽略
```

前端只有一个 Route Handler：`web/src/app/api/chat/route.ts`，只收 POST，把对话转发给只听本机的 `agent.serve`（`features/chat/forward.server.ts`）。它先查 `Origin` 等于 `SITE_URL`、`Host` 是 `SITE_URL` 的主机和端口、`Content-Type` 是 JSON、带 `X-CSRF` 头、有会话 Cookie，任何一项不过都不转发；只转发 `question` 和 `thread_id`，带服务令牌（`AGENT_SERVICE_TOKEN`）、会话 id 和 CSRF 头，用户和 CSRF 由 `agent.serve` 核对。登录和退出是 `features/chat/actions.ts` 里的 Server Action（Next.js 自带 Origin / Host 比对，另按 `SITE_URL` 再查一遍），不另建路由。不要再加别的 `app/api` 路由或代理只读接口。服务端组件经 `features/*/read.server.ts` 取数：未配置 `API_URL` 时读演示样本，配置后由 `lib/api.server.ts` 在服务端请求只读接口，再由各功能的 `api-adapter.ts`（纯函数）把生成类型转成展示契约；序列化后交给客户端组件，只传页面所需的公开数据。浏览器不直接访问接口。

调用方向：app 组装 features / components；features 可以使用 components / lib；components 不反向引用 features。跨功能调用仅使用模块公开入口，其他模块内部文件通过 ESLint 禁止引用。app 只负责页面组合与路由语义；业务交互放功能组件和 hook。Provider 只在实际使用时创建。

客户端不得导入 .server 模块、演示源或 server-only。未来请求入口放功能 hook，底层 HTTP 能力放职责明确的 lib 文件；服务端取数与客户端刷新隔离。生成类型与展示模型分开，展示类型放使用它的功能模块；不要在 api/ 放手写契约。

根布局仅承担 HTML/Provider/跳过链接；`app/(browse)/layout.tsx` 和 `app/site-frame.tsx` 组装业务壳层，业务 URL 不变。首页 `app/page.tsx` 动态读取并投影 current 字段，`entry` 内分离刷新 hook、HTML 卡片、静态海报及懒加载 3D。场景不得接收概率、比赛 ID、读取回执或以其作为 key。`auth` 只管理弹窗表单与焦点，不创建账号服务。根级错误页含壳，业务组错误页复用组布局，不能重复导航或 main。

### 演示契约与状态

每场含 ID、联赛/球队、UTC 开球时间、状态、推荐标记、档名、历史命中率、模型及来源、赔率来源、当前预测、首次预测存档、来源/获取/预测三种时间、可空比分、inplay 状态。无赔率来源为兜底 dc_market，前端只显示字段，不重新兜底。高信心推荐由契约提供，不重算概率阈值。

预测里的亚盘块对应 `output/analysis.py` 的 `asian()`：主队方向数字线、市场线 / 公平线、五种结算概率、选择方与等效赢盘概率、亚盘信心档与历史命中（公平线不分档）、dc_market 同线主队赢盘、盘口变动说明。页面先显示亚盘，再显示胜平负；前端只按 Python `ah_text` / `ah_pick_text` 的写法格式化，不换算中文盘口名，不重算概率。联赛代码与名称在 `features/match/leagues.ts`，顺序与 `live.LEAGUES` 一致。成绩单行对应 `review/scorecard.live_report()`，数值由页面格式化。

筛选不进入 URL，通过 sessionStorage 保存筛选与滚动；关注用 localStorage，客户端 effect 读取，读完前不写空默认值。服务端与客户端首次渲染一致，存储被禁用时保留内存交互并提示无法保存。数据刷新不得重置交互状态。

### 展示与错误边界

主题与移动适配遵循 stack.md。业务页用语义色变量；首页 3D 材质可以用 stack.md 里的专用场景色。inplay 表示滚球，UTC 比较、北京时间展示。页面不写模型规则；当前结果和首次存档分区显示。缺数据显示暂无数据，不补零。

比赛页按请求动态渲染，metadata 与正文复用请求内读取；检查完成前不开始 streaming，不缓存失败结果。未知 ID 使用 notFound 返回 404；读取失败有旧值则展示旧值和延迟，无旧值则抛错误并返回 5xx。客户端刷新错误不等于文档 404。只用服务端测试配置注入故障，不增加公开测试路由。生产 HTTP 测试必须覆盖失败恢复及状态码。

演示站整站禁止收录，不建 sitemap。canonical 使用 SITE_URL 和稳定 match_id，不带客户端筛选状态。真实比赛由后端传入已有 ID，前端不重新哈希。

## 单文件尺度

行数用物理行，`wc -l` 即可，含文档字符串和注释。这是警报，不是凑行数的目标。

| 情况 | 尺度 |
|---|---|
| 目标 | 80–300 行 |
| 必须拆 | 超过 400 行。拆开的依据是第二种职责，拆到同包的新文件 |
| 不要新建 | 不足 80 行，又说不清独立职责 |

例外可以短：

- `__init__.py`、`version.py` 这种注册表。`__init__.py` 里不写业务。
- 同族模型的完整变体。`xg_dc.py` 短，是因为它只换数据源和权重，父类行为仍在 `sot_dc.py`。不要为了凑行数把父类抄进子文件。
- 测试文件不受 80 行下限约束。
- 前端路由、布局、配置、明确职责的小组件与类型可短；不为凑行数混合职责。

现有文件保持原样。`validation/backtest.py` 约 310 行，仍在上限内。`data/loader.py`、`data/oddsportal.py` 已拆到 400 行以下（赛程快照在 `data/fixtures.py`，OddsPortal 解析在 `data/oddsportal_parse.py`；实盘成绩单在 `review/scorecard.py`，从 `review/store.py` 拆出）。不要为了贴合本规范专门去拆或去合并其他文件。下一次改动如果会让文件超过 400 行，先拆再加功能。

禁止碎片化：

- 不一个函数一个文件。
- 不建 `utils.py`、`helpers.py`、`common.py`、`misc.py`、`base.py`、`manager.py`。
- 只被一个文件使用的函数，以 `_` 开头，留在那个文件里。
- 第二个调用方出现，或文件因此超过 400 行，再提到新模块，并用职责命名。

`.ts` 和 `.tsx` 用同一把尺子。不要为单个 Tailwind 节点建组件文件。

## 公开表面

跨包只引用对方的公开函数：没有 `_` 前缀，并且出现在该包 `__init__.py` 的 `__all__` 或文件已有的调用约定里。现有代码直接引用具体模块（如 `football_prediction.data.loader`），继续这样写，不要再包一层转发。

包内可以互用私有函数。包外不引用 `_` 函数。改公开函数的参数或返回字段时，同一次改动里改掉调用方和测试。

## 新代码放哪

按这个顺序决定，停在第一条说得通的：

1. 现有文件里的一个私有函数就能完成。
2. 同一包已有同一职责的文件，放进去后仍不超过 400 行。
3. 同一包里出现了第二种职责：同包新文件。
4. 一种新的数据源、模型族或用例：新包，或 `services/` 里的新用例文件。

判断标准是「以后改它的理由是否和这个文件原来的理由相同」。只为了让原文件看起来短，不开新文件。

新增带 `LAYER_VERSION` 的领域模块时，仍走 `AGENTS.md` 的「改一层时」。`services/` 和 `server/` 不单独登记预测版本；它们改变的是编排或 HTTP，预测算法变了才升对应领域层的版本。

## 两人协作

按目录分工，不按「谁有空谁改一行」。

| 目录 | 负责 | 另一人使用的方式 |
|---|---|---|
| `web/` | 页面 | 只看 OpenAPI，不改 Python |
| `server/` | HTTP | 只调 `services` 的公开函数 |
| `services/` | 用例契约 | 改签名的人同时改路由、命令行和测试 |
| `data/` `features/` `model_*/` `calibration/` `validation/` | 数据与模型 | 通过用例使用，不从 `web/` 或 `server/` 调用 |
| `output/` `review/` | 预测结果的形状 | 通过用例使用 |
| `version.py` | 谁改变了行为谁更新 | 另一人不要在同一轮改版本号 |

同一轮不要两个人改同一个领域包。要改 `services` 的公开签名、OpenAPI 响应字段或 `version.py` 时，先看这个文件是否已有未合并的改动，并在同一次改动里更新调用方。

一次改动穿过相邻的两层为止：例如一个领域包加上调用它的用例，或一个路由加上用例签名。算法改动不顺手改页面文案，页面改动不改 SQL。响应字段要两边一起变时，这次改动只含契约和它的调用方。

Python 测试跟着被测模块走，放在 `tests/test_<模块>.py`。已有文件能放下就写进已有文件；超过 400 行再按被测模块拆。新测试保持离线，用内存 SQLite，不碰 `football.db`。

前端组件测试放在所属功能目录，生产 HTTP/浏览器测试放 web/tests。源文件长度由 ESLint 检查（物理行，400 行上限），生成物除外。
