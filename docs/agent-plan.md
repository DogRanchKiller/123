# Agent 与训练模块方案（第 5 稿，已通过）

状态：2026-10-27 审核通过，按 [agent-dev.md](agent-dev.md) 分阶段开发。第 1 稿 2026-10-26 提出；第 2 稿同日按审核意见修订：依赖与环境隔离（第 5 节）、结构化数字校验（第 8 节）、RAG 时点与白名单（第 7 节）、`model_nn` 覆盖与门槛（第 9.1 节）、网页访问与额度（第 10 节），框架比较改为概念验证（第 3 节）。第 3 稿（2026-10-27）按复审意见修订：G1 预注册与多重比较、训练样本按场时点构造（第 9.1 节）；事实作用域、单位、开球后快照改标（第 6、8 节）；白名单逐文件、赛果与评分分块（第 7 节）；身份头信任边界、CSRF、额度原子预留（第 10 节）；Windows wheel 解析参数（第 5 节）。第 4 稿（2026-10-27）按第三轮复审修订：评分块按指标指纹检测变化、来源标签随比分块的可见时间（第 7.1 节）；研究白名单逐文件写依据和锚点（第 7.2 节）；模型请求次数与逐次预留（第 8.1、10.3 节）；G1 检验家族与显著性预算（第 9.1 节）；概念验证用单独环境装两套框架（第 3、5 节）；数字校验覆盖中文数字等写法（第 8.3 节）；阶段 6 按鉴权做法分别验收（第 10.4 节）。第 5 稿（2026-10-27）按第四轮复审修订：一个留出集只有一份显著性预算，新预算只给未评估过的新留出集（第 9.1 节）；G1 选参和留出改在 `football.db` 冻结副本上做，训练历史从 2122 起与实盘一致（第 9.1 节）；`model_calls` 改为独立硬上限（第 8.1、10.3 节）；数字校验改为默认拦截加放行表，补英文整十词、序数、罗马数字（第 8.3 节）。审核通过后，把定下来的规则并入 `docs/stack.md`、`docs/modules.md`、`docs/ml-stack.md`、`AGENTS.md`，本文件只留阶段契约；进度仍只写在 [progress.md](progress.md)。通过后的修改：2026-10-27 阶段 0 经用户同意，第 5 节的 Windows wheel 检查由 `pip download --platform` 改为 `uv pip compile --python-platform`。2026-10-27 阶段 2 用户选定 Milvus Lite 作向量库，替代第 3 节原定的 Chroma；BM25 改用 Milvus 自带的 BM25 函数，不再装 `rank-bm25`（第 2、3、5、7 节已跟着改）。

## 1. 先定的一条线

**大模型不产生概率。** 胜平负、亚盘、比分、大小球的数字只来自现有的 `services` 和模型（写方案时主模型是 `market_implied`、兜底 `dc_market`；2.0.0 起主模型是 `dc_dyn`，`market_implied` 作对照；以后加上 `model_nn`）。Agent 负责理解问题、调用工具、检索资料、比对和解释，并给出每个数字的来源。

理由：

- 仓库已有结论：5 联赛 × 9 赛季、16k 场样本外，自研模型每个联赛、每个赛季都不如赛前市场（`AGENTS.md`、`docs/progress.md`）。让大模型读文字直接给比分，没有证据能比市场好，而且没法存档、评分、做 `promotion_check`。
- 现有的存档、评分、替换规则都建立在「同一模型、同一版本、首次预测」上。Agent 每次输出的文字可能不同，进不了这套规则。

训练分两条线，互不替代：

| 线 | 训练什么 | 用什么 | 产出进哪里 |
|---|---|---|---|
| 预测线 | 表格比赛特征上的神经网络（`model_nn`） | PyTorch | 和其他模型一样：回测 → 门槛 G1 并行存档 → 门槛 G2 替换（第 9.1 节） |
| Agent 线 | 小号开源大模型的 LoRA 微调（工具调用、按格式输出结构化事实）；必要时微调检索向量模型 | Transformers + PEFT + TRL；sentence-transformers | 只在 Agent 里用，不碰 `football.db` 的 `predictions` |

## 2. 分层（对应图 1）

```
应用层      web/ 对话页（阶段 6）· 命令行 python -m agent · MCP（Claude Code / Desktop）
             │
Agent 层    agent/graph.py   LangGraph 状态图：理解 → 调工具 → 提交结构化事实 → 校验 → 渲染
             │                LangChain 只用它的模型接口、Tool、Retriever
     ┌───────┴────────┐
模型层                 工具与数据层
agent/llm.py           agent/tools/   包装 football_prediction.services 的只读函数
 Claude / GPT          agent/kb/      向量知识库（Milvus Lite + bge-m3 + BM25）
 本地开源模型(LoRA)    agent/mcp_server.py  同一套工具以 MCP 暴露
                       football.db / fotmob.db（只读）
```

进程：Agent 和训练只在独立环境 `.venv-ml` 里运行（第 5 节）。现有的 `python -m server`、`live`、定时任务继续用 `.venv`，不 import `agent`、不需要 torch。网页对话时 Agent 是一个单独的本机进程（第 10 节）。

训练代码不在运行链路上：`football_prediction/model_nn/` 训练表格网络；`agent/train/` 训练大模型 LoRA 和向量模型。

## 3. 选型

版本号是 2026-10-26 在本机 `.venv`（Python 3.14.6，Mac M5 16GB）上用 `pip index versions` 查到的最新版，只是候选。实际版本在阶段 0 装进 `.venv-ml`、跑通测试后钉死（第 5 节）。

| 用途 | 候选 | 说明 |
|---|---|---|
| Agent 编排 | LangGraph 1.2.x 或 OpenAI Agents SDK | 不预先排除。阶段 1 之后做概念验证再定（见下） |
| 模型接口、Tool、Retriever | LangChain 1.4.x（`langchain-anthropic`、`langchain-openai`） | 选 Agents SDK 时不用 |
| 状态持久化 | LangGraph 选 `langgraph-checkpoint-sqlite`；Agents SDK 选它自带的会话存储 | 都存在 `agent_data/`，不写进 `football.db`（实盘库只由 Windows 定时任务提交） |
| 向量库 | Milvus Lite 3.2.x（`pymilvus` 3.0.x），本地数据目录（阶段 2 用户选定，替代原定的 Chroma） | 需要按 `available_at` 过滤元数据：Milvus 的标量过滤表达式支持；同一集合里稠密向量和 BM25 稀疏向量两路检索。纯 Python 包，Mac / Windows 同一个 wheel（Windows 未实测）。数据目录有独占锁，同一时间只能一个进程打开 |
| 向量模型 | `BAAI/bge-m3` | 中英混合；本地运行，重建索引不产生费用，知识库内容不外发 |
| 关键词检索 | BM25（Milvus 自带的 BM25 函数），入库前中文先按字二元切分 | 是否换 jieba 由阶段 2 的检索评测决定 |
| 重排（可选） | `BAAI/bge-reranker-v2-m3` | 评测证明有提升才开 |
| 深度学习 | PyTorch 2.14.x | TensorFlow / JAX 已被 `docs/stack.md` 排除 |
| 大模型微调 | Transformers 5.x + PEFT 0.21.x（LoRA）+ TRL 1.16.x（SFT） | P-Tuning / PET 已被 `docs/ml-stack.md` 排除 |
| 向量模型微调 | sentence-transformers 6.x | |
| 工具协议 | MCP 官方 Python SDK（`mcp` 2.x），stdio | |
| 本地模型推理 | Ollama 的 OpenAI 兼容接口 | 能否直接加载我们训出的 LoRA 适配器未验证，阶段 5 先试，不行就合并权重再导入 |

**框架概念验证（阶段 1 结束后，约一个分支、不合并）**：用同样 3 个工具（`list_upcoming`、`get_match`、`kb_search` 的假实现）、同一个云端模型、同一份 20 条问题，分别用 LangGraph 和 OpenAI Agents SDK 实现第 8 节的流程。逐项记录：

- 能否接入 Claude 和本地模型（OpenAI 兼容接口）。
- 结构化事实输出 + 校验失败打回重答，要写多少代码。
- 对话状态持久化、中断后恢复、人工审核点怎么做。
- 离线测试能否用假模型脚本化。
- 工具调用次数、重试次数能否设上限；每次调用的 token 用量能否拿到。

概念验证的环境：两套框架同时装在单独的 `.venv-poc`（gitignore，第 5 节），不装进 `.venv-ml`。定框架后删掉 `.venv-poc`，只把选中的那套写进 `requirements-ml.txt`，重建 `.venv-ml` 并重跑阶段 0 的实测项。

结果写进交接记录，你看过再定框架。第 4、8 节按 LangGraph 写，换成 Agents SDK 时只改 `agent/graph.py`、`agent/llm.py`，工具、知识库、校验、额度模块不变。

模型（下载前都先说明仓库和体积，经你同意再下）：

- 云端：Claude、GPT 二选一或都配，密钥放仓库根目录 `.env`（gitignore），不写进代码和日志。
- 本地：Qwen 系列小号 Instruct 模型（0.5B–1.5B 级），型号在阶段 5 按实测内存再定。

## 4. 目录

