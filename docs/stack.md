# 技术栈

本文件定义前端、后端、训练的选型。训练的数据切分、指标、版本和 checkpoint 规则仍以 [ml-stack.md](ml-stack.md) 为准。

三层分工固定：浏览器只展示和发请求；FastAPI 只暴露现有预测能力；训练只在 Python 里进行，不在 TypeScript 里训练。

## 网站前端

公开只读网站，访客可查看预测与比赛状态，不提供训练或修改数据操作。目录 `web/`；框架 Next.js 16 稳定版 + React，App Router；TypeScript strict；Tailwind CSS + 语义主题变量。替代原 Vite / React Router 方案。Next.js 只负责网站渲染，不计算概率或模型兜底。

Mac、Windows 统一 Node.js 24 LTS（`.nvmrc`、`package.json engines`），npm 管理依赖；提交 `web/package-lock.json`，用 `npm ci` 安装。生产需 Node 服务端，不能静态导出。开发和检查命令见 `AGENTS.md`。

首次浏览器测试运行 `npx playwright install chromium`。typecheck、build 和 npm ci 顺序执行，避免生成目录或依赖被并发替换。组件测试用 Vitest/Testing Library；端到端检查对 next start 的生产产物执行。

服务端组件取数：未配置 `API_URL`（只在服务端读取，运行时生效，不加 `NEXT_PUBLIC_`）时用固定演示样本，配置后请求只读接口。接口类型用 openapi-typescript 7.13.0 从 `web/openapi.json` 生成到 `src/api/schema.d.ts`（`npm run api:types`），禁止手改；`openapi.json` 由 `python -m server --openapi web/openapi.json` 导出，`tests/test_server.py` 检查两者一致。不建 `app/api` 或 /api 代理。TanStack Query 暂缓：数据每轮实盘才变，服务端组件取数加现有的首页定时刷新已够用，需要客户端轮询或乐观更新时再引入。

### 展示与手机适配

中文界面，根布局 `lang="zh-CN"`。全站深蓝黑主题、青色强调与清晰白字；业务背景、文字、边框、强调色、状态色使用语义 CSS 变量。首页独立壳层，业务页使用静态背景；3D 材质与首页装饰光允许专用颜色。

首页使用 Three.js + React Three Fiber 9（React 19）+ drei + postprocessing，程序化几何和 GPU 粒子，不引入 GSAP。模块级动态加载；HTML 预测卡片与 Canvas 隔离，场景不接收预测数据。静态 SVG 海报优先，WebGL2/加载失败降级，减少动态效果默认静态。手机 800 粒子、DPR 1、无后期；桌面 3000 粒子、DPR ≤1.5、Bloom；低帧率降档，离屏和后台暂停。

首页当前预测由 readDemoMatches() 选取：推荐未开赛且有 current 优先，否则第一场未开赛且有 current。页面可见每 60 秒 router.refresh()，回前台立即刷新。独立读取回执判断完成；15 秒超时或读取失败保留旧卡片与原时间并显示延迟，同值不动文字，成功无候选清空。刷新不能重挂 Canvas。

登录注册仅有前端表单（邮箱密码、确认密码、手机验证码）与校验、焦点管理；提交、短信、找回均诚实提示服务未接入，无认证 Cookie、密码持久化或假成功。业务页不要求登录。

移动端优先：手机单列卡片与可折叠菜单，桌面多列或表格；360px 不发生页面级横向溢出，宽表仅在容器内滚动。触摸目标至少 44×44px，支持键盘焦点、文字缩放，操作不依赖悬停。验收宽度 360 / 390 / 768 / 1440；桌面 Safari、Chrome 响应式模式，真机未测不得宣称通过。

存储与时间比较用 UTC 瞬间，展示用 Asia/Shanghai 并标注北京时间。模型、档名、命中率与来源均显示数据字段。保留高信心档历史上仍约四分之一未命中的提示。滚球代码名 inplay，与 Python live 实盘入口区分。

