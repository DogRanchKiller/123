---
name: transformers-framework
description: >
  用 Hugging Face Transformers 搭序列或预训练模型。Use when the user mentions
  Transformers, Hugging Face, Trainer, tokenizer, or a pretrained checkpoint。
  表格比赛特征改读 .agents/skills/pytorch-training/SKILL.md。
---

# Transformers 框架

1. 读 `docs/ml-stack.md` 的「框架选择」。完成标准：已判定输入是数值特征，还是文本、序列或预训练 checkpoint。
2. 数值特征：接着读并执行 `.agents/skills/pytorch-training/SKILL.md`。完成标准：模型是 `torch.nn.Module`，依赖里没有 `transformers`。
3. 文本、序列或预训练 checkpoint：用 Transformers 实现。适配方式按 `docs/ml-stack.md`「框架选择」：LoRA（显存不够时 QLoRA）、SFT，有偏好标签时 DPO。权重按该节放置。完成标准：代码不 import `大模型项目`，不新写 P-Tuning 或 PET，训练不写 `football.db`，下载前已向用户说明仓库和体积。
4. 训完要报概率指标时，读并执行 `.agents/skills/numpy-analysis/SKILL.md`。完成标准：指标来自该技能指定的函数。