```
agent/                      仓库根目录，与 server/ 并列
  __init__.py   __main__.py  python -m agent "周末英超哪场亚盘最稳？"
  config.py                  读 .env：提供方、模型名、额度、库路径
  llm.py                     按配置返回 ChatModel（claude / openai / local）
  graph.py                   状态图、节点、重试上限
  facts.py                   结构化事实的格式、校验、渲染（第 8 节）
  budget.py                  用量记录、额度预留与结算、并发限制（第 10 节）
  prices.toml                各模型单价，你手工维护（第 10.3 节）
  prompts.py                 系统提示词
  serve.py                   本机对话服务与鉴权（阶段 6）
  tools/
    matches.py               比赛、看法、存档、成绩单
    knowledge.py             kb_search
  kb/
    sources.py               白名单资料 → 文本块 + 时点元数据
    index.py                 建索引、增量更新、混合检索
    whitelist.toml           入库资料白名单（第 7.2 节）
  mcp_server.py              python -m agent.mcp_server
  eval/                      检索与回答评测集（jsonl）和评测脚本
  train/
    lora_sft.py  embed_ft.py  traces.py
football_prediction/model_nn/   预测线的 PyTorch 网络（docs/ml-stack.md 已定的落点）
  dataset.py  net.py  train.py  model.py
tests/test_agent_*.py  tests/test_model_nn.py
```

文件按 `docs/modules.md` 的尺度：80–300 行，不建 `utils.py` 一类文件；实际写出来不足 80 行又说不清独立职责的，并进同包文件。

调用方向：

```
web(Next.js 服务端) --HTTP--> server(.venv，只读接口，不变)
web(Next.js 服务端) --HTTP--> agent.serve(.venv-ml，阶段 6)
agent --> football_prediction.services --> 领域包
```

- `agent` 只调 `football_prediction.services` 的公开函数和 `version`，不直接 import 领域包，不写 SQL。需要的新读法（例如按队名查最近几场、读阵容）加到 `services/match_read.py`，和接口共用。
- `football_prediction` 和 `server` 都不 import `agent`（加测试检查）。`server` 现有「只 import `services` / `version`」的规则不变：对话服务是 `agent/serve.py` 单独一个进程，不挂在 `server` 上。

## 5. 依赖和运行环境

**策略：独立环境，现有 `.venv` 一个包都不加。**

| 环境 | 装什么 | 谁用 |
|---|---|---|
| `.venv`（现有） | `requirements.txt`，不变 | `live`、`server`、定时任务、`python -m pytest tests` |
| `.venv-ml`（新增，gitignore） | `requirements.txt` + `requirements-ml.txt`，受 `constraints-ml.txt` 约束 | `agent`、MCP、知识库、`model_nn` 训练、LoRA 微调 |
| `.venv-poc`（只在阶段 1.5，gitignore） | 上一行 + `requirements-poc.txt`（两套编排框架） | 框架概念验证；定框架后删除 |

- 只建一个 ML 环境，不再拆 agent / train 两份：sentence-transformers 依赖 torch，向量检索本身就要 torch，拆开也省不掉。
- `requirements-ml.txt` 写直接依赖并钉 `==`：pymilvus、milvus-lite、sentence-transformers（阶段 0 时是 chromadb、rank-bm25，阶段 2 换掉）、mcp、python-dotenv、torch、transformers、peft、trl、datasets。编排框架这一组（langgraph、langgraph-checkpoint-sqlite、langchain 系，或 openai-agents）在阶段 1.5 定框架后才写进来，之前不装：阶段 1 的工具是普通函数加 MCP，不依赖编排框架。
- 阶段 1.5 的概念验证单独建 `.venv-poc`（gitignore）：`requirements.txt` + `requirements-ml.txt` + `requirements-poc.txt`（两套框架都列、都钉 `==`），同样受 `constraints-ml.txt` 约束。装完先过 `pip check`；两套框架的依赖解析冲突时，各建一个 `.venv-poc-lg` / `.venv-poc-oai`，概念验证的对比记录写明用了哪种。`requirements-poc.txt` 随概念验证分支提交，不合并进 main。
- 定框架后：选中的那组从 `requirements-poc.txt` 移进 `requirements-ml.txt`，删掉 `.venv-poc*`，重建 `.venv-ml`，重跑阶段 0 的实测项（`pip check`、两个环境的 `pytest tests`、`.venv` 的 `pip freeze` 不变、Windows wheel 解析）。
- `constraints-ml.txt` 钉关键的间接依赖：numpy、pandas、scipy、pydantic、fastapi、httpx、tokenizers、safetensors 等。其中与 `requirements.txt` 重叠的包，版本必须和 `.venv` 里实际装的一致；解析冲突时改 ML 包的版本，不改 `requirements.txt`。不用整份 `pip freeze`，它会带进只在 Mac 上有的包。
- 安装：`python -m venv .venv-ml` → `.venv-ml/bin/python -m pip install -r requirements.txt -r requirements-ml.txt -c constraints-ml.txt`（Windows 换 `Scripts`）。
- `football_prediction/model_nn/` 在模块顶层不 import torch：`version.py` 和 `tests/test_versions.py` 在 `.venv` 里读它的 `LAYER_VERSION` 时不能失败。
- 新测试用 `pytest.importorskip`，在 `.venv` 里跳过，在 `.venv-ml` 里执行。

**和 `docs/ml-stack.md` 的冲突怎么解**：那里写「`model_nn` 落地时把 `torch` 写进 `requirements.txt`」。改成：`model_nn` 在 `.venv-ml` 里研究和训练；只有通过门槛 G1（第 9.1 节）、要在实盘并行存档时，才把 torch 加进 `requirements.txt`，并且那次改动要在 Windows 实盘机上装好、跑一轮 `live` 作为验收。阶段 0 同时改 `ml-stack.md` 这一句。

`.gitignore` 加：`.venv-ml/`、`.venv-poc*/`、`.env`、`agent_data/`（知识库索引 `agent_data/kb/`、对话状态、用量库）、`checkpoints/`（权重）。新增 `.env.example`，只列变量名。

**阶段 0 的实测项（都写进交接记录作证据）**：

- Mac：`.venv-ml` 安装成功；`pip check` 无冲突；`import torch, chromadb, transformers, mcp` 成功（编排框架阶段 0 不装；阶段 2 换成 Milvus Lite 后核对的是 `import pymilvus, milvus_lite`）；`torch.backends.mps.is_available()` 的结果。
- `.venv` 没有被改：安装前后 `.venv/bin/python -m pip freeze` 完全一致；`python -m pytest tests` 的通过数与安装前的基线一致（2026-10-27 本机基线：阶段 0 开始时 210 passed，1 skipped，跳过的是缺 httpx 的接口测试；经用户同意给 `.venv` 补装 `requirements.txt` 缺的 httpx 后，基线为 218 passed）。
- `.venv-ml` 里跑 `python -m pytest tests` 同样通过。
- Windows wheel：在 Mac 上对完整的 `.venv-ml`（主依赖 + ML 依赖）做交叉解析，用 uv 按目标平台解析（uv 是本机独立安装的工具，不装进任何环境），目标解释器参数写死：

  ```bash
  uv pip compile requirements.txt requirements-ml.txt -c constraints-ml.txt --python-platform x86_64-pc-windows-msvc --python-version <X.Y> --only-binary :all: --no-header --no-annotate -o /tmp/win<XY>_lock.txt
  ```

  `<X.Y>` / `<XY>` 取 Windows 实盘机 `python -c "import sys, platform; print(sys.version, platform.machine())"` 的结果（要你在那台机器上查，或告诉我）；若那台是 ARM64，`--python-platform` 改为 `aarch64-pc-windows-msvc`。`--only-binary :all:` 下解析成功，就说明每个包都有该平台可装的 wheel；失败时 uv 会报出缺 wheel 的包。记录解析是否成功、哪些包没有 wheel、实际选中的版本，以及与 Mac 上 `.venv-ml` 的差异（只在一边有的包、版本不同的包）。不用 `pip download --platform`：pip 只按目标平台挑 wheel 标签，环境标记仍按本机求值，在 Mac 上会把 Windows 不需要的 uvloop 算进来而解析失败（阶段 0 实测，2026-10-27）。这只证明「有可装的 wheel」，不证明能运行；真正在 Windows 上安装、跑 `pytest tests` 放到需要在那台机器跑 Agent 或 `model_nn` 时，那时再作为验收。
- 显存 / 内存：阶段 0 只记录设备；表格网络和 LoRA 的实际占用分别在阶段 4、5 用小样本实测后记录，之前不作承诺。

## 6. 工具层（阶段 1）

每个工具是一个普通 Python 函数，带类型注解和中文 docstring；LangChain 的 `@tool`（或 Agents SDK 的工具）和 MCP 都包装同一个函数，不写两份。