### 渲染、SEO 与部署

比赛页按请求动态渲染；存在性、数据和 metadata 在输出响应前检查，不用提前流式 loading 掩盖 404/5xx。实际状态码以 `next build` + `next start` 验收为准。正式取数 no-store，失败不缓存；数据刷新不能改写真实数据时间。

演示阶段整站 `noindex`、`X-Robots-Tag: noindex, nofollow`、robots `Disallow: /`，不发布 sitemap。页面仍提供正文、标题、描述和 canonical。真实数据上线后才单独开放收录、生成真实比赛 sitemap；关注页始终不收录。比赛路径直接使用后端 match_id，不按球队名称生成；延期改期身份由后端处理。

开发：在 web 执行 `npm ci`、`npm run dev`，默认仅监听 localhost。生产：`npm run build` 后 `npm run start`，由 HTTPS 反向代理转发至 Next.js，配置 `SITE_URL` 为实际域名。首轮不购买或部署云服务。环境变量示例在 `web/.env.example`；密钥不得放进 NEXT_PUBLIC 变量或客户端代码。

群友访问（2026-10-26 定）：走 Tailscale 组网，不加访问口令，只靠网络限制。`run_site.bat` 先 `npm run build`，再 `next start` 只监听本机的 Tailscale IPv4（100.x）端口 3000，不监听局域网和公网网卡；`setup_site.ps1` 另加防火墙规则，3000 端口只放行 100.64.0.0/10。接口 `run_api.bat` 始终只听 127.0.0.1:8000，没有防火墙规则。两个脚本崩溃后 30 秒重启，日志写到 `logs/api.log`、`logs/site.log`（gitignore）。`setup_site.ps1` 要用管理员 PowerShell 跑一次，注册开机任务 `FootballSiteApi` / `FootballSiteWeb`（当前用户 S4U，不存密码），`-Remove` 撤销。Tailscale 的安装、登录和把本机共享给群友由用户在 Tailscale 里做；共享时只共享这台机器。站点运行时不要在 `web/` 里另跑 `npm run build` 或 e2e，它们会改写正在服务的 `.next`。

问答（P6，2026-10-27 定做法 A）：`run_agent.bat` 跑 `.venv-ml` 里的 `python -m agent.serve`，只听 127.0.0.1:8100，没有防火墙规则，日志 `logs/agent.log`；还没有登记开机任务（`setup_site.ps1` 未改），要手动起或另加任务。浏览器只访问 Next.js：登录和退出是 Server Action，对话走唯一的转发路由 `/api/chat`，Next.js 在服务端带服务令牌转给 `agent.serve`。群友凭邀请码登录（`.venv-ml` 的 `python -m agent.access add 名字` 打印一次邀请码，库里只存哈希；`revoke` 吊销其全部会话），会话 Cookie `fp_chat` 是 `HttpOnly`、`SameSite=Strict`、`Path=/`、14 天，站点是 http 所以不带 `Secure`，传输安全靠 Tailscale。根目录 `.env` 和 `web/.env.local` 填同一个 `AGENT_SERVICE_TOKEN`（至少 32 个字符，由用户生成填写）；`run_site.bat` 默认设 `AGENT_SERVE_URL=http://127.0.0.1:8100`，两者都有才显示问答。对话路由和登录按 `SITE_URL` 核对 `Origin` 与 `Host`：`run_site.bat` 不设时取 `http://<Tailscale IPv4>:3000`，群友要用别的地址（如 MagicDNS 名）打开时，在启动前的环境变量里设 `SITE_URL`（进程环境变量优先于 `web/.env.local`），否则问答会回 403。额度和并发见 `docs/agent-plan.md` 第 10.3 节，配置在 `.env`。

SITE_URL 在生产构建前设置，静态页面 metadata 会使用构建时域名。进程管理器负责重启和日志，反向代理不缓存动态比赛及错误响应。WEB_TEST_CONTROL_FILE 只用于本机故障注入，正式运行不设置。演示成功结果仅有进程内缓存，重启后不保留；真实接入时改由后端提供持久的最近有效结果。

