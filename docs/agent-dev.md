# Agent 与训练模块开发文档

按阶段开发 `agent/`（Agent、工具、知识库、对话服务）和 `football_prediction/model_nn/`（PyTorch 预测网络）。每个阶段做完、验证通过、你验收后，才进入下一阶段。

## 0. 三份文档怎么分工

| 文档 | 写什么 | 什么时候改 |
|---|---|---|
| [agent-plan.md](agent-plan.md) | 设计与理由（第 5 稿，2026-10-27 审核通过）。本文件用「方案 §x」引用它 | 设计要变时先改它，经你同意 |
| 本文件 | 怎么做：每个阶段的入口条件、任务、验证命令、出口证据 | 做法要变时改；不记状态 |
| [progress.md](progress.md) | 做到哪（「已约定，尚未写代码」「已完成」） | 每个阶段结束时 |
| `docs/handoff/` | 每次会话的操作和证据 | 每次会话结束时 |

本文件不记「第几阶段完成了」。当前做到哪，只看 `progress.md` 和最新的交接记录。

## 1. 通用规则（每个阶段都适用）

**环境**

| 做什么 | 用哪个解释器 |
|---|---|
| `python -m pytest tests`（主环境基线）、`live`、`server` | `.venv/bin/python`（Windows `.venv\Scripts\python`） |
| `agent`、MCP、知识库、`model_nn`、LoRA、ML 环境下的 `pytest tests` | `.venv-ml/bin/python` |
| 阶段 1.5 的框架概念验证（已结束，环境已删） | `.venv-poc/bin/python` |

- 从仓库根目录运行。不跑不带路径的 `pytest`。
- `.venv` 一个包都不加（方案 §5）。往 `.venv` 里装东西就算这个阶段失败。

**每个阶段开始前**

1. 读 `AGENTS.md`、`session-handoff` 技能、最新 1–2 份交接记录、`progress.md`。
2. 读这一阶段卡片「先读」里列的文件。
3. 检查卡片「入口」：前置阶段都已由你验收；用到的决定（第 3 节）都已经定了。没定就先问你，不按默认值往下做。

**做的过程中**

- 只做卡片「任务」里列的事。卡片外的改动（重构、加依赖、改别的层）先问你。
- 文件尺度按 `docs/modules.md`：80–300 行，超过 400 行要拆；不建 `utils.py` 一类文件。
- 下载模型或大体积依赖之前，先说明来源和大小，经你同意再下。
- 密钥只放仓库根目录的 `.env`，由你填写。不读取、不打印、不写进日志或交接记录。
- 不写 `football.db`、`fotmob.db`；Agent 一律用 `open_readonly`。Mac 上不提交 `football.db`、`reports/`、`logs/`。
- 不改 `大模型项目/`，不直接改 `.claude/skills/`。
- 提交、建分支、合并都要你明确同意。建议每个阶段一个分支，命名 `agent/p<阶段>-<短名>`。

**每个阶段结束时**（第 11 节有清单）

验证命令全部通过 → 写交接记录（附出口证据）→ 更新 `progress.md` → 等你验收 → 你同意后再提交 / 合并 → 下一阶段。

验收项不通过时，不跳过、不放宽判据：查明原因、修好再验。修不好就停下，说清缺什么，交给你决定。影响运行的问题按 `issues.md` 的格式记一条。

## 2. 阶段顺序

```
P0 环境与规范 ──→ P1 工具层 + MCP ──→ P1.5 框架概念验证 ──→ P2 知识库 ──→ P3 Agent 图 + 命令行 ──→ P6 对话服务 + 网页
      │                                                                        │
      └──→ P4 model_nn（只依赖 P0，可与 P1–P3 穿插）                              └──→ P5 LoRA（要 P3 的对话记录）
```

一次只开一个阶段的分支。P4 要和 P1–P3 穿插时，用单独的分支，两边不改同一个文件。

## 3. 决定什么时候要定

方案 §12 的 8 项，不用一次全定，到对应阶段的入口时再定：