| 工具 | 做什么 | 来自 |
|---|---|---|
| `list_upcoming(league=None, hours=72)` | 本轮未开赛场次和每场看法（亚盘在前） | `read_current` |
| `get_match(match_id)` | 单场本轮看法 + 首次存档 + 临场存档 + 赛果 | `read_match` |
| `recent_results(league=None, days=3)` | 最近已开球场次的存档与赛果 | `read_recent` |
| `explain_fixture(league, home, away)` | 按最新赔率现算单场判断（不存档） | `explain_inputs` |
| `scorecard()` | 实盘成绩单，含与 `market_avg` 的同场差值 ± SE | `read_scorecard` |
| `resolve_team(text)` | 中文名 / 别名 → 库里队名和联赛 | `TEAM_ALIASES` + 中文名表 |
| `team_news(league, team)` | 阵容、伤停（有 `fotmob.db` 时） | 新增 `services` 读函数 |
| `kb_search(query, k=5, as_of=None, match_id=None, scope="default")` | 知识库混合检索（第 7 节） | `agent/kb` |

返回格式（第 8 节的校验依赖它）：结果是 JSON 可序列化的 dict，由 `agent/tools/` 把 `services` 的返回重新包成「块」。每块带 `scope`、主体键、`kind`、`at`：

| `scope` | 主体键 | 用于 |
|---|---|---|
| `match` | `match_id` | 单场的看法、存档、赛果、评分、阵容 |
| `scorecard` | `model_name` + `model_ver`（另带成绩单的 `generated_at`） | 成绩单里某个模型的汇总行 |
| `kb` | `chunk_id`（另带 `path`、`commit`） | 知识库片段 |

| `kind` | 含义 | `at` |
|---|---|---|
| `current` | 本轮快照里、**尚未开球**的看法 | 快照 `generated_at` |
| `last_pre_kickoff` | 开球后仍留在快照里的最后一轮看法（见下） | 快照 `generated_at` |
| `live_calc` | `explain_fixture` 现算 | 计算时刻；另带赔率获取时间 |
| `first_archive` | 首次存档 | `predictions.generated_at` |
| `near_archive` | 临场存档（`_t1`） | 同上 |
| `score` | 比分 | 实际采用的那个来源的获取时间（第 7.1 节） |
| `grading` | 赛后评分（log loss、命中）；来源标签按调用时刻可见的比分来源现定（第 7.1 节） | `predictions.scored_at` |
| `scorecard` | 成绩单汇总行 | 快照 `generated_at` |
| `team_news` | 阵容、伤停 | `lineups.fetched_at` |
| `kb` | 知识库片段 | 片段的 `available_at` |

开球后的快照看法：`read_match` 在开球后仍返回快照里最后一轮的看法（`services/match_read.py` 的 docstring 写明了这一点），字段名还是 `current`。工具层按调用时刻处理，不按字段名：

- 调用时刻早于开球：标 `current`。
- 调用时刻不早于开球、快照 `generated_at` 早于开球：改标 `last_pre_kickoff`，渲染为「开球前最后一轮看法」，不能说成当前判断。
- 快照 `generated_at` 不早于开球（正常流程不会出现）：整块丢弃，不交给模型。

这条规则在 `agent/tools/` 里实现，不改 `read_match`（网站详情页依赖它现有的行为）；`list_upcoming` 用的 `read_current` 本来就剔除已开球场次。
- 全部只读：库用 `open_readonly`（`mode=ro`）打开。Agent 不能调用 `run_round`、`run_near`、`save_prediction`、爬虫和任何写库函数。
- 中文队名现在只在 `web/src/features/match/teams.ts`。建议导出成一份 JSON，网站和 `resolve_team` 共用；放哪要你定。
- 不加耗时工具（回测、爬虫）。以后要加时，在图里放人工审核点，你同意才跑。

MCP：`python -m agent.mcp_server` 用 stdio 暴露上表工具，Claude Code / Claude Desktop 配上就能直接查实盘看法。只读，本身不调大模型，不需要密钥。

## 7. 向量知识库（阶段 2）

### 7.1 时点

每块带三个时间字段：

- `available_at`：这条信息**实际可以被观测到**的时间，不用文件修改时间。
- `event_time`：信息所说的事件时间（比赛开球时间）；文档类为空。
- `at_source`：`available_at` 取自哪个字段，便于核查。

| 来源 | `available_at` | `event_time` |
|---|---|---|
| 快照里每场看法 | 快照 `generated_at` | 开球 |
| 首次 / 临场存档 | `predictions.generated_at` | 开球 |
| 比分（FotMob） | `fotmob_results.fetched_at`（`INSERT OR IGNORE`，即首次抓到的时间） | 开球 |
| 比分（football-data） | `matches.fetched_at` | 开球 |
| 赛后评分 | 该行 `predictions.scored_at`；`scored_at` 不变而指标被补算时，取索引发现变化的时间（见下） | 开球 |
| 阵容 / 伤停 | `lineups.fetched_at` | 开球 |
| 文档、研究结论 | 该版本的 git 提交时间（`git log -1 --format=%cI -- <路径>`）；未提交的改动不入库 | 空 |

赛果拆成「比分」和「评分」两类块，每个来源各自建块：

- 比分块按来源分开：FotMob 一块、football-data 一块，各用自己的获取时间。不拿另一个来源更早的获取时间给当前比分回填。
- football-data 到达后，FotMob 那块不删，加 `superseded_at` = football-data 块的 `available_at`；`as_of` 晚于它时只返回 football-data 块。两边比分不同时，两块都保留，回答以 football-data 为准并说明 FotMob 曾给出不同比分。
- 评分块对应 `predictions` 的一行，只放指标（`actual_outcome`、`log_loss`、`brier`、`ou25_log_loss`、`score_log_loss`、`ah_line`、`ah_log_loss`、`ah_hit`）和评分时用的比分 `score_used`（建块时按该行 `result_src` 从对应来源取），`available_at` = `scored_at`。来源标签不固定写在评分块里（规则见下）。

评分行在库里有三种改法（`review/store.py`，已核对），只看 `scored_at` 会漏掉后两种：

| 改法 | 改了什么 | `scored_at` |
|---|---|---|
| `reconcile_results`，两边比分不同 | 按 football-data 重评，指标和 `result_src` 都变 | 改成重评时间 |
| `reconcile_results`，两边比分相同 | 只把 `result_src` 从 `fotmob` 改成 `fd` | **不变** |
| `score_predictions` 里的 `_backfill_ah` | 只补 `ah_line` / `ah_log_loss` / `ah_hit` | **不变** |

所以：

- 增量检测用指纹：`result_src`、`scored_at` 和上面全部指标列一起算哈希，存进块的元数据。`--update` 逐行比指纹，任何一项变了都处理，不只比 `scored_at`。
- 指标或 `scored_at` 变了：旧块加 `superseded_at`，再加新块。新块的 `available_at` 取新的 `scored_at`；`scored_at` 没变而指标变了（`_backfill_ah`），取这次 `--update` 发现变化的时间，`at_source` 记 `index_detected`。这个时间晚于真实补算时间，只会晚可见，不会泄漏。
- 只有 `result_src` 变了（比分相同）：指标没变，不加新块，只更新元数据里的 `result_src` 和指纹。
- 来源标签在检索时按 `as_of` 现定，不取评分块里存的值：`as_of` 时可见的比分块里，有 football-data 块且比分等于 `score_used` 就标「football-data」；只有 FotMob 块可见时标「FotMob，待 football-data 核对」；可见的 football-data 比分与 `score_used` 不同（重评之前的那段时间）时标「按 FotMob 比分评分，football-data 比分不同，待重评」。这样比分相同、只改了 `result_src` 的那一行，在 football-data 到达之前和之后都标对，而且不需要知道 `reconcile_results` 实际跑的时刻。取不到 `score_used`（例如 `result_src = fotmob` 但没挂 `fotmob.db`）的行不建评分块。`result_src` 为空的旧行按 `fd` 处理，与 `review/store.py` 的约定一致。
- `--rebuild` 以库里当前值建块，旧块不保留。`_backfill_ah` 补过的行在重建后 `available_at` 回到 `scored_at`，早于实际补算时间；补算只用了 `scored_at` 时已有的存档和比分，所以不带入新信息，可以接受。若要精确记录，需要在 `review/store.py` 里加一列「最后改动时间」，那是 review 层的行为变化，要升版本，本方案不做，留作可选。
- 测试：在合成库上分别模拟三种改法，`--update` 后旧块、新块、`superseded_at`、元数据与预期一致；比分相同只改 `result_src` 的一行，`as_of` 在 football-data 块之前、之后分别检索，标签依次是 FotMob 和 football-data；比分不同时，重评之前的 `as_of` 检索得到「待重评」标签。
存档块只放存档行里就有的数（概率、赔率、市场线和那条线的五种结算、可能比分、大 2.5 概率）和由它们直接算出的选择方。`services.read_match` 给存档补的信心档、历史命中率、亚盘信心档和稳妥线是按现在的规则现算的，存档行里没有；写进块会让 `as_of` 早于这些规则的检索看到后来的规则（阶段 2 评测发现：10-25 的存档块里出现了 1.11.0 才有的稳妥线），所以不入块。快照看法块照常带它们，那是快照生成时的规则。

通用规则：

