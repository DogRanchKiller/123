# 足球预测系统

仓库根目录的可运行项目是 `football_prediction`（英超 E0 / 德甲 D1 / 西甲 SP1）。在仓库根目录工作，数据库与报告路径都相对 cwd。

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

技能正文是步骤，规则以 `docs/ml-stack.md` 为准。Codex 读 `.agents/skills/`。Claude Code 经 `.claude/skills/` 的符号链接读同一份文件。

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

依赖在 `.venv`（Python 3.10+）。从仓库根目录：

```bash
.venv/bin/python -m pytest tests   # 离线单测，不联网、不碰 football.db
.venv/bin/python -m football_prediction.live   # 实盘一轮：更新数据 → 评分 → 预测 → 报告
.venv/bin/python -m football_prediction.main   # 全量回测对比；会下载赛季 CSV，很慢
```

不要跑不带路径的 `pytest`：它会收集 `大模型项目/` 里依赖 torch 的测试并在收集阶段失败。

改完一层后跑 `.venv/bin/python -m pytest tests`。`tests/` 只用内存 SQLite 和合成比赛；新测试保持离线。

## 布局

| 路径 | 职责 |
|---|---|
| `football_prediction/version.py` | 各层版本、`PRIMARY_MODEL`、`PROMOTE_MIN_N` |
| `data/loader.py` | football-data.co.uk → `football.db`（赛果、赔率、射正、赛程） |
| `data/understat.py` | understat xG → `match_xg`；已结束赛季缓存在 `_cache/understat/` |
| `features/builder.py` | 特征；只用截止日之前的比赛 |
| `model_elo/` `model_dc/` `model_lgbm/` | Elo、Dixon-Coles、射正版、xG 版、LightGBM 修正 |
| `calibration/platt.py` | Platt；2425 验证无增益，不进实盘主流程 |
| `validation/backtest.py` | 时间外回测、市场基准、同场配对 |
| `output/derive.py` `output/report.py` | 比分矩阵 → 胜平负 / 大小球；主模型报告写到 `reports/` |
| `review/store.py` | 预测写入同一 `football.db`，赛后评分 |
| `live.py` | 实盘入口。`services/` 建立后只保留命令行，编排规则见 [`docs/modules.md`](docs/modules.md) |
| `main.py` | 回测演示入口。同上 |

`football.db` 每次实盘都会变，已纳入版本库；需要备份时由用户决定是否提交。不要为了“清理工作区”还原或覆盖它。`reports/`、`_cache/`、`_diag/` 同样是运行产物。

## 预测规则

- 拟合一律 `match_date < cutoff`。实盘 cutoff 是当天（UTC），只预测尚未开球的场次。
- 每场、每个 `model_name` + `model_ver` 只保留开赛前**首次**预测。`save_prediction` 不覆盖旧行。改算法必须升版本，不能靠重跑改历史。
- 市场基准名 `market_avg`，版本是 `live.MARKET_VER`（算法变才改，不跟数据层走）。
- 报告只展示 `version.PRIMARY_MODEL`（现为 `dc_xg` / `model_xg`）。其余模型并行存档。
- 替换主模型只走 `promotion_check`：同一批已评分实盘上，场数 ≥ `PROMOTE_MIN_N`（1000）且（差值 + 2×SE）< 0。不要用回测事后改 `PRIMARY_MODEL`。
- 回测禁止随机 KFold。`2526` 是留出赛季：shrink、射正权重、xG 权重都不在该季上重选。当前选参：DC `shrink=0.5`，射正版进球权重 `w=0.7`，xG 版 `w=0.3`。
- 评价用 Log Loss，辅以 Brier。同场差值为负表示前者更好；`|差| < 2×SE` 视为无显著差异。

## 改一层时

1. 更新该模块的 `LAYER_VERSION`（模型类还有 `MODEL_VER` 的，一起改）。
2. 同步 `version.py` 的 `LAYER_VERSIONS`。行为变化才升版本；纯注释不必升。
3. 改 `live.py` 时，模块文档第二行要含 `v{live 版本}`，`tests/test_versions.py` 会检查。
4. 新增带 `LAYER_VERSION` 的模块时，把它登记进 `tests/test_versions.py` 的 `MODULES`。
5. 新联赛队名先走 `data/loader.py` 的 `TEAM_ALIASES`。understat 队名靠同日 ±1 天且同比分投票，不要手写第二套映射。
6. 按「进度与问题」更新 `docs/progress.md`。这次改动修了会影响运行的问题时，同时更新 `docs/issues.md`。

数据下载失败时沿用本地库，不要把空结果写成“已更新”。xG 必须在该赛季 `matches` 写入之后再拉。`match_xg` 只 `INSERT OR IGNORE`。