| 决定（方案 §12） | 谁要用 | 没定时 |
|---|---|---|
| 1 环境方案 | P0 | 你已经通过方案，按方案 §5 做 |
| 4 Windows 实盘机的 Python 版本和机器架构 | P0 的 Windows wheel 检查 | 只做这一项时停下等你；其余 P0 项照做。**已核对 3.12 / AMD64**（2026-10-27 在 Windows 实盘机上运行：`3.12.10 ... [MSC v.1943 64 bit (AMD64)] AMD64`；那台机器没有 `.venv`，定时任务用的是系统 Python `C:\Users\93589\AppData\Local\Programs\Python\Python312\python.exe`），P0 的解析结果不用重跑 |
| 6 中文队名表放哪 | P1 的 `resolve_team` | 先只用 `TEAM_ALIASES`，中文名留空，交接里注明 |
| 2 默认云端模型和密钥 | P1.5、P3 | **已定**（2026-10-27）：OpenAI 兼容中转站 + `DeepSeek-v4.1-flash-1017`，密钥在本机 `.env` |
| 8 下载 bge-m3 / 重排模型 / Qwen | P2、P5 | 对应阶段不能开始 |
| 研究白名单里锚点不够的 4 条（方案 §7.2） | P2 | 这 4 条不收，其余照做 |
| 7 G1 判据和登记哪些检验 | P4 写 `prereg.md` 之前 | **已定**（2026-10-27）：登记 T1–T4，m = 4，每个检验要求差值 + 2.54×SE < 0 |
| 3 三道额度金额和并发上限 | P3 的命令行额度、P6 | **已定**（2026-10-27）：每人每日 2、全站每日 10、全站每月 100 美元（北京时间），全站并发 3、每人 1；P3 的个人一档另算 |
| 5 网站对话做不做、用哪种鉴权 | P6 | **已定**（2026-10-27）：做，用做法 A（邀请码 + 会话 Cookie），只允许一个对话转发路由；不建分支，直接在 main 上开发 |

### Windows 实盘机拉取后自行核对

决定 4 已于 2026-10-27 核对（见上表第 4 行）；以下是当时的步骤。Windows 实盘机第一次拉取含 P0 的提交后，在那台机器上由 Agent（或人）按顺序做，不用先问 Mac 那边：

1. 在仓库根目录运行 `.venv\Scripts\python -c "import sys, platform; print(sys.version, platform.machine())"`。
2. 判断：
   - 输出是 3.12.x、`AMD64`：暂定值成立。在 `docs/handoff/` 写一份交接记下这行输出，把上表第 4 行的「暂定」改成「已核对」并写日期。
   - 版本或架构不同：在 Mac 或那台机器上按方案 §5 用实际的 `<X.Y>`（ARM64 时换 `--python-platform aarch64-pc-windows-msvc`）重跑 `uv pip compile`，结果写进交接，再改上表第 4 行。解析失败时停下，把缺 wheel 的包告诉用户，不改 `requirements-ml.txt`。
3. 顺带核对 `.venv`：`.venv\Scripts\python -m pip check`，以及 `set PYTHONIOENCODING=utf-8` 后跑 `.venv\Scripts\python -m pytest tests -q`。2026-10-27 Mac 上的基线是 218 passed、没有 skip。缺 httpx 一类 `requirements.txt` 已写的包时，`.venv\Scripts\python -m pip install -r requirements.txt` 补上（只补 `requirements.txt` 里的包，不装 ML 包），见 `docs/issues.md`「Mac 的 `.venv` 没装 httpx」。
4. 这一步只做核对，不在 Windows 上建 `.venv-ml`。真正在那台机器装 ML 环境，按方案 §5，放到需要在那台机器跑 Agent 或 `model_nn` 时再做。

## 4. P0 环境与规范

**目标**：建好 `.venv-ml`，证明现有 `.venv` 和测试没有受影响，把方案定下来的规则并进规范文档。不写 `agent/` 代码。