## 后端与后续数据接入

Python 3.12+；FastAPI + Uvicorn + Pydantic v2，目录 `server/`，只调用 `football_prediction/services/`，数据库继续使用根目录 football.db。`services/` 已建立；接口读实盘一轮写的快照 `reports/latest_round.json` 和 `predictions` 首次存档，不按请求拟合模型（见 [modules.md](modules.md)）。

只读接口：`python -m server`（默认 127.0.0.1:8000；`--host/--port/--db/--snapshot/--fotmob`），`GET /api/matches`（`?recent_days=` 附带最近已开球场次，默认 3）、`/api/matches/{id}`、`/api/review`。库以 `mode=ro` 打开（`fotmob.db` 同样只读挂上补比分），无快照时 503，未知比赛 404。没有鉴权：默认只监听本机，改 `--host` 时会打印警告，局域网访问范围要在网络层限制。网站服务端用 `API_URL` 直连，浏览器不访问接口，不需要 CORS，也不建 Next Route Handler 或代理。Web 不提供公开训练、采集或写库入口。Agent 和训练不在 `.venv` 里运行，见下面「Agent 与训练环境」。

先评估允许公开展示的免费 API：11 个实盘联赛的覆盖、盘口种类、额度、实际延迟。目标刷新 1–5 分钟，不能将页面刷新频率当作数据源实时能力；搜索引擎不是赔率源，爬虫只作允许访问的补充。依次接入赛前赔率、实时比分与状态、独立滚球模型。后端集中采集与缓存，网页只读；当前预测与首次预测存档分离。接口应提供数据来源时间、获取时间、预测时间以及新鲜度状态。

以后引入 TanStack Query 时：手机后台暂停轮询，恢复前台重新取数，保留筛选与滚动。现在单场读取失败时保留同一服务进程内的上次结果并提示延迟，不伪造概率。训练依赖仍在对应功能落地时引入。

## 训练

训练语言是 Python，和后端同一个解释器。2026 年工业界的训练默认仍是 Python：PyTorch 做神经网络，梯度提升树做表格数据。TypeScript 只出现在前端。

本仓库的预测输入是每场比赛的数值特征，不是文本。默认方式按输入分开，主模型保持 `version.PRIMARY_MODEL`（2.0.0 起为动态攻防 `dc_dyn` / `model_dc_dyn`，有没有赔率都用它；市场隐含 `market_implied` 是 `version.MARKET_MODEL` 对照）。

| 输入 | 方式 | 库 |
|---|---|---|
| 比分与攻防强度 | Dixon-Coles 一族（已有 Elo、射正版、xG 版留在原模块） | NumPy、SciPy |
| 表格特征上的机器学习 | 梯度提升树。这是 2026 年结构化数据上的工业默认 | LightGBM |
| 新的神经网络 | `torch.nn.Module` 加自己的训练循环 | PyTorch |
| 文本、序列或预训练语言模型 | LoRA；显存不够时用 QLoRA。监督微调用 SFT，有偏好标签时用 DPO | PyTorch、Transformers、PEFT、TRL |

不引入 TensorFlow 或 JAX。表格模型不用 Hugging Face Trainer。

`大模型项目/微调/` 里的 P-Tuning 和 PET 是上一代课堂写法。新训练不沿用这两种方法。需要参考时只借鉴循环结构（数据切分、训练步、验证、保存），实现放在 `football_prediction`，不 import 该目录。

新网络的落点、概率契约、`2526` 留出和 Log Loss / Brier 见 [ml-stack.md](ml-stack.md)。

## Agent 与训练环境

设计在 [agent-plan.md](agent-plan.md)，分阶段做法在 [agent-dev.md](agent-dev.md)。大模型不产生概率：胜平负、亚盘、比分、大小球的数字只来自 `services` 和现有模型，Agent 负责调用工具、检索、比对和解释。

