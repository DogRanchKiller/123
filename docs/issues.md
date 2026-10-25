# 问题记录

只在这个文件记问题。新问题写在「未解决」最上面。解决后把整段移到「已解决」，不删原文。

一条的格式：

```markdown
### 标题

- 状态：未解决 / 已解决（层版本）
- 日期：YYYY-MM-DD
- 现象：
- 原因：
- 处理：
- 位置：
```

现象写看到的结果，原因写代码或数据上的依据，处理写最后怎么做的。没有查清原因时，原因写「未查清」，不要补一个猜测。

## 未解决

### data 层两个文件超过 400 行

- 状态：未解决
- 日期：2026-10-24
- 现象：`data/loader.py`、`data/oddsportal.py` 各 418 行，超过 `docs/modules.md` 的上限。
- 原因：v1.4.0 / v1.5.0 加快照、亚盘和爬虫时没有先拆文件。
- 处理：下次改这两个文件之前先拆。候选：`loader.py` 的赛程与快照（`load_fixtures`、`save_snapshots`、`odds_movement`）拆到同包新文件；`oddsportal.py` 的 `book_odds` 表结构与 `book_consensus` 拆出，抓取与配对留在原文件。拆分不改行为、不升版本。
- 位置：`football_prediction/data/loader.py`、`football_prediction/data/oddsportal.py`

## 已解决

### 返回预测列表时滚动恢复被路由重置

- 状态：已解决（web 0.1.0，预测版本不变）
- 日期：2026-10-25
- 现象：筛选保留，但从详情返回列表后偶发滚回顶部。
- 原因：Next Link 自动滚动与 sessionStorage 的恢复同时执行，路由切换也可能在卸载前改变 window.scrollY。
- 处理：返回列表链接关闭路由自动滚动；记录最后一次列表滚动位置，卸载时不读取新页面的位置；生产浏览器测试覆盖刷新和返回恢复。
- 位置：`web/src/features/predictions/list-state.client.ts`、`web/src/features/match/match-detail.tsx`

### 网站错误页重试没有重新读取服务端数据

- 状态：已解决（web 0.1.0，预测版本不变）
- 日期：2026-10-25
- 现象：生产测试注入取数故障得到 5xx；故障解除后点击“重新读取”仍显示错误页。
- 原因：Next.js error boundary 的 reset 只重置组件，不保证重新请求失败的服务端数据。
- 处理：按钮改为重新请求当前文档；生产浏览器测试验证 5xx、错误文案、重试恢复以及旧结果延迟展示。
- 位置：`web/src/app/error.tsx`、`web/tests/e2e/website.spec.ts`

### Windows 上 `.claude/skills/` 符号链接检出为普通文本

- 状态：已解决
- 日期：2026-10-24
- 现象：Windows 检出后 `.claude/skills/numpy-analysis` 等是三十几字节的文本文件（内容是 `../../.agents/skills/...`），Claude Code 不会加载这些技能。
- 原因：Git for Windows 默认 `core.symlinks=false`，模式 120000 的条目检出成普通文件。
- 处理：不再用符号链接。`.claude/skills/` 改为 `.agents/skills/` 的真实副本，由 `python .agents/sync_skills.py` 生成，`tests/test_skills_sync.py` 检查两边一致（行尾按 LF 比较）。没有选"开发者模式 + `core.symlinks=true`"，因为它要求每台 Windows 机器单独设置。
- 位置：`.claude/skills/`、`.agents/sync_skills.py`、`tests/test_skills_sync.py`

### 找不到 OddsHarvester 或其输出 JSON 损坏时整批抓取中断

- 状态：已解决（data 1.5.0）
- 日期：2026-10-24
- 现象：`.venv-scrape` 缺失或爬虫中途被打断时，`collect` 抛 `FileNotFoundError` / `JSONDecodeError`，后面的联赛都不抓。
- 原因：`_with_retry` 只捕获 `RuntimeError` 和超时。
- 处理：`run_harvester` 把这两类异常转成 `RuntimeError`，走重试与跳过；`main` 抓取前先检查可执行文件，找不到时只打印已有数据。
- 位置：`football_prediction/data/oddsportal.py`

### 每日任务批处理含中文时 cmd 解析出错

- 状态：已解决
- 日期：2026-10-24
- 现象：`run_daily.bat` 写入 UTF-8 中文注释后，cmd 执行出错。
- 原因：cmd 按 GBK 解析批处理文件，UTF-8 中文字节会破坏后续行。
- 处理：`run_daily.bat` 只用 ASCII，行尾 CRLF。
- 位置：`run_daily.bat`

### 扩样本下载 football-data 老赛季时连接被重置

- 状态：已解决
- 日期：2026-10-24
- 现象：构建 `research.db` 时有 6 个联赛赛季下载报 ConnectionResetError。
- 原因：连续请求时服务端偶发断开。
- 处理：`csv_for` 先读 `_cache/fd_research`，下载失败退避重试 4 次。60 个联赛赛季全部入库。
- 位置：`_diag/expand/build_research_db.py`

### 裸跑 pytest 会收集参考目录并失败

- 状态：已规避
- 日期：2026-10-24 记入文档。命令约束此前已写在 `AGENTS.md`。
- 现象：仓库根目录执行 `pytest` 时，收集 `大模型项目/` 里依赖 torch 的测试，收集阶段失败。
- 原因：pytest 默认从当前目录向下收集，参考目录不是预测系统的测试。
- 处理：只跑 `python -m pytest tests`（用 `.venv` 时换成其中的解释器）。不把 `大模型项目/` 改成可收集，也不把 torch 加进预测依赖。
- 位置：`AGENTS.md` 的命令一节

### 升级队 Dixon-Coles 攻防参数发散

- 状态：已解决（model_dc 1.3.0）
- 日期：2026-10-24 记入文档。修复在 model_dc 1.3.0。
- 现象：德甲 2425 St Pauli 赛季初 `attack=-12.2`，月度回测 9 月 Log Loss 1.38。
- 原因：升级队样本少，极大似然没有约束时参数冲出合理范围。
- 处理：单队攻防参数向联赛均值做 L2 收缩，`shrink=0.5`。`shrink=0` 时与 v1.2.0 的结果一致。
- 位置：`football_prediction/model_dc/dixon_coles.py`

### LightGBM 两套重名方法让 alpha 交叉验证失效

- 状态：已解决（model_lgbm 1.1.0）
- 日期：2026-10-24 记入文档。修复在 model_lgbm 1.1.0。
- 现象：v1.0.0 的混合系数交叉验证没有按预期生效。
- 原因：同一类里两套重名的 `fit` / `predict`，实际走到的是不带 alpha 的那套。
- 处理：去掉重名方法。`fit()` 改为滚动样本外，alpha 在最接近测试期的一折上选择。
- 位置：`football_prediction/model_lgbm/lgbm_model.py`
