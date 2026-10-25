# 技术栈

本文件定义前端、后端、训练的选型。训练的数据切分、指标、版本和 checkpoint 规则仍以 [ml-stack.md](ml-stack.md) 为准。

三层分工固定：浏览器只展示和发请求；FastAPI 只暴露现有预测能力；训练只在 Python 里进行，不在 TypeScript 里训练。

## 网站前端

公开只读网站，访客可查看预测与比赛状态，不提供训练或修改数据操作。目录 `web/`；框架 Next.js 16 稳定版 + React，App Router；TypeScript strict；Tailwind CSS + 语义主题变量。替代原 Vite / React Router 方案。Next.js 只负责网站渲染，不计算概率或模型兜底。

Mac、Windows 统一 Node.js 24 LTS（`.nvmrc`、`package.json engines`），npm 管理依赖；提交 `web/package-lock.json`，用 `npm ci` 安装。生产需 Node 服务端，不能静态导出。开发和检查命令见 `AGENTS.md`。

首次浏览器测试运行 `npx playwright install chromium`。typecheck、build 和 npm ci 顺序执行，避免生成目录或依赖被并发替换。组件测试用 Vitest/Testing Library；端到端检查对 next start 的生产产物执行。

首轮只有演示骨架：服务端组件直接引入静态演示契约，不建后端、services、`app/api`、OpenAPI 生成目录或 HTTP 演示接口。TanStack Query 在真实接口接入时再启用；接口类型用 openapi-typescript 从 FastAPI OpenAPI 生成，禁止手改。

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

SITE_URL 在生产构建前设置，静态页面 metadata 会使用构建时域名。进程管理器负责重启和日志，反向代理不缓存动态比赛及错误响应。WEB_TEST_CONTROL_FILE 只用于本机故障注入，正式运行不设置。演示成功结果仅有进程内缓存，重启后不保留；真实接入时改由后端提供持久的最近有效结果。

## 后端与后续数据接入

Python 3.12+；FastAPI + Uvicorn + Pydantic v2，目录 `server/`，只调用 `football_prediction/services/`，数据库继续使用根目录 football.db。建立后端时按 [modules.md](modules.md) 同时迁移现有编排，不提前建空包。

FastAPI 接入后由 Next 开发服务器代理 `/api`；生产同域，浏览器不需要 CORS。首轮不占用 `/api`，不建 Next Route Handler 或代理。Web 不提供公开训练、采集或写库入口。

先评估允许公开展示的免费 API：三联赛覆盖、盘口种类、额度、实际延迟。目标刷新 1–5 分钟，不能将页面刷新频率当作数据源实时能力；搜索引擎不是赔率源，爬虫只作允许访问的补充。依次接入赛前赔率、实时比分与状态、独立滚球模型。后端集中采集与缓存，网页只读；当前预测与首次预测存档分离。接口应提供数据来源时间、获取时间、预测时间以及新鲜度状态。

真实接口接入时使用 TanStack Query；手机后台暂停轮询，恢复前台重新取数，保留筛选与滚动。无新结果时保留旧值并提示延迟，不伪造概率。训练、FastAPI 依赖仍在对应功能落地时引入。

## 训练

训练语言是 Python，和后端同一个解释器。2026 年工业界的训练默认仍是 Python：PyTorch 做神经网络，梯度提升树做表格数据。TypeScript 只出现在前端。

本仓库的预测输入是每场比赛的数值特征，不是文本。默认方式按输入分开，主模型保持 `version.PRIMARY_MODEL`（现为市场隐含 `market_implied` / `model_market`，无赔率时回退 `dc_xg` / `model_xg`）。

| 输入 | 方式 | 库 |
|---|---|---|
| 比分与攻防强度 | Dixon-Coles 一族（已有 Elo、射正版、xG 版留在原模块） | NumPy、SciPy |
| 表格特征上的机器学习 | 梯度提升树。这是 2026 年结构化数据上的工业默认 | LightGBM |
| 新的神经网络 | `torch.nn.Module` 加自己的训练循环 | PyTorch |
| 文本、序列或预训练语言模型 | LoRA；显存不够时用 QLoRA。监督微调用 SFT，有偏好标签时用 DPO | PyTorch、Transformers、PEFT、TRL |

不引入 TensorFlow 或 JAX。表格模型不用 Hugging Face Trainer。

`大模型项目/微调/` 里的 P-Tuning 和 PET 是上一代课堂写法。新训练不沿用这两种方法。需要参考时只借鉴循环结构（数据切分、训练步、验证、保存），实现放在 `football_prediction`，不 import 该目录。

新网络的落点、概率契约、`2526` 留出和 Log Loss / Brier 见 [ml-stack.md](ml-stack.md)。