两个环境，现有 `.venv` 不加任何包：

| 环境 | 装什么 | 谁用 |
|---|---|---|
| `.venv` | `requirements.txt` | `live`、`server`、定时任务、`python -m pytest tests` |
| `.venv-ml`（gitignore） | `requirements.txt` + `requirements-ml.txt`，受 `constraints-ml.txt` 约束 | `agent/`、MCP、知识库、`model_nn` 训练、LoRA 微调 |

- `requirements-ml.txt` 只写直接依赖，都用 `==` 钉版本：langgraph、langgraph-checkpoint-sqlite、langchain-core、langchain-openai、langchain-anthropic（编排与模型接口）；pymilvus、milvus-lite、sentence-transformers（知识库）；mcp、python-dotenv；torch、transformers、peft、trl、datasets（训练）。
- `constraints-ml.txt` 钉与 `requirements.txt` 重叠的包，版本等于 `.venv` 里实际装的版本；解析冲突时改 ML 包的版本，不改 `requirements.txt`。另钉 tokenizers、safetensors 等关键间接依赖。不用整份 `pip freeze`。
- 编排框架用 LangGraph（用户 2026-10-27 在 P1.5 概念验证后选定，不用 OpenAI Agents SDK；两者没有做对比实现）：图与状态用 `langgraph`，对话状态持久化用 `langgraph-checkpoint-sqlite`（存 `agent_data/`），模型接口用 `langchain-openai`（OpenAI 兼容接口：中转站、本地 Ollama）和 `langchain-anthropic`（Claude）。SDK 自带重试关掉，由我们自己的代码限次重试并逐个数 HTTP 请求。概念验证的代码在分支 `agent/p15-poc`，不合入 main；`.venv-poc` 已删。
- 默认云端模型（决定 2）：OpenAI 兼容中转站上的 `DeepSeek-v4.1-flash-1017`，地址、模型名和密钥只写在本机 `.env`（`AGENT_PROVIDER` / `AGENT_MODEL` / `AGENT_BASE_URL` / `OPENAI_API_KEY`）。
- 密钥只放仓库根目录 `.env`（gitignore），变量名见 `.env.example`；代码和日志里不出现密钥。知识库索引（`agent_data/kb/`）、对话状态、用量库放 `agent_data/`，权重放 `checkpoints/`，都不进版本库，也不写进 `football.db`。
- 向量知识库用 Milvus Lite（用户 2026-10-27 在 P2 选定，替代原方案的 Chroma）：`pymilvus` 的 `MilvusClient` 打开本地数据目录 `agent_data/kb/milvus.db`，同一集合里存 bge-m3 稠密向量和 Milvus BM25 函数生成的稀疏向量，两路检索后在 Python 里做 RRF。数据目录有独占锁，`--rebuild` / `--update` 进行中时 `kb_search` 返回「正在被使用」的说明。纯 Python 包，2026-10-27 在 Windows 实盘机实测可用（Python 3.12，CPU 上 `--rebuild` 约 8 分钟）。
- 向量模型 bge-m3 放 `checkpoints/bge-m3/`（约 2.1 GB），只从本地加载（`local_files_only`），路径可用 `AGENT_EMBED_MODEL` 改。下载：`huggingface_hub.snapshot_download("BAAI/bge-m3", revision="5617a9f61b028005a4858fdac845db406aefb181", local_dir="checkpoints/bge-m3")`，只取 sentence-transformers 需要的配置、分词器和 `pytorch_model.bin`（不取 ONNX 和 colbert / sparse 权重），再用 torch 转成 `model.safetensors`、删掉 `.bin`。另一台机器照此下载，或直接拷贝这个目录。下载卡住不动时设 `HF_HUB_DISABLE_XET=1` 改走 HTTP（见 `docs/issues.md`）。
- 模型权重（bge-m3、重排模型、Qwen 等）下载前先说明仓库和体积，经用户同意再下。
