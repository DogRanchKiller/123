# 技术栈

本文件定义前端、后端、训练的选型。训练的数据切分、指标、版本和 checkpoint 规则仍以 [ml-stack.md](ml-stack.md) 为准。

三层分工固定：浏览器只展示和发请求；FastAPI 只暴露现有预测能力；训练只在 Python 里进行，不在 TypeScript 里训练。

## 前端

语言是 TypeScript。应用是 Vite + React，样式用 Tailwind CSS，服务端数据用 TanStack Query。路由用 React Router。

接口类型从后端 OpenAPI 生成（`openapi-typescript`），不手写一套与响应对不齐的类型。

页面覆盖现有报告和成绩单：未开赛场次的胜平负概率、倾向、信心档、最可能比分、大 2.5 球，以及赛后评分。计算留在 `football_prediction`，页面不重算概率。

落地目录是 `web/`。在此之前不要加前端依赖。

## 后端

语言是 Python（3.12+，与现有 `.venv` 相同）。框架是 FastAPI，进程是 Uvicorn，请求和响应模型是 Pydantic v2。

代码放在 `server/`，只调用 `football_prediction/services/` 的用例。路由里不写 Dixon-Coles、LightGBM 或神经网络。目录、调用方向和文件尺度见 [modules.md](modules.md)。数据库继续用仓库根目录的 `football.db`，不另起一套库。

开发时为 Vite 源站打开 CORS。契约以 FastAPI 自动生成的 OpenAPI 为准。当前是本机单用户，第一版不加登录。

`fastapi` 和 `uvicorn` 在实现 `server/` 时再写入依赖。在此之前 `pytest tests` 保持现有依赖可跑。

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