**先读**：方案 §3、§5、§11；`docs/stack.md`、`docs/modules.md`、`docs/ml-stack.md`。

**入口**：方案已通过。

**任务**

1. 记录基线：
   - `.venv/bin/python -m pip freeze > /tmp/venv_before.txt`；
   - `.venv/bin/python -m pytest tests -q` 的通过数和跳过数；
   - `football.db` 的 md5。
2. 新建 `requirements-ml.txt`：方案 §5 列出的直接依赖，用 `==` 钉版本。编排框架这一组不写进去（P1.5 之后再写）。
3. 新建 `constraints-ml.txt`：钉住与 `requirements.txt` 重叠的包（numpy、pandas、scipy、pydantic、fastapi、httpx 等），版本取 `.venv` 里实际装的版本；再钉 tokenizers、safetensors 等关键间接依赖。不用整份 `pip freeze`。
4. 新建 `.venv-ml`，按方案 §5 的命令安装。torch 等大包装之前，先告诉你包名、版本和大概的下载大小。
5. 检查：
   - `pip check`；
   - `import torch, chromadb, transformers, mcp`；
   - `torch.backends.mps.is_available()`。
6. 对比：
   - `.venv` 的 `pip freeze` 和第 1 步完全一致；
   - `.venv` 和 `.venv-ml` 里各跑一次 `python -m pytest tests`，都通过，通过数一致（lightgbm 的 skip 可以不同，要写明）。
7. Windows wheel 检查：按方案 §5 的 `uv pip compile` 命令（`--python-platform x86_64-pc-windows-msvc --only-binary :all:`），`<X.Y>` 等你给出 Windows 机的 Python 版本后再跑。记录解析是否成功、哪些包没有 wheel、与 Mac 上 `.venv-ml` 的差异。不用 `pip download --platform`（在 Mac 上按本机求值环境标记，会误报缺 uvloop）。
8. `.gitignore` 加：`.venv-ml/`、`.venv-poc*/`、`.env`、`agent_data/`、`checkpoints/`。新建 `.env.example`，只写变量名（`AGENT_PROVIDER`、`AGENT_MODEL`、各家密钥的变量名、额度、`AGENT_SERVICE_TOKEN`、`SITE_URL`），不写值。
9. 并入规范（只写定下来的规则，不抄方案全文）：
   - `docs/ml-stack.md`：torch 改成过了 G1 才进 `requirements.txt`；`model_nn` 在 `.venv-ml` 里研究；G1 在 `football.db` 冻结副本上做，训练历史从 2122 起，一个留出集只有一份预算（方案 §9.1）。
   - `docs/stack.md`：Agent 和训练的选型、`.venv-ml`、框架等 P1.5 再定。
   - `docs/modules.md`：在根目录加 `agent/`，与 `server/` 并列；调用方向 `agent → services`，`football_prediction` / `server` 不 import `agent`；对话转发路由的例外等到 P6 再写。
   - `AGENTS.md`：命令一节加 `.venv-ml` 的用法；布局表加 `agent/`（标明还没有代码）；检索一节加本文件和方案的指针。
10. `progress.md`：「已约定，尚未写代码」里 Agent 模块那一条，补上 P0 做完的部分。

**验证**

```bash
.venv/bin/python -m pytest tests -q
```

```bash
.venv-ml/bin/python -m pytest tests -q
```

```bash
.venv-ml/bin/python -m pip check
```

**出口证据**（写进交接）：两份 `pip freeze` 的 diff 为空；两个环境的 pytest 汇总行；`pip check` 的输出；import 和 MPS 的结果；实际钉的版本表；Windows wheel 的解析结果（如果第 7 步还在等，就写「等待 Windows Python 版本」）；`football.db` 的 md5 前后一致；`git status` 里只有本阶段的文件。

## 5. P1 工具层与 MCP

**目标**：用 Python 函数实现方案 §6 的只读工具（`kb_search` 先用假实现），并通过 MCP 暴露。不接大模型。

**先读**：方案 §4、§6；`football_prediction/services/match_read.py`；`server/app.py`（看现在怎么调 services）；`tests/conftest.py`。