- 找不到可靠观测时间的资料不入库，不拿别的时间代替。
- 历史赛季的 `matches.fetched_at` 是入库时间，晚于真实赛果时间。这只会让资料「晚可见」，不会泄漏，可以接受。
- 检索按 `as_of` 过滤，只返回 `available_at <= as_of`、且 `superseded_at` 为空或晚于 `as_of` 的块。`as_of` 默认是当前时间；传 `match_id` 时由工具取 `min(当前时间, 该场开球时间)`，不由模型填写，所以问赛前看法时检索不到赛后结果。

### 7.2 白名单

资料来源由 `agent/kb/whitelist.toml`（入版本库，手工维护）逐个文件列出，每条一个完整的相对路径，不含 `*`、`?`、`**`。每条带 `authority`，`research` / `record` 另带说明字段：

| `authority` | 收什么 | 检索时 |
|---|---|---|
| `rule` | `AGENTS.md`、`docs/stack.md`、`docs/modules.md`、`docs/ml-stack.md`、`docs/api.md`、`docs/handover.md` | 默认检索 |
| `status` | `docs/progress.md`、`docs/issues.md`（当前版本） | 默认检索 |
| `research` | 被 `progress.md` 或 `issues.md` 引用过结论的结果文件，逐个列出；每条写 `cited_in`（引用它的文档和小节）和 `superseded`（是否已被后来的结论替代） | 默认检索，跳过 `superseded = true` |
| `record` | 你指定的交接记录，逐个列出；不自动收新的交接记录 | 默认不检索；只在 `scope="handoff"` 时检索，回答里标「交接记录，未必是当前状态」 |

`research` 每条除 `path`、`superseded` 外，逐文件写清依据：

- `cited_in`：引用它的文档和**小节标题**（如 `docs/progress.md#兜底换 dc_market、第二临场档、只用亚盘的对照研究`），不是整份文档。
- `basis`：这一节怎么指到这个文件，三选一：`path`（小节里原样出现完整路径）、`dir`（小节里出现目录，并点名这个文件名或生成它的脚本）、`script`（小节只点名生成脚本，`generated_by` 写脚本路径）。
- `generated_by`：生成这个文件的脚本路径（`basis = path` 时也写，便于核对）。
- `anchors`：至少两个同时出现在该小节和这个文件里的数字原文（如 `−0.00597`），证明小节的结论确实出自这个文件，而不只是路径碰巧相同。

第一版候选（我按 progress / issues 整理，并已用脚本核对过各小节与文件共有的数字；阶段 2 开始前给你过目再定）：

| 文件 | `cited_in` 小节 | `basis` | 共有数字（核对结果） |
|---|---|---|---|
| `_diag/fallback/result.txt` | progress「兜底换 dc_market…（1.12.0）」 | `dir`（点名 `analyze.py` → `result.txt`） | −0.00597、−0.00216 等 |
| `_diag/fallback/tiers.txt` | 同上 | `dir`（点名 `tiers.py` → `tiers.txt`） | 0.378、0.753、0.540 |
| `_diag/ah_only/result.txt` | 同上 | `dir`（点名 `result.txt`） | +0.00032、0.00132 等 |
| `_diag/algo_sweep/result.txt` | issues「football-data 2526 起部分场次的赛前平均亚盘客队水位错误」 | `dir`（「位置」只列目录） | 0.599、0.672 等；只有目录，要你确认 |
| `_diag/explore/ah_clean_recheck.log` | 同上 | `script`（`ah_clean_recheck.py`） | 0.586、0.677 等 |
| `_diag/explore/new_league_tiers.log` | progress「1.9.0」 | `path` | 小节里没有和文件共有的多位小数，要另选锚点或你确认 |
| `_diag/explore/score_shape.log` | progress「1.6.0」 | `path` | 0.0004、0.0007 等（位数少，锚点偏弱） |
| `_diag/explore/reliability.log` | issues「意甲 / 法甲的信心档命中率是三联赛标定的」 | `path`（「位置」写的是 `.py`，正文出现 `.log`） | 小节的百分比与文件格式不同，要另选锚点或你确认 |
| `_diag/explore/ah_baseline.log` | progress「1.10.0」 | `script`（`ah_baseline.py`） | 只有 0.984 一个，不够两个 |
| `_diag/explore/ah_confidence_line.log` | progress「1.11.0」 | `script`（`ah_confidence_line.py`） | 0.725、0.639 等 |
| `_diag/explore/lineup_fotmob_eval.log` | issues「阵容调整系数还没有定」 | `script`（括号里点名 `.log`） | +0.00075、+0.00072 等 |

锚点不足两个的四条（`algo_sweep`、`new_league_tiers`、`reliability`、`ah_baseline`）在你确认前先不收；确认时你给出锚点，或写 `anchors_waived` 并说明理由（例如文件里是百分比、文档里是四舍五入后的写法）。`record` 第一版为空。

白名单的测试（阶段 2 验收）：

- 每条路径存在、是文件、不含 `*` `?` `[`、不在下面的「不收」名单里，也不是目录。
- `research` 每条：`cited_in` 的小节标题在该文档里存在且唯一；按 `basis` 检查——`path` 要求小节里出现完整路径；`dir` 要求小节里出现目录且出现文件名或 `generated_by` 的文件名；`script` 要求小节里出现 `generated_by`。只出现目录、不点名文件或脚本的一律不通过。
- `generated_by` 存在，且脚本里出现这个输出文件名（或你写明它是重定向输出）。
- 每个锚点在小节和文件里都原样出现（把 `−` 和 `-` 视为同一字符）；锚点少于两个且没有 `anchors_waived` 时不通过。
- 文件在 `git log` 里有提交（未提交的不收，与第 7.1 节一致）。

- 不收：`.env*`、`web/.env*`、`servers.txt`、`*.pem`、`*.key`、源代码、`_cache/`、逐场 CSV / JSON、`logs/`。
- 结论冲突时，`rule` / `status` 优先于 `research` / `record`；检索结果带 `authority`，回答时一起标出。
- 比赛类资料（看法、存档、赛果、阵容）不走白名单文件，由 `services` 的读函数从库里取。

### 7.3 检索与评测

- bge-m3 向量 + BM25 两路，各取前 20，倒数排名融合（RRF）取前 k；评测证明有用再加重排。
- 索引在 `agent_data/kb/`（Milvus Lite 数据目录 + `meta.json`），`python -m agent.kb --rebuild` 完整重建，`--update` 只加新块。先手动跑，不接进 `run_daily.bat`。
- 评测集 `agent/eval/retrieval.jsonl`：60–100 条问题，每条带 `as_of` 和应命中的块（人工标注）。比较只用向量、只用 BM25、混合、混合 + 重排的 recall@5 和 MRR；阶段 2 先测基线，目标值看到基线后再定。
- 泄漏用例：`as_of` 早于赛果、早于某份文档提交的问题，结果里出现晚于 `as_of` 的块就算失败。这一项必须是 0。

## 8. Agent 图与结构化事实（阶段 3）

### 8.1 流程

```
START → agent（LLM 绑定工具）──有工具调用──→ tools（记录每次调用的 id 和原始返回）──→ agent
                 │
           提交最终答案（结构化）
                 ↓
              verify（纯 Python）──不通过且 answers<2──→ agent（附上逐条错误）
                 │
         通过 → render → END        第 2 次提交仍不通过 → 降级输出 → END
```

计数口径（`agent/graph.py` 和 `agent/budget.py` 共用，数字可在 `.env` 改，下面是默认值）：

| 计数 | 含义 | 每轮上限 |
|---|---|---|
| `model_calls` | agent 节点每调一次模型就加 1，不论这次返回的是工具调用、答案、超限的工具提议还是格式错误 | **6，独立硬上限** |
| `tool_rounds` | 进入 tools 节点、真正执行工具的次数 | 4 |
| `answers` | 模型提交结构化答案的次数，**含首次** | 2：首次 + verify 打回后重答 1 次 |
| HTTP 请求 | 实际发给提供方的请求，每次都可能计费 | 每次模型调用 ≤ 2（首发 + 1 次重试），每轮 ≤ 12 |

四个计数各自累加、各自判定，`model_calls` 不由另外两个推算。几条边界：

- `tool_rounds` 到 4 之后，模型再提议工具：这次调用已经发生，`model_calls` 照样加 1；工具不执行，图在下一次调用里附上「工具次数已用完，请直接提交答案」。
- 返回既不是工具调用、也不是可解析的答案（格式错误、空回复）：`model_calls` 加 1，不算 `answers`，下一次调用附上格式错误说明。
- 每次调用模型之前先查 `model_calls < 6`，不满足就不再调用，直接降级：只渲染已有工具结果里能核对的事实（第 8.4 节），没有任何工具结果时只回一句「这次没能完成查询」。
- 图里的 `answers<2` 只是重答条件之一；重答还要同时满足 `model_calls < 6`。例如已经 4 轮工具、1 次超限提议、1 次答案（共 6 次）而答案没通过，就直接降级，不再重答。

HTTP 重试由 `agent/llm.py` 自己做，SDK 自带的自动重试设为 0（第 10.3 节说明原因）。

### 8.2 模型提交的格式

模型不直接写带数字的成段文字，而是提交：

