# 训练与分析规范

本文件是训练栈和分析栈的唯一规范。`AGENTS.md` 只负责检索到这里和对应 skill。技能步骤在 `.agents/skills/`，不重复本文件的规则。

## 可行性

三件事都能用，分工固定：

| 工作 | 工具 | 适用 |
|---|---|---|
| 指标、矩阵、分布、回测数值 | NumPy | 所有分析，含 PyTorch 训完之后的评估 |
| 新的神经网络 | PyTorch | 表格比赛特征上的新模型 |
| 序列、预训练权重、Tokenizer、Trainer | Hugging Face Transformers | 输入是文本或序列时 |
| 已有 Elo、Dixon-Coles、射正版、xG 版、LightGBM | 现有 SciPy、NumPy、LightGBM | 继续留在原模块 |

现有统计模型保持原实现。Transformers 不替换 `version.PRIMARY_MODEL`，也不把 Dixon-Coles 的比分矩阵包成语言模型。新模型要成为主模型时，仍走 `AGENTS.md` 里的 `promotion_check` 规则。

`大模型项目/` 的边界以 `AGENTS.md` 为准。借鉴训练循环时只读 `大模型项目/微调/` 里最接近的脚本，把循环结构抄到 `football_prediction`，用本系统的比赛数据。实现不 import 该目录，不把它的权重、数据集或 checkpoint 写入 `football.db` 或 `reports/`。

## 新模型落点

第一个神经网络放在 `football_prediction/model_nn/`，在独立环境 `.venv-ml` 里研究和训练（`requirements-ml.txt`，受 `constraints-ml.txt` 约束；见 [stack.md](stack.md)）。现有 `.venv` 不加任何包。

- 按 `AGENTS.md` 的「改一层时」登记 `LAYER_VERSION`。只研究、没过 G1 时不升 `SYSTEM_VERSION`。
- 模块顶层不 import torch：`version.py` 和 `tests/test_versions.py` 在 `.venv` 里读它的 `LAYER_VERSION` 不能失败。用到 torch 的测试用 `pytest.importorskip("torch")`。
- `torch` 只有在 `model_nn` 通过门槛 G1、要在实盘并行存档时，才写进 `requirements.txt`；那次改动另开分支，在 Windows 实盘机上装好并跑一轮 `live` 作为验收。在此之前 `requirements.txt` 不加 `torch` 和 `transformers`。
- 权重目录用 `checkpoints/`（已 gitignore）。权重不进版本库。
- 默认设备：有 CUDA 用 CUDA，Mac 上可以用 MPS，否则 CPU。不把 GPU 写成运行前提。

### 门槛 G1 的检验

细节在 [agent-plan.md](agent-plan.md) 第 9.1 节，这里只列规则：

- 选参（2425）和留出（2526）都在 `football.db` 的冻结副本上做：用 SQLite backup 接口复制到 `checkpoints/g1/`，只读打开，md5 写进预注册。`research.db` 只用于探索，它的结论不作 G1 证据，也不在它上面评估 2526。
- 训练历史从 2122 起，与实盘一致。窗口规则、联赛是否合并训练、特征来源都是配置的一部分，上线时原样使用。
- 每场样本的特征按这一场自己的 cutoff 生成（只用 `match_date <` 该场日期的比赛）。
- 跑 2526 之前先写 `_diag/model_nn/prereg.md` 并单独提交，登记全部确认性检验；2526 只跑一次。
- 一个留出集只有一份显著性预算（单侧 2.28%，按登记的检验数做 Bonferroni），在预注册时一次分完，之后不再在这个留出集上登记新检验。新预算只给 `model_nn` 从没评估过的新留出集；每次评估都在 `_diag/model_nn/eval_log.md` 记一行（副本 md5、日期范围、配置、提交号）。

## 预测契约

神经网络若要进入 `review` 或和现有模型同场比较，输出三项概率 `p_home_win`、`p_draw`、`p_away_win`，和为 1。有比分矩阵时，矩阵交给 `football_prediction/output/derive.py` 的 `derive_markets`。

拟合只用 `match_date < cutoff` 的比赛。`2526` 留出，不在该季上选超参或早停。随机种子写进训练配置并打印。训练过程不调用 `save_prediction`。

## 分析

概率指标以 `football_prediction/validation/backtest.py` 为准：`_log_loss_one`、`_brier_one`、`paired_compare`。比分矩阵的市场分解以 `derive_markets` 为准。

张量先 `.detach().cpu().numpy()` 再算这些指标。分析脚本不另写一套 Log Loss 或 Brier。

## 框架选择

训练语言是 Python。选型说明见 [stack.md](stack.md)。这里只保留实现约束。

输入是每场比赛的数值特征时，模型是 `torch.nn.Module`，训练循环用 PyTorch。此时不引入 `transformers`。已有表格模型继续用 LightGBM，不改写成神经网络。

输入是文本或序列，或要加载预训练 checkpoint 时，用 Transformers（同样只在 `.venv-ml` 里）。适配用 PEFT 的 LoRA；显存不够时用 QLoRA。监督微调用 TRL 的 SFT，有偏好标签时用 DPO。不新写 P-Tuning 或 PET。权重来自本地目录，或来自用户本次明确要求的下载。下载前说明仓库和体积。checkpoint 放进 `checkpoints/`，不放进 `大模型项目/模型/`。