**入口**：P0 已验收。决定 6（中文队名表）没定时，按第 3 节处理。

**任务**

1. `services` 新增读函数（和接口共用）：按队名查最近几场、读阵容 / 伤停、评分行（含 `result_src` 和指标列）。`match_read.py` 现在 253 行，加完超过 300 行就新开 `services/team_read.py`。函数不写库。
2. `agent/__init__.py`、`agent/config.py`：库路径、快照路径，从 `.env` 读，带默认值。
3. `agent/tools/matches.py`：
   - 实现 `list_upcoming`、`get_match`、`recent_results`、`explain_fixture`、`scorecard`、`resolve_team`、`team_news`。
   - 把返回包成块，每块带 `scope`、主体键、`kind`、`at`（方案 §6 的两张表）。
   - 开球后的快照看法按方案 §6 改标为 `last_pre_kickoff`，快照时间不早于开球的整块丢掉。
   - 不改 `read_match`。
4. `agent/tools/knowledge.py`：`kb_search` 的假实现，签名和方案 §6 一致，返回固定的块。
5. `agent/mcp_server.py`：用 stdio 暴露上面的工具，同一个函数，不写两份。`python -m agent.mcp_server` 能启动。
6. 测试：
   - `tests/test_agent_tools.py`：每个工具的返回结构；块的四个字段；开球前 / 后改标；整块丢弃。
   - `tests/test_agent_boundary.py`：
     - 用 AST 扫描，确认 `football_prediction/` 和 `server/` 不 import `agent`；
     - `agent/` 不 import 领域包，只 import `football_prediction.services` 和 `version`；
     - `agent/` 里没有 SQL 字符串。
   - 只读测试：在临时目录建一个文件型 SQLite（用 conftest 的合成比赛），跑一遍全部工具，库文件的 md5 不变。
   - MCP 的测试用 `pytest.importorskip("mcp")`，在 `.venv` 里跳过。

**验证**：两个环境的 `pytest tests` 都通过；`.venv-ml/bin/python -m agent.mcp_server` 能启动，并能用 MCP 客户端列出工具。

**出口证据**：
- 两个环境的 pytest 汇总；
- 只读测试的 md5；
- 本机真实 `football.db`（只读）上 `list_upcoming` 的一段输出；
- 给你用的 MCP 注册命令（`claude mcp add ...`），由你自己执行，因为 `.mcp.json` 不由我改。

## 6. P1.5 框架概念验证

**目标**：在 LangGraph 和 OpenAI Agents SDK 之间选一个（方案 §3）。概念验证的代码不合并进 main。

**结果（2026-10-27）**：用户直接选定 LangGraph，没有写 Agents SDK 的实现。概念验证在分支 `agent/p15-poc`；依赖已移进 `requirements-ml.txt`，`.venv-ml` 已重建。交接：`docs/handoff/2026-10-27-0352-…`（实测）和本阶段收尾那份。

**先读**：方案 §3、§8.1、§8.2。

**入口**：P1 已验收；决定 2 已定，你已在 `.env` 里填好密钥。

**任务**

1. 建分支 `agent/p15-poc`。新建 `requirements-poc.txt`，两套框架都写上、都钉版本；建 `.venv-poc` 并安装，跑 `pip check`。有冲突就分成两个环境（方案 §5）。
2. 两套框架各写一个最小实现：用 P1 的 3 个工具（`list_upcoming`、`get_match` 和 `kb_search` 的假实现），走方案 §8.1 的流程。`verify` 先只查「文字里没有数字」和「占位与事实一一对应」两条。
3. 20 条问题放在 `agent/eval/poc.jsonl`。脚本里写死调用次数上限：`model_calls` ≤ 6、HTTP ≤ 12。跑之前先告诉你预计花多少（按 token 估算），你同意再跑。
4. 按方案 §3 的五项逐项记录：接 Claude 和本地 OpenAI 兼容接口、结构化输出加打回重答要写多少代码、状态持久化和中断恢复、能不能用假模型做离线测试、能不能设次数上限并拿到 token 用量。另外记下两边实际花的钱。