```json
{
  "text": "这场市场线是 {f1}，主队赢盘概率 {f2}；首次存档时的市场线是 {f3}。过去已评分的 {f4} 场里，主模型同场差值为 {f5}。",
  "facts": [
    {"id": "f1", "scope": "match", "subject": "ffd82975358cfced", "tool_call_id": "call_2",
     "path": "/blocks/0/asian/line", "value": -0.75, "unit": "line", "kind": "current", "at": "2026-10-26T14:43:07Z"},
    {"id": "f2", "scope": "match", "subject": "ffd82975358cfced", "tool_call_id": "call_2",
     "path": "/blocks/0/asian/cover_prob", "value": 0.534, "unit": "prob", "kind": "current", "at": "2026-10-26T14:43:07Z"},
    {"id": "f3", "scope": "match", "subject": "ffd82975358cfced", "tool_call_id": "call_2",
     "path": "/blocks/1/asian/line", "value": -0.5, "unit": "line", "kind": "first_archive", "at": "2026-10-25T10:07:12Z"},
    {"id": "f4", "scope": "scorecard", "subject": "market_implied@1.0.0", "tool_call_id": "call_3",
     "path": "/blocks/2/n", "value": 57, "unit": "count", "kind": "scorecard", "at": "2026-10-26T14:43:07Z"},
    {"id": "f5", "scope": "scorecard", "subject": "market_implied@1.0.0", "tool_call_id": "call_3",
     "path": "/blocks/2/ll_diff", "value": -0.004, "unit": "ll_diff", "kind": "scorecard", "at": "2026-10-26T14:43:07Z"}
  ]
}
```

（字段路径和数值只是示例，以阶段 1 定下的工具返回结构为准。）每条事实：作用域 `scope`、主体 `subject`（`match` 是 `match_id`，`scorecard` 是 `模型名@版本`，`kb` 是 `chunk_id`）、工具调用 id、工具结果里的字段路径（JSON Pointer）、数值、单位、`kind`（第 6 节的表）、该块的时间。

单位（`facts.py` 里的字段 → 单位对照表）：

| 单位 | 例子 | 比对 |
|---|---|---|
| `prob` | 胜平负、赢盘概率 | 按工具结果的小数位 |
| `odds` | 赔率 | 同上 |
| `line` | 亚盘线、大小球线 | 完全相等 |
| `goals` | 实际进球数 | 完全相等，整数 |
| `score` | 比分 | 完全相等（主、客两个整数） |
| `xg` | 预期进球（FotMob / understat） | 按小数位；不能和 `goals` 互换 |
| `lambda` | 模型给的进球率 λ | 按小数位；不能和 `xg`、`goals` 互换 |
| `count` | 场数、样本量 | 完全相等 |
| `ll` / `ll_diff` / `se` | log loss、同场差值、标准误 | 按小数位 |
| `pp` | 百分点差 | 按小数位 |
| `datetime` | 开球、存档、获取时间 | 完全相等，渲染为北京时间 |
| `kb_number` | 知识库片段里的数字 | 见第 8.3 节第 7 条 |

### 8.3 校验（`agent/facts.py`）

1. `text` 里除了 `{fN}` 占位，不允许出现数字。例外只有从工具结果里原样取来的实体名（如 `Mainz 05`），由校验器对照工具结果放行。日期、时间、比分、进球数、预期进球、场数、差值 ± SE 都要走事实。「数字」不只指阿拉伯数字，校验先做 NFKC 归一（全角 `５` → `5`），再按下面的写法检查，任一命中即不通过：
   - Unicode 里带数值的字符（`unicodedata.numeric` 有值）：阿拉伯数字（含全角、上下标）、带圈数字（`①`）、分数字符（`½`）、罗马数字字符（`Ⅱ`），以及中文数字和大写数字（零〇一二两三四五六七八九十百千万亿、壹贰叁肆伍陆柒捌玖拾佰仟）。本机核对过：`５` `①` `½` `Ⅱ` `三` `两` `十` `零` `壹` 都有数值；`半` `第` 没有，单独处理。
   - 「半」：除放行表里的词（如「上半场」「下半场」「半场」）外一律算数字（「半球」「一球半」「半个」「半数」）。
   - 序数和排名：「第」「前」「后」「头」「近」「连」紧跟数字字符的写法（「第十三」「排名第三」「前四」「近五场」「三连胜」）——这些已被上一条的数字字符拦下，这里列出是为了测试覆盖。
   - 百分比、成数、比分的文字写法：「百分之…」「…成」「…比…」「…胜…负」，同样已被数字字符拦下，单列为测试项。
   - 英文数词，按词边界、不区分大小写，用一份写死的词表：基数 `zero`…`nineteen`、整十 `twenty` `thirty` `forty` `fifty` `sixty` `seventy` `eighty` `ninety`、`hundred` `thousand` `million` `billion` `dozen`；序数 `first`…`twelfth`、`thirteenth`…`nineteenth`、`twentieth` `thirtieth` 等整十序数、`hundredth`；分数和倍数 `half` `halves` `quarter` `third` `once` `twice` `double` `triple`；以及连字符组合（`twenty-one`、`thirty-third`）。
   - ASCII 罗马数字：两个及以上字符的 `[IVXLC]+` 整词（`II`、`IV`、`XI`）；单个 `I` / `V` / `X` 不拦，避免误伤英文。
   - 中文盘口名（「平手」「平半」「半一」「一球」「球半」等）：项目规定亚盘只用数字线，这些词同样要走事实。

   **判定方式是「默认拦、放行表放」**：任何数字字符、「半」、英文数词都算数字，只有 `facts.py` 里写死的固定词放行表能放过（「一定」「一般」「一起」「一直」「一致」「一些」「一下」「统一」「唯一」「万一」「之一」「一样」「上半场」「下半场」「半场」等，每个词带测试）。不按「数字 + 量词」去猜，放行表外的一律不通过，宁可多打回一次。放行表的实际打回率在阶段 3 评测里统计，按结果增补，增补的每个词都要有测试。
   必测用例：
   - 被打回：`５场`、`三场`、`两成`、`百分之五十三`、`二比一`、`半球`、`一球半`、`平半`、`第十三`、`排名第三`、`前四`、`三连胜`、`十几场`、`fifty-three percent`、`thirty`、`Thirty-Third`、`twice`、`½`、`①`、`Ⅱ`、`IV`。
   - 不被打回：「一定」「统一口径」「唯一」「上半场」，以及单独的英文 `I`。
   - 工具结果里的队名 `Mainz 05` 放行；模型自己写的 `Mainz 05`（本轮工具结果里没有这场）不放行。
2. 占位和事实一一对应：每个占位都有事实，每条事实都被用到。
3. `tool_call_id` 必须是本轮 tools 节点真实记录过的调用。
4. 按 `path` 取到的值必须存在，并与 `value` 一致，容差按上面的单位表。
5. `path` 必须落在某一块里；该块的 `scope`、主体键、`kind`、`at` 必须分别等于事实的 `scope`、`subject`、`kind`、`at`。这一条挡住「拿 A 场的数说 B 场」「拿 A 模型的成绩说 B 模型」和「把首次存档说成当前看法」。
6. 字段在对照表里登记的单位必须等于事实的 `unit`；对照表里没有的字段一律不通过（例如 `xg` 字段只能是 `xg`，不能报成 `goals`）。
7. `scope = kb` 的事实：`path` 指向片段正文，另带 `quote`（片段里的原文短句）。校验 `quote` 在该片段正文里原样出现，`value` 是 `quote` 里出现的数字；单位一律 `kb_number`，渲染时原样照抄 `quote` 里的写法，不换算，后面标「项目文档 <路径>，<提交日期>」或「研究结论 <路径>」。片段 `authority = record` 的数字另标「交接记录，未必是当前状态」。
8. `text` 里出现的队名，必须属于至少一条 `scope = match` 事实的那场比赛（对照该块的主客队）。挡住「A 场的数配 B 场的队名」。

### 8.4 渲染

- 通过后，由 Python 把每个占位替换成**工具结果里的值**（不用模型写的 `value`），按现有写法格式化（盘口线用 `ah_text` 的写法，概率百分比，时间转北京时间），并在后面按 `kind` 自动加来源标签，例如「主-0.75（本轮看法，10-26 22:43 北京时间）」「主-0.75（开球前最后一轮看法，10-26 22:43）」「53%（首次存档，10-25 18:07）」「2-1（比分，FotMob，待 football-data 核对）」「1.42（预期进球，FotMob）」。
- 用完重试仍不通过：不输出模型的成段文字，只输出通过校验的事实（Python 渲染成表格）和一句「部分内容没有通过核对，已省略」。不展示未核实的数字。
- 校验管得住数字的来源，管不住措辞本身（例如在首次存档的数字旁写「现在」）。来源标签由 Python 加在每个数字上，可以减轻这类问题；评测集另统计措辞与 `kind` 不符的比例，作为阶段 3 的观察项。

### 8.5 其他

