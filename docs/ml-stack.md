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

第一个神经网络放在 `football_prediction/model_nn/`。同一改动里：

- 按 `AGENTS.md` 的「改一层时」登记 `LAYER_VERSION`。
- 把 `torch` 写进 `requirements.txt`。用到 Transformers 时再加 `transformers`。在此之前不要加这两项，实盘和 `pytest tests` 保持现有依赖可跑。
- 权重目录用 `checkpoints/`，并把它加入 `.gitignore`。权重不进版本库。
- 默认设备：有 CUDA 用 CUDA，否则 CPU。不把 GPU 写成运行前提。

## 预测契约

神经网络若要进入 `review` 或和现有模型同场比较，输出三项概率 `p_home_win`、`p_draw`、`p_away_win`，和为 1。有比分矩阵时，矩阵交给 `football_prediction/output/derive.py` 的 `derive_markets`。

拟合只用 `match_date < cutoff` 的比赛。`2526` 留出，不在该季上选超参或早停。随机种子写进训练配置并打印。训练过程不调用 `save_prediction`。

## 分析

概率指标以 `football_prediction/validation/backtest.py` 为准：`_log_loss_one`、`_brier_one`、`paired_compare`。比分矩阵的市场分解以 `derive_markets` 为准。

张量先 `.detach().cpu().numpy()` 再算这些指标。分析脚本不另写一套 Log Loss 或 Brier。

## 框架选择

训练语言是 Python。选型说明见 [stack.md](stack.md)。这里只保留实现约束。

输入是每场比赛的数值特征时，模型是 `torch.nn.Module`，训练循环用 PyTorch。此时不引入 `transformers`。已有表格模型继续用 LightGBM，不改写成神经网络。

输入是文本或序列，或要加载预训练 checkpoint 时，用 Transformers。适配用 PEFT 的 LoRA；显存不够时用 QLoRA。监督微调用 TRL 的 SFT，有偏好标签时用 DPO。不新写 P-Tuning 或 PET。权重来自本地目录，或来自用户本次明确要求的下载。下载前说明仓库和体积。checkpoint 放进 `checkpoints/`，不放进 `大模型项目/模型/`。