**出口证据**：对比表和实际花费写进交接，由你定框架。定下之后（在 main 的后续分支上做）：
- 把选中的那组依赖写进 `requirements-ml.txt`，`docs/stack.md` 写明选了哪个框架；
- 删掉 `.venv-poc*`，重建 `.venv-ml`；
- 重跑 P0 的第 5、6、7 步，证据另写一份交接。

## 7. P2 向量知识库

**目标**：带时点过滤的混合检索，把 `kb_search` 换成真实实现（方案 §7）。

**结果（2026-10-27，代码已写，待你抽查评测集后验收）**：向量库按你的决定用 Milvus Lite（`pymilvus` 3.0.2 + `milvus-lite` 3.2.2），替代原定的 Chroma，`rank-bm25` 不装。评测集 100 条（83 条普通题、17 条泄漏用例），基线和泄漏结果在 `docs/progress.md` 与本阶段的交接记录里。没有下载重排模型，「混合 + 重排」未跑。研究白名单里锚点不够的 4 条（`algo_sweep`、`new_league_tiers`、`reliability`、`ah_baseline`）先不收。

**先读**：方案 §6（块的格式）、§7 全部；`football_prediction/review/store.py` 的 `score_predictions`、`reconcile_results`、`_backfill_ah`。

**入口**：P1.5 已定框架，`.venv-ml` 已重建；决定 8（下载 bge-m3）已同意；研究白名单里锚点不够的 4 条已由你确认，或决定先不收。

**任务**

1. `agent/kb/whitelist.toml`：
   - `rule` 和 `status` 两级按方案 §7.2 列出；
   - `research` 收锚点核对通过的那几条，每条写 `cited_in`、`basis`、`generated_by`、`anchors`；
   - `record` 先为空。
2. `agent/kb/sources.py`：
   - 白名单里的文件切成块，`available_at` 取 git 提交时间，未提交的改动不收；
   - 比赛类的块（看法、存档、比分、评分、阵容）通过 `services` 的读函数从库里取，`available_at` / `event_time` / `at_source` 按方案 §7.1 的表；
   - 比分按来源分块，评分块只放指标和 `score_used`。
3. `agent/kb/index.py`：
   - Milvus Lite 存在 `agent_data/kb/`，bge-m3 做向量（2026-10-27 用户选定 Milvus Lite，替代原定的 Chroma）；
   - BM25 用 Milvus 自带的 BM25 函数，入库前中文按字二元切分；
   - 两路各取前 20，用 RRF 合并；
   - 按 `as_of` 和 `superseded_at` 过滤；
   - 评分块的指纹，以及三种改法的处理和来源标签现定，都按方案 §7.1；
   - `python -m agent.kb --rebuild` / `--update`。
4. `agent/tools/knowledge.py` 换成真实实现：传 `match_id` 时，`as_of` 由工具算，不由模型填。
5. 评测集 `agent/eval/retrieval.jsonl`：60–100 条，人工标注应命中的块，带 `as_of`。先由我起草，你抽查后定稿。
6. 测试（离线，用临时目录里的 Milvus Lite；不想加载 bge-m3 时可换成假的向量函数）：
   - 白名单测试（方案 §7.2 的五条）；
   - 泄漏用例；
   - 评分块三种改法分别在 `--update` 后的结果；
   - 来源标签随 `as_of` 变化；
   - 白名单之外的文件不入库。

**验证**：两个环境的 `pytest tests` 都通过（知识库测试在 `.venv` 里跳过）；`--rebuild` 和 `--update` 在真实库上都能跑完；泄漏用例为 0。

**出口证据**：
- 四种检索方式（只用向量、只用 BM25、混合、混合 + 重排）的 recall@5 和 MRR 基线表；
- 泄漏用例的数量和失败数（必须是 0）；
- 索引的大小和重建用时；
- 白名单最终收了哪些文件。