- 模型层：`.env` 里 `AGENT_PROVIDER=claude|openai|local`、`AGENT_MODEL=...`，`llm.py` 返回 ChatModel，图不知道背后是哪家。每次调用的用量交给 `budget.py`（第 10 节）。
- 对话状态存在 `agent_data/state.db`，同一 `thread_id` 可以追问。
- 测试全部离线：假模型按脚本吐出工具调用和结构化答案；内存 SQLite + `tests/conftest.py` 的合成比赛；临时目录里的 Milvus Lite。必测：编造数字、错比赛、错模型、错时点、错单位（含 `xg` 报成 `goals`）、把存档当当前看法、开球后把快照看法标成 `current`、知识库 `quote` 不在原文里、队名与比赛不符，各自被 verify 打回；占位与事实不一一对应时打回；第 8.3 节第 1 条列出的数字写法用例；第 8.1 节计数表的每个上限都能单独触发（假模型一直要工具：执行 4 轮工具后共调用 6 次即停，没有第 7 次；超限提议和格式错误都计入 `model_calls`；第 2 次提交不通过即降级；6 次用完时的答案不通过也直接降级）；降级输出不含未核实数字；工具只读（跑完库的 md5 不变）；`football_prediction`、`server` 不 import `agent`。

## 9. 训练

### 9.1 预测线：`model_nn`（阶段 4，PyTorch）

规则沿用 `docs/ml-stack.md`：`match_date < cutoff`、`2526` 留出、种子写进配置、`fit(conn, league, cutoff_date)`、训练不调 `save_prediction`、指标用 `validation/backtest.py`。

**覆盖范围：阶段 4 先做五联赛（E0 / D1 / SP1 / I1 / F1），过 G1 之前不进实盘。**

**训练历史与实盘对齐（G1 的前提）**：实盘模型在 `football.db` 上拟合，历史从 2122 起（本机核对：五联赛都是 2122–2627，E0 的 `match_xg` 也从 2122 起）。Elo 这类递推特征的状态、球队统计的窗口、可用样本量都取决于从哪一季开始，所以 G1 检验的必须就是将来上线的那一套。做法：

- **选参（2425）和 G1 留出（2526）都在 `football.db` 上做，不用 `research.db`。** 训练历史一律从 2122 起，和实盘一样；评估 2425 时用 2122–2324，评估 2526 时用 2122–2425，按月滚动。
- 训练窗口规则（从 2122 起全量，还是只取最近 N 季）、联赛是合并训练还是分联赛训练、特征来源（xG 用 `match_xg`，understat 缺的由 FotMob 补，与实盘一致）都是配置的一部分，写进 `prereg.md`，上线时原样使用。上线后每月重拟合也按同一条窗口规则。
- `football.db` 每天被实盘改写。G1 用一份冻结的副本：用 SQLite 的 backup 接口（不是直接拷文件，避免拷到写了一半的库）复制到 `checkpoints/g1/football_<日期>.db`（gitignore），只读打开，md5 写进 `prereg.md`。选参和留出都用这同一份副本。
- `research.db`（9394 起）只用于探索，例如判断更长历史是否有帮助。它的结论不能作为 G1 证据，在它上面选出的配置也要回到 `football.db` 的 2425 上重新确认。两个库的 2526 是同一批比赛，所以在 `research.db` 上同样不能评估 2526。按 `AGENTS.md`，老赛季不能加进 `football.db`，因此「更长历史更好」这个结论即使成立也上不了线。
- 本机目前没有 `research.db`。只有要做上面的探索时，才用 `_diag/expand/build_research_db.py` 从 `_cache/fd_research` 重建；G1 不依赖它。
- 另外六个实盘联赛（E1 / N1 / P1 / SC0 / B1 / T1）同样在 `football.db` 上，也从 2122 起，没有 understat xG。它们的检验见下面的 T3、T4。
- 特征分两套：`full`（含 xG，只能用于五联赛，`football.db` 里从 2122 起有 xG）和 `no_xg`（不含 xG，可以用于全部联赛）。另外六个联赛没有历史 xG，只能用 `no_xg`。
- 变体：A 无赔率（对照 `dc_market`）；B 带赔率，输入加去水概率和市场隐含 λ，学市场之外的残差（对照 `market_implied`）。
- 输出主客队进球率 λ（softplus），套现有的 DC 比分矩阵，交给 `derive_markets` 得到胜平负、亚盘、大小球。损失是实际比分在矩阵上的负对数似然。

**训练样本按场时点构造：**

- 每一场样本（不论用于训练、验证还是评估）的特征，都按**这一场自己**的 cutoff 生成：只用 `match_date < 该场 match_date` 的比赛，与 `features/builder.py` 的 `build_features(conn, league, cutoff_date=该场日期, ...)` 同一口径。不允许先用整个训练窗口算好球队统计、再贴回每一场。
- 带赔率的变体 B 只用该场的赛前平均赔率（`Avg*`），不用收盘赔率；Elo 等递推特征取该场开球前的状态。
- 同日比赛互不可见（cutoff 不含当天），与实盘一致。
- 特征表不写进任何比赛库，单独缓存在 `checkpoints/nn_features/`（gitignore，可重建），每行带 `cutoff_date` 和 `features_ver`。
- 测试：在合成比赛上删掉某场之后的全部比赛，重算该场特征，结果必须完全相同；任一特征依赖了该场及之后的比赛就失败。

**比较口径：**

- 同场：只比较候选和基准都有预测的场次（B 和 `market_implied` 只在有赛前赔率的场次比）。
- 同一时间切分：候选和基准都按 `run_backtest(refit_freq="monthly")` 的同一组 cutoff 拟合，每个月只用该月第一天之前的比赛。`market_implied` 不拟合，用同一行的赛前平均赔率，不用收盘赔率。
- 选参：A / B 两个变体、`full` / `no_xg` 两套特征、各种超参，都只在 2425 上逐月评估、互相比较。早停用每个 cutoff 之前最后一段时间（训练集内部按时间切出），不用被评估的月份。
- 指标：1X2 log loss、Brier、比分 log loss、亚盘五种结算 log loss，都用 `paired_compare` 给同场差值 ± SE。

**预注册（在跑 2526 之前写好并提交）：**

选参结束后，新建 `_diag/model_nn/prereg.md` 并单独提交一次，写死下面几项，提交号记进 progress。2526 只能在这次提交之后跑，而且只跑一次：

- 主候选：每个变体只留一个配置（特征集、结构、超参、训练轮数、种子），由 2425 的结果选出。最多两个主候选：B（对 `market_implied`）和 A（对 `dc_market`）。
- 主指标：1X2 log loss 的同场差值。Brier、比分 log loss、亚盘 log loss 只作参考，不参与 G1 判定。
- 聚合：每个联赛组（五联赛、六联赛）各自合并成一个总体计算同场差值和 SE，不按单个联赛分别判定。
- 检验家族：G1 的全部确认性检验算**一个家族**，同一次在 `prereg.md` 里登记。成员最多 4 个，每个是「联赛组 × 变体」：

  | 检验 | 联赛组 / 数据 | 候选 | 对照 |
  |---|---|---|---|
  | T1 | 五联赛，`football.db` 2526 | B 的主配置 | `market_implied` |
  | T2 | 五联赛，`football.db` 2526 | A 的主配置 | `dc_market` |
  | T3 | 六联赛，`football.db` 2526 | B 的 `no_xg` 配置 | `market_implied` |
  | T4 | 六联赛，`football.db` 2526 | A 的 `no_xg` 配置 | `dc_market` |

  六联赛只测这两个候选，不另选。B / A 的主配置本身是 `no_xg` 时，T3 / T4 用同一个配置；是 `full` 时，另在五联赛 2425 上选出同一变体最好的 `no_xg` 配置，和主配置同时冻结。按第 12 节第 7 项只做五联赛时，家族只有 T1、T2。
- 显著性预算：家族合计单侧 α = 2.28%，也就是项目现有单次检验「差值 + 2×SE < 0」的水平。按登记的检验数 m 做 Bonferroni，每个检验要求（差值 + z×SE）< 0：

  | m | 每个检验的 α | z |
  |---|---|---|
  | 1 | 2.28% | 2.00 |
  | 2 | 1.14% | 2.28 |
  | 3 | 0.76% | 2.43 |
  | 4 | 0.57% | 2.54 |

  （z 由 `scipy.stats.norm.isf(0.02275 / m)` 算出，向上取到两位小数。）m 按登记数算：登记了 4 个、后来有的没跑，m 仍是 4，不因少跑而放宽。
- **一个留出集只有一份预算**。2526 的 2.28% 在 `prereg.md` 提交时一次分完，之后在 2526 上不再登记任何确认性检验：不另开家族，不追加成员，也不把没跑的成员的 α 挪给别的检验。登记时只选五联赛（m = 2）的话，六联赛以后就不能再用 2526，只能等新留出集。所以推荐一开始就把 T1–T4 全部登记（m = 4）。
- 新留出集才有新预算：之前没看过的数据（例如 `football.db` 2627 在某个预注册日期之后完赛的部分，或 2728），另写一份 `prereg`，在任何评估之前提交，另用 2.28%。前提是 `model_nn` 从没在这段数据上评估过。为此每次评估都在 `_diag/model_nn/eval_log.md` 追加一行：数据库快照、日期范围、配置、提交号。登记新留出集时，用这份日志证明它和以往的评估范围不重叠。
- 每个留出集的结论只在它自己那里成立，不和别的留出集合并、不挑结果好的那次报。progress 里记下 G1 一共用过几个留出集、每个的结果，你决定 G2 时能看到全部尝试。
- 每个检验单独判定、单独生效：T1 通过只让 B 在五联赛并行存档，不连带 T3。
- 按联赛、按赛季的结果照常列出，只作描述，不用来挑联赛。

