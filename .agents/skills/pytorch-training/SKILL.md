---
name: pytorch-training
description: >
  用 PyTorch 训练新的神经网络。Use when the user asks to train a model, write
  a training loop, or mentions PyTorch / 训练。先读 docs/ml-stack.md。表格特征
  走本技能；文本或预训练走 transformers-framework。
---

# PyTorch 训练

1. 读 `docs/ml-stack.md`。完成标准：任务归成两类之一。已有 Elo、Dixon-Coles、射正版、xG 版、LightGBM 的改动留在原模块。新的神经网络继续下一步。
2. 循环结构不清楚时，只读 `大模型项目/微调/` 里最接近的一个训练脚本，列出要借用的步骤。完成标准：借用的是循环结构，不是 P-Tuning 或 PET；实现计划里没有从 `大模型项目` 的 import。
3. 在 `football_prediction/model_nn/` 实现，并完成 `docs/ml-stack.md`「新模型落点」里的同一批改动。完成标准：训练只用 `match_date < cutoff` 的数据，种子写入配置并打印，权重在 `checkpoints/`，训练不调用 `save_prediction`。
4. 模型要和现有模型同场比较时，按该文件的「预测契约」输出三项概率。完成标准：概率和为 1，且 `tests/` 里有一条离线测试覆盖这一点。