重排模型只有在基线表显示有提升、并且你同意下载之后才开。

## 8. P3 Agent 图、结构化事实与命令行

**目标**：`python -m agent "问题"` 能给出每个数字都核对过来源的回答（方案 §8）。

**结果（2026-10-27 完成，你验收后合入 main）**：个人日额度 2 美元（北京日），价格表先填 `DeepSeek-v4.1-flash-1017`。第二轮评测 26 题：首次通过 0.423、通过（含重答）0.808、降级 0.192、措辞与 `kind` 不符 0、放行表打回 0.316，花费 0.2389 美元。数字和未处理的问题在 `docs/progress.md` 与本阶段的交接记录里。

和方案不同、你已同意的做法（以这里为准；方案 §8、§10 的原文没有改）：

- 校验写成包 `agent/facts/`（`numbers.py` 第 1 条、`units.py` 单位对照表、`verify.py` 第 1–8 条、`render.py` 渲染与降级），不是单文件 `facts.py`。
- 单位表多一个 `brier`（成绩单的 Brier）。
- 每轮工具返回总量上限 `AGENT_MAX_TOOL_TOKENS`（默认 12000 token）；超出的那次返回不交给模型，回一句「缩小范围再查」。
- 第 8 条在没有事实时也查；只认本轮工具结果里出现过的队名。
- 小数按工具结果的写法严格比对。
- `budget.py` 只写 `agent_data/usage.db`（P3 时是 `agent/` 里唯一写 SQL 的文件）。P6 起 `access.py` 也写 SQL，只碰 `agent_data/access.db`。两处都由 `tests/test_agent_boundary.py` 检查。
- 5xx 和超时一样记 `usage_unknown`，按满预留额计。
- 高峰倍率只按 `prices.toml` 里周一至周五的时段，不认节假日和调休。
- `max_tokens` 默认 6000（含思考 token）。2000 时思考就占掉约 1600，第一轮有 4 次回复被截断成空；被截断时提示「少想，直接提交」，不用普通的催促。
- 知识库打开失败隔 1 秒重试一次：同进程里 Milvus Lite 的 gRPC 连接偶尔被对端以 `too_many_pings` 断开，原来会被当成「另一个进程在用」。
- 放行表按第一轮评测增补 15 个词：北京、参照、参考、另一、下一场、上一场、下一轮、上一轮、最后一轮、最后一场、最近一场、下一步、下一阶段、两者、两队。每个词都有测试，另测了它们旁边的真数量照拦。

**先读**：方案 §8 全部、§10.3；P1.5 的交接（选了哪个框架）。

**入口**：P2 已验收；决定 2 已定；你的个人额度金额已定（决定 3 的一部分）。

**任务**

1. `agent/facts/`（实际拆成包，见上面的结果）：
   - 事实的格式、单位对照表；
   - 校验规则第 1–8 条；第 1 条的数字识别按「默认拦、放行表放」，词表写死；
   - 渲染和来源标签，以及降级输出。
2. `agent/llm.py`：
   - 按 `AGENT_PROVIDER` 返回模型；
   - SDK 自带的自动重试设为 0，由这里自己重试最多 1 次，只对超时、429、5xx 重试。
3. `agent/budget.py`（先做命令行需要的部分）：
   - `agent_data/usage.db`，每次 HTTP 请求单独预留，用 `BEGIN IMMEDIATE`；
   - 结算、`usage_unknown`；
   - `model_calls` 和 HTTP 请求的硬上限；
   - 价格表 `agent/prices.toml`（单价由你填）；
   - 个人额度一档。
   每人 / 全站额度和并发计数留到 P6。
4. `agent/graph.py`：
   - 按选定的框架实现方案 §8.1 的图；
   - 四个计数各自判定，边界规则按方案 §8.1 的列表。
5. `agent/prompts.py`、`agent/__main__.py`。对话状态存在 `agent_data/state.db`。
6. 测试：
   - 方案 §8.5 列的全部必测项，含第 8.3 节第 1 条的数字写法用例和计数上限；
   - 方案 §10.4 里和计数、预留有关的几条（12 次请求、429 后重试、6 次即停）。