2526 跑过之后，不再根据它的结果改任何东西。想按联赛筛选，或想换配置，都必须按上面的规则用新留出集，先预注册、只跑一次。

**另外六个联赛：**

它们在 `football.db` 里的 2526 还没被 `model_nn` 用过。步骤：

1. 只测上表 T3、T4 的两个候选（`no_xg`，结构、超参、训练轮数都在五联赛 2425 上定好并冻结），不在六联赛上重选。
2. 在同一份冻结副本上，以 2122–2425 按月滚动拟合（只拟合网络权重，不调超参），2526 作留出，只跑一次。训练历史同样从 2122 起，与实盘一致。
3. 六联赛合并成一个总体判定，z 用上表按家族 m 取的值。不通过就不进实盘，不再按单个联赛挑选。

**两个门槛，分开判定：**

| 门槛 | 判定 | 通过后 |
|---|---|---|
| G1 实盘并行存档 | `prereg.md` 登记的检验（T1–T4 中登记了的），各自在只跑一次的留出集上按家族的 z 通过；每个检验只对它那一组联赛、那一个变体生效 | 升 `LAYER_VERSION` 和 `SYSTEM_VERSION`，把 torch 加进 `requirements.txt`，Windows 实盘机装好后跑一轮 `live`；只存档，不进报告 |
| G2 替换 | B 替主模型：只走现有 `promotion_check`（实盘同批 ≥ 1000 场、差值 + 2×SE < 0）。A 替兜底：照 1.12.0 换 `dc_market` 的做法，11 联赛多赛季月度重拟合回测显著更好，并经你确认 | 改 `PRIMARY_MODEL` / `FALLBACK_MODEL`，按「改一层时」升版本 |

- 预期：按已有结论，A 大概率不如 `dc_market`，B 大概率与市场无显著差异，很可能两个都过不了 G1。结果不论好坏都写进 `progress.md`。
- 只研究、未过 G1 时：`model_nn` 登记 `LAYER_VERSION`（`version.py`、`tests/test_versions.py`），不升 `SYSTEM_VERSION`。

### 9.2 Agent 线：LoRA 微调（阶段 5）

目的：让本地小模型能正确调用工具、按第 8 节的格式提交结构化事实，不依赖云端模型。不教它足球知识，也不让它出概率。

- 训练数据（`agent/train/traces.py`）：
  - 用真实联赛、队名、日期按模板造问题，配上正确的工具调用和通过 verify 的结构化答案。
  - 阶段 3 用云端模型跑出、并通过 verify 的真实对话记录。用云端模型的输出训练别的模型前，先核对对应服务条款是否允许（未核实）。
  - 按比赛日期切分训练 / 验证，同一场比赛不同时出现在两边。
- 方法：Transformers + PEFT LoRA + TRL `SFTTrainer`；有 CUDA 时可用 QLoRA（bitsandbytes 在 MPS 上不可靠）。没有偏好标签，先不做 DPO。
- 评测（`agent/eval/agent.jsonl`）：工具选对率、参数正确率、verify 一次通过率、降级率；对照未微调的同一模型和云端模型。
- 权重：适配器放 `checkpoints/agent_lora/<日期>/`，不进版本库。

向量模型微调：只有阶段 2 的检索评测显示 recall 不够、且错误集中在本项目术语（盘口线写法、模型名、队名）时才做。用 sentence-transformers 的对比学习，训练对是「问题 → 正确块」，按日期留出一部分评测。

## 10. 应用层：访问与额度（阶段 6）

### 10.1 网络

现状：接口 `run_api.bat` 只听 127.0.0.1:8000；网站 `run_site.bat` 只听本机 Tailscale IPv4 的 3000 端口，浏览器从不直接访问接口。群友的浏览器访问不到 127.0.0.1 上的任何服务。

方案：**同源转发，Agent 服务不对外。**

```
群友浏览器 --Tailscale--> Next.js :3000（同源路由，只做转发）--127.0.0.1--> agent.serve（.venv-ml）
```

- `agent/serve.py` 只听 127.0.0.1（端口另定，避开 8000），没有新的防火墙规则。
- Next.js 只为对话加一个服务端路由（流式转发），其余页面取数照旧走服务端组件。这要改 `docs/modules.md`「前端不建 `app/api` 或代理」：改成只允许这一个对话转发路由，不转发只读接口。
- 不选「把 API 开到 Tailscale」：要给接口加防火墙规则和鉴权，并且两个接口进程都要对外，暴露面更大。

### 10.2 鉴权

站点现在没有账号服务，所以对话需要单独的最小鉴权，两种做法二选一（要你定）。

**做法 A：邀请码（不改现有部署）**

- 你给每个群友一个码，`agent_data/access.db` 只存码的哈希和对应用户 id。
- Next.js 校验通过后发会话 Cookie：值是随机会话 id（库里只存哈希），`HttpOnly`、`SameSite=Strict`、`Path=/`，有过期时间，可在库里吊销。
- 站点走 Tailscale 的 http，Cookie 带不了 `Secure` 标志；传输安全依赖 Tailscale 自身的加密和访问控制。

**做法 B：Tailscale 身份头（要改部署）**

- 身份头只能来自可信代理：由 `tailscale serve` 把 tailnet 上的请求转发给只听 127.0.0.1 的 Next.js，并由它注入访问者身份头。这和现在 `run_site.bat` 直接监听 Tailscale IPv4 的部署不同：选 B 就要把 Next.js 改成只听 127.0.0.1，由 `tailscale serve` 对外，`run_site.bat` 和 `setup_site.ps1`（防火墙规则）一起改。
- 只在请求来自 127.0.0.1（即来自 `tailscale serve`）时才读身份头；直接连 Next.js 的请求一律不认身份头。
- 本机的其他进程也能连 127.0.0.1 并伪造身份头。这台是单用户的实盘机，可以接受，但要写进文档。
- 未验证，选 B 之前先实测：`tailscale serve` 会不会清掉客户端自带的同名头；通过节点共享访问的外部账号能否拿到身份头。任何一项不成立就退回做法 A。

**两种做法共同的规则**

- Next.js 转发给 `agent.serve` 时带一个服务令牌（环境变量，不进前端代码）和已认证的用户 id；`agent.serve` 没有令牌或令牌不对一律拒绝，并且不从浏览器请求里读用户 id。
- 对话是会花钱的 POST，按跨站请求伪造（CSRF）来防：
  - 校验 `Origin` 必须等于站点自己的地址（`SITE_URL`）；没有 `Origin` 的请求拒绝。
  - 校验 `Host` 是预期的站点地址，防止换域名指向本机。
  - 只接受 `Content-Type: application/json`，跨站发这种请求浏览器必须先做预检，站点不回应跨域。
  - 每个会话另发一个 CSRF 令牌，放在页面里，请求头带回来校验（A 绑定会话 id，B 绑定身份头里的用户，服务端签名、有过期时间）。做法 B 没有 Cookie，但身份头是代理自动加的，恶意页面诱导浏览器发请求时同样带身份，所以 B 也要做这一条。
- 对话路由不支持 GET，也不接受表单格式。

### 10.3 额度

按**金额**算，不按 token 数：

- `agent_data/usage.db` 记每次模型调用：用户、对话、提供方、模型、输入 / 输出 / 缓存 token、按价格表算出的金额、时间。重启后保留。
- 价格表 `agent/prices.toml` 由你手工维护（每百万 token 的单价，带生效日期）。价格表里没有的模型拒绝调用。本地模型记 token、金额为 0。
- 三道上限（金额由你定，`.env` 里配）：每人每日、全站每日、全站每月；「日」按北京时间切。
- 预留再结算：每次 HTTP 请求前按「输入 token 估计 + `max_tokens` 上限」算出最高金额并预留，余额不够就拒绝；调用后按实际用量结算，退回多余部分。
- 预留必须是原子的：在 `usage.db` 里用一个 SQLite `BEGIN IMMEDIATE` 事务完成「算出三道上限各自的已结算 + 未结算预留 → 比较 → 写入预留」，提交后才发请求。`BEGIN IMMEDIATE` 一开始就拿写锁，两个请求不会同时通过检查。结算同样在一个事务里改写这条预留。不在内存里做计数。
- 进程崩溃留下的预留：过期时间设为单轮总超时再加余量，过期前一直计入已用。过期后释放；如果之后这次调用的实际用量又回来了，照样记账（可能让当日略超上限，会在用量库里留下记录）。
- 并发计数（每人 1 个、全站上限）也放在同一个库、同一类事务里，不放内存，重启后先清掉过期的占用。
- 单轮上限按第 8.1 节的计数表：`model_calls` ≤ 6（独立计数，超限的工具提议和格式错误都算）、`tool_rounds` ≤ 4、`answers` ≤ 2（含首次）、HTTP 请求 ≤ 12，另有单次 `max_tokens` 和单轮总超时。`budget.py` 在每次预留时自己检查 `model_calls` 和 HTTP 请求数，不依赖图的计数，两边任一到上限就拒绝。
- **预留和记账的单位是每一次 HTTP 请求**，不是每轮、也不是每次模型调用：
  - 发请求前按「这次的输入 token 估计 + `max_tokens`」单独预留一笔，三道上限都够才发。
  - 收到带用量的响应：按实际用量结算这笔，退回多余部分。
  - 明确没有生成内容的失败（连接被拒、请求未发出、提供方返回 4xx / 429 且没有用量字段）：这笔按 0 结算，记录失败原因。
  - 超时、流式中途断开等不确定是否计费的情况：这笔按预留的全额记为 `usage_unknown`，不退。提供方对这类请求怎么计费没有核实，按最坏情况算。
  - 重试前重新预留一笔；预留失败就不重试，本轮按降级处理。