**验证**：两个环境的 `pytest tests` 都通过；离线测试全部用假模型。真实模型的评测跑之前，先告诉你预计花多少。

**出口证据**：
- 离线测试的汇总；
- 评测集 `agent/eval/agent.jsonl` 上的数字：verify 一次通过率、降级率、措辞与 `kind` 不符的比例、放行表的打回率；
- 实际花费；
- 几条示例对话，渲染后的样子。

## 9. P4 `model_nn`（PyTorch）

**目标**：按方案 §9.1 训练并检验表格网络，得出 G1 的判定。结果不论好坏都写进 progress。

**先读**：方案 §9.1；`docs/ml-stack.md`；`.claude/skills/pytorch-training/SKILL.md` 和 `numpy-analysis/SKILL.md`（按 `AGENTS.md` 的触发表）；`features/builder.py`、`validation/backtest.py`、`model_dc/market_dc.py`（看 `fit` 的写法）。

**入口**：P0 已验收。写 `prereg.md` 之前，决定 7 必须已定。

**任务**

1. 冻结副本：用 SQLite 的 backup 接口，把 `football.db` 复制到 `checkpoints/g1/football_<日期>.db`，记下 md5。之后选参和留出都只读这一份。
2. `football_prediction/model_nn/`：
   - `dataset.py`：每场样本按它自己的 cutoff 生成特征，缓存在 `checkpoints/nn_features/`；
   - `net.py`：输出 λ，用 softplus；
   - `train.py`：种子写进配置；早停只用训练集内部按时间切出来的一段；
   - `model.py`：`fit(conn, league, cutoff_date)`。
   模块顶层不 import torch。
3. 登记 `LAYER_VERSION`：写进 `version.py` 的 `LAYER_VERSIONS` 和 `tests/test_versions.py` 的 `MODULES`。不升 `SYSTEM_VERSION`。
4. 测试 `tests/test_model_nn.py`：
   - 时点测试：删掉某场之后的比赛，这场的特征完全不变；
   - λ 是正数，比分矩阵加起来等于 1；
   - 用 `importorskip("torch")`，在 `.venv` 里跳过，确认 `.venv` 里 `test_versions` 仍能通过。
5. 选参：
   - 脚本 `_diag/model_nn/select.py`，只在 2425 上按月评估，训练历史从 2122 起；
   - 比较 A / B、`full` / `no_xg`、各种超参；
   - 结果写到 `_diag/model_nn/select.log`；
   - 每次评估都在 `_diag/model_nn/eval_log.md` 追加一行：副本的 md5、日期范围、配置、提交号。
6. 预注册：按方案 §9.1 写 `_diag/model_nn/prereg.md`，内容包括：
   - 登记了哪些检验、m 和 z；
   - 主配置、训练窗口规则、联赛是否合并训练、特征来源；
   - 副本的 md5。
   给你看过、你同意后**单独提交一次**，提交号写进 progress。
7. 留出：
   - 脚本 `_diag/model_nn/holdout.py`，在 `prereg.md` 的提交之后运行；
   - 每个登记的检验只跑一次，输出 `_diag/model_nn/holdout.log`；
   - 按联赛、按赛季的结果只作描述，同样写进这份 log。
8. 判定：每个检验按「差值 + z×SE < 0」判断是否通过。通过的才进入方案 §9.1 的 G1 后续步骤（升版本、把 torch 加进 `requirements.txt`、在 Windows 上验收），而且这一步要另开分支、经你同意。

**验证**：两个环境的 `pytest tests` 都通过；`git log` 显示 `prereg.md` 的提交早于 `holdout.log` 的提交；`eval_log.md` 里在 `prereg.md` 提交之前没有任何 2526 的范围。

**出口证据**：
- 选参的结果表；
- `prereg.md` 的提交号；
- 留出的结果表：同场差值、SE、z，以及每个检验是否通过；
- 训练用时和内存 / MPS 的实测；
- progress 里写进的结论。

逐场 CSV 等中间数据按 `.gitignore` 不提交，`.log` 和 `.md` 提交。

## 10. P5 LoRA 微调

**目标**：本地小模型能正确调用工具、按格式提交事实（方案 §9.2）。

**先读**：方案 §9.2；`.claude/skills/transformers-framework/SKILL.md`；`docs/ml-stack.md`。

**入口**：P3 已验收，并且已经有通过 verify 的对话记录；决定 8（Qwen 型号和下载）、决定 4（显卡）已定；你确认过云端模型输出能否用来训练（服务条款，方案 §9.2 写明未核实）。没确认之前，只用模板造的数据。

**任务**：
- `agent/train/traces.py`：生成训练数据，按比赛日期切分训练集和验证集；
- `agent/train/lora_sft.py`：用 PEFT + TRL 训练，适配器放在 `checkpoints/agent_lora/<日期>/`；
- `agent/eval/agent.jsonl`：对比三方，即微调前、微调后和云端模型；
- 本地推理：先试 Ollama 能不能直接加载适配器，不行就合并权重后再导入，两种结果都要记下来。

**出口证据**：工具选对率、参数正确率、verify 一次通过率、降级率的对比表；训练时的实测内存；适配器的大小。

向量模型微调（`embed_ft.py`）只在 P2 基线显示 recall 不够、而且错误集中在本项目术语上时才做，做之前另外问你。

## 11. P6 对话服务与网页

**目标**：群友能在网站上用 Agent 对话，有鉴权、有额度（方案 §10）。

**先读**：方案 §10 全部；`docs/modules.md`；`docs/stack.md` 的部署一节；`run_site.bat`、`setup_site.ps1`；`web/` 的现有结构。

**入口**：P3 已验收；决定 3、5 已定。选了做法 B 时，先由你在 Windows 机上完成方案 §10.2 的 Tailscale 实测，结果不成立就改用做法 A。

**任务**：
- `agent/serve.py` 只听 127.0.0.1，检查服务令牌；
- `budget.py` 补上每人 / 全站的日、月额度和并发计数；
- Next.js 加一个对话转发路由，同时修改 `docs/modules.md` 写明这一个例外；
- 实现所选做法的鉴权和 CSRF；
- 改部署脚本：只在做法 B 时改 `run_site.bat` 和 `setup_site.ps1`，两个文件都要保持纯 ASCII 加 CRLF；
- 前端的对话页。

**验证**：
- Python：两个环境的 `pytest tests`。
- 前端：在 `web/` 按顺序执行 `npm run typecheck`、`npm run lint`、`npm run test`、`npm run build`、`npm run test:e2e`。不能并行，也不能在站点运行时在 Windows 上跑。
- 方案 §10.4 的「共同」和所选做法那一组，逐条记录结果。

**出口证据**：方案 §10.4 每一条的结果；360/390/768/1440 四个视口下的截图或检查结果；没做真机测试这一点要写明。

## 12. 阶段结束清单

- [ ] `.venv/bin/python -m pytest tests -q` 通过（写下数字）。
- [ ] 本阶段用到 `.venv-ml` 时，`.venv-ml/bin/python -m pytest tests -q` 通过。
- [ ] `football.db` 的 md5 在本阶段前后一致（P4 的 G1 后续步骤除外）。
- [ ] `git status` 只有本阶段的文件；没有 `.env`、权重、`agent_data/`、`checkpoints/`。
- [ ] 卡片「出口证据」逐项写进 `docs/handoff/YYYY-MM-DD-HHMM-摘要.md`。
- [ ] `progress.md`：更新「已约定，尚未写代码」或「已完成」；改了预测行为、升了版本时，按 progress 末尾的步骤做。
- [ ] 发现会影响运行的问题，就写进 `issues.md`。
- [ ] 方案和本文件与实际做法不一致的地方，先停下问你，同意后再改文档。
- [ ] 你验收后再提交或合并。