- SDK 自带的自动重试关掉（`max_retries=0`）：SDK 内部重试不经过 `budget.py`，没法逐次预留。重试由 `agent/llm.py` 做，最多 1 次，只对超时、429、5xx 重试。
- 所以一轮最坏花费 = 12 × 单次最高预留金额，在发第一笔请求前就有上限；每人每日上限至少要能容纳这一轮，否则这轮第一笔就会被拒。
- 并发：每人同时只能有 1 个进行中的对话；全站并发数设上限，超过直接返回 429，不排队。
- 兜底：建议你在模型提供方的控制台另设消费上限。本地额度是第一道，控制台是最后一道。

### 10.4 阶段 6 验收

按第 12 节第 5 项最终选的鉴权做法，只跑「共同」和对应那一组；没选的那组不跑，也不算通过条件。

**共同（两种做法都要过）**

- 没有服务令牌或令牌不对，直接打 `agent.serve` 被拒；请求体里自带的用户 id 被忽略。
- 在 Tailscale 地址上扫不到 `agent.serve` 的端口。
- 余额不足以预留时，调用前就拒绝，用量库里没有这次调用。
- 同一用户发第二个并发对话得到 429；全站并发满时得到 429。
- 重启 `agent.serve` 后当日已用金额不变。
- verify 打回的重答和 HTTP 重试都计入金额：用假提供方让每次请求都超时，一轮最多发出 12 个 HTTP 请求，用量库里正好 12 笔预留，全部记为 `usage_unknown`；让首发返回 429、重试成功，用量库里两笔，第一笔为 0。
- 假模型一直要工具：执行 4 轮工具，第 5、6 次调用的工具提议不执行，第 6 次之后不再调用模型，用量库里正好 6 次模型调用的预留（不含 HTTP 重试）；第 2 次提交仍不通过时降级，没有第 3 次提交。
- 达到每日上限后，次日北京时间 0 点恢复；达到每月上限后整月拒绝。
- 原子预留：把上限设成刚好够一次预留，用多个线程 / 进程同时发请求，只有一个通过，用量库里只有一条预留；重复多次结果相同。
- CSRF：`Origin` 是别的站点、缺 `Origin`、`Host` 不对、不是 JSON、缺 CSRF 令牌、用 GET 或表单格式，各自被拒，且没有产生预留。

**做法 A（邀请码 + 会话 Cookie）**

- 没有会话 Cookie 返回 401；邀请码错误不发 Cookie。
- 吊销后的会话 Cookie 立即失效；过期的 Cookie 被拒。
- Cookie 带 `HttpOnly`、`SameSite=Strict`、`Path=/` 和过期时间（检查响应头）；库里只有会话 id 和邀请码的哈希。
- CSRF 令牌属于别的会话时被拒。

**做法 B（Tailscale 身份头）**

- Next.js 只听 127.0.0.1：从 tailnet 直接连本机 Tailscale IPv4 的 3000 端口连不上；`setup_site.ps1` 里放行 3000 端口的旧防火墙规则已撤掉。
- 经 `tailscale serve` 访问时，请求带上访问者身份；拿不到身份（例如不在允许名单里的节点，或通过节点共享访问的外部账号，按实测结果）返回 401。
- 客户端经 `tailscale serve` 自带伪造的同名身份头：不会被当成身份，以代理注入的为准（实测记录，抓 Next.js 收到的请求头作证据）。
- 本机其他进程直接连 127.0.0.1 带伪造身份头：按第 10.2 节可以接受，写进文档；验收只确认 Next.js 只认 127.0.0.1 来源，其他来源带身份头一律 401。
- CSRF 令牌属于别的用户时被拒；身份头换了用户，旧令牌失效。
- 上面任一实测项不成立：按第 10.2 节退回做法 A，改跑 A 组。

命令行 `python -m agent` 和 MCP 只在本机用，也记用量，额度单独一档（你的个人额度）。

## 11. 阶段与验收

| 阶段 | 内容 | 验收（证据写进交接记录） |
|---|---|---|
| 0 | `.venv-ml`、`requirements-ml.txt`、`constraints-ml.txt`、`.gitignore`、`.env.example`；本方案定下的规则并入规范文档（含 `ml-stack.md` 的 torch 一句、`modules.md` 的 `agent/` 位置） | 第 5 节实测项全部有结果：`.venv` 的 `pip freeze` 前后一致；两个环境 `pytest tests` 都通过；`pip check` 无冲突；Windows wheel 解析结果 |
| 1 | 工具层 + MCP；`services` 新增的读函数 | 工具单测；每块返回都有 `scope` / 主体键 / `kind` / `at`；开球后的快照看法标成 `last_pre_kickoff`；跑完库 md5 不变；Claude Code 通过 MCP 能列出本轮场次 |
| 1.5 | 框架概念验证（第 3 节） | `.venv-poc` 装好两套框架、`pip check` 无冲突（或分成两个环境的记录）；两种框架逐项对比记录，你定框架；定框架后 `.venv-ml` 重建、阶段 0 实测项重跑 |
| 2 | 知识库 | 能重建、能增量；第 7.2 节白名单测试通过（逐文件、`basis` / `generated_by` / 锚点）；白名单之外的文件不入库；比分按来源分块；评分块按指纹检测三种改法，来源标签随 `as_of` 正确（第 7.1 节的测试）；泄漏用例 0；四种检索方式的 recall@5 / MRR 基线 |
| 3 | Agent 图 + 结构化事实 + 命令行 | 第 8.5 节的离线测试全过（含第 8.3 节第 1 条的数字写法用例、第 8.1 节的计数上限）；真实模型在评测集上：verify 一次通过率、降级率、措辞与 `kind` 不符率有数字 |
| 4 | `model_nn` 研究 | `football.db` 冻结副本及其 md5；训练历史从 2122 起、窗口规则与实盘一致；按场时点构造特征的测试通过；2425 选参结果；`prereg.md`（检验家族 T1–T4 中登记的成员、m、z、训练窗口规则、副本 md5）的提交号早于任何 2526 评估；`eval_log.md` 记下每次评估的范围；每个检验只跑一次的结果（合并判定，按联赛 / 赛季只作描述）写进 progress；G1 判定结果 |
| 5 | LoRA 微调 | 微调前后工具选对率、verify 一次通过率、降级率对比；实测内存占用 |
| 6 | 对话服务 + 网页转发 + 鉴权 + 额度 | 第 10.4 节「共同」和所选做法那一组全部通过；选 B 时 Tailscale 实测记录在先，不成立就改走 A |

顺序：0 → 1 → 1.5 → 2 → 3 是一条线，做完就有可用的 Agent。4 只依赖阶段 0，可以和 1–3 穿插。5 要用阶段 3 的对话记录。6 最后做。每个阶段结束写交接记录；阶段改变「已完成」或「尚未写代码」时更新 `progress.md`。

## 12. 要你决定的事

1. 环境：按第 5 节建独立 `.venv-ml`、现有 `.venv` 不动，`model_nn` 过 G1 才把 torch 加进 `requirements.txt`（推荐）。
2. 默认云端模型：Claude、GPT，还是先只用本地模型；谁提供密钥。
3. 额度：每人每日、全站每日、全站每月三个金额，以及全站并发上限。
4. Windows 实盘机：Python 版本；有没有 NVIDIA 显卡、显存多大。没有显卡时训练都在 Mac 上跑。
5. 网站对话：做不做。做的话，同意改 `modules.md` 只允许一个对话转发路由；鉴权用邀请码还是 Tailscale 身份。
6. 中文队名表放哪，网站和 Agent 共用。
7. G1 的判据是否接受：
   - 选参和留出都在 `football.db` 冻结副本上做，训练历史从 2122 起，与实盘一致；
   - 按联赛组合并，1X2 log loss 为主指标；
   - 2526 只有一份 2.28% 的预算，一次登记分完。推荐一开始就登记 T1–T4（m = 4，每个检验 2.54×SE）。只登记五联赛（m = 2，2.28×SE）的话，六联赛以后要等新的留出集。
8. 下载：bge-m3、重排模型、Qwen 小模型都要从 Hugging Face 下载，每次下载前我会说明仓库和体积。

框架（LangGraph 还是 OpenAI Agents SDK）不用现在定，阶段 1.5 的对比结果出来后再定。

另外：`大模型项目/` 在这台 Mac 上不存在，本方案不依赖它。Python 3.14、Windows wheel、内存 / 显存占用都还没实测，分别在阶段 0、4、5 作为验收证据补上。
