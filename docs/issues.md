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

### 临场档依赖电脑开机，且可能与每日任务争 SQLite 锁

- 状态：未解决
- 日期：2026-10-24（2026-10-25 更新）
- 现象：`*_t1`（market_*_t1、lineup_t1 / lineup_base_t1）只有在开球前 1.5 小时内跑过 `live --near` 才会存档。
- 原因：OddsPortal 多家赔率和 FotMob 正式首发都要临场抓；开赛集中在北京时间 19:30–05:00，电脑关机或睡眠时没有存档。`run_near.bat` 与 `run_daily.bat` 都写 `football.db` / `fotmob.db`，同一时刻运行可能报 `database is locked`。
- 处理：2026-10-25 建了计划任务 `FootballPredictNear`（每天 18:13 起每 30 分钟一次，到 05:43；单次上限 40 分钟，上一轮未完则跳过）。`init_db` 连接加 `timeout=BUSY_TIMEOUT`（120 秒），遇锁先等待而不是立即报错。仍要求开赛时段电脑开机、不睡眠；失败的一轮只会少存档，不会写错数据（存档只认首次，下一轮会补）。
- 位置：`run_near.bat`、`football_prediction/live.py`（`_run_near` / `_predict_near`）、`football_prediction/data/loader.py`（`BUSY_TIMEOUT`）

### understat robots.txt 为 `Disallow: /`，FotMob 使用条款未核验

- 状态：未解决
- 日期：2026-10-24
- 现象：understat 的 robots.txt 禁止全部路径；FotMob 的 robots.txt 只禁 `/api/` 等路径，但服务条款是否允许程序抓取没有核验。
- 原因：两者都是本项目 xG / 阵容的来源；understat 由用户确认照常使用（低频、已结束赛季缓存）。
- 处理：understat 抓不到时 `fotmob.backfill_xg` 补 `match_xg`。FotMob 只抓 HTML 页、间隔 3.5 秒、历史页缓存不重抓、只抓即将开赛或已完赛的联赛比赛。对方明确禁止或封禁时停用对应来源，不绕过。
- 位置：`football_prediction/data/understat.py`、`football_prediction/data/fotmob.py`

## 已解决

### 阵容调整系数还没有定

- 状态：已解决（model_lineup 1.1.0，系数定为 0）
- 日期：2026-10-24（2026-10-25 结论）
- 现象：`model_lineup/adjust.py` 的 `COEF_PRE` / `COEF_POST` 全为 0，`lineup_t1` 与 `lineup_base_t1` 相同。
- 原因：FotMob 历史补完后（E0 / D1 / SP1 2324–2526），2324–2425 拟合（1948 场）、2526 留出（1214 场）：叠在赛前赔率上（COEF_PRE）四个系数都在 2 个 SE 以内，留出对未调整 +0.00075±0.00100；叠在收盘赔率上（COEF_POST）留出 +0.00072±0.00072。两者都略差、不显著，三联赛分别看也没有一个显著更好。阵容信息基本已在赔率里（留出收盘对赛前 −0.0019±0.0016）。
- 处理：两套系数保持 0，不写入。合并规则留在代码里（赔率早于首次正式首发用 COEF_PRE，否则 COEF_POST）；`lineup_t1` / `lineup_base_t1` 照常并行存档，实盘 `horizon_report` 若出现显著差异再重估并升版本。注意实盘「赔率晚于首发」多是首发公布后几秒抓的，与拟合 COEF_POST 用的收盘赔率不完全对应，将来写入非零系数前要核对。
- 位置：`football_prediction/model_lineup/adjust.py`、`_diag/explore/lineup_fotmob_eval.py`（`lineup_fotmob_eval.log`）

### 意甲 / 法甲的信心档命中率是三联赛标定的

- 状态：已解决（output 1.3.0）
- 日期：2026-10-25
- 现象：报告里意甲、法甲场次的信心档后面的历史命中率（如「高[73%/90%]」）与英超、德甲、西甲共用一套数字。
- 原因：`MARKET_TIERS` 是在 E0 / D1 / SP1 上按市场概率分档标定的，加入 I1 / F1 时没有重标。
- 处理：在 `research.db` 5 联赛 1213–2425（23,488 场）上按 Shin 去水的首选概率重标：高 72%/89%、中 52%/79%、低 41%/71%；2526 留出 72.5%/89.7%、49.9%/79.2%、42.8%/70.0%。各联赛同档首选命中率相差不超过 4pp；联赛、赛季初、升级队对市场概率的修正在留出期都不显著，所以不分联赛。报告另列「本场估计（首选/双选）」= Shin 概率。见 `_diag/explore/reliability.log`。
- 位置：`football_prediction/output/analysis.py`（`MARKET_TIERS`）、`_diag/explore/reliability.py`

### 老赛季 CSV 部分行带多余空列，被整行跳过

- 状态：已解决（研究库脚本，2026-10-25）
- 日期：2026-10-25
- 现象：研究库扩到 9394 起时，F1 0203 只读到 191 / 380 场，I1 0304 194 / 306 场，另有 E0 0304–0405、D1 0203–0304、F1 0304、I1 0405、SP1 0405 各缺几十到一百多场。
- 原因：这些 CSV 有些行比表头多出几个字段，多出的都是空值；`pd.read_csv(on_bad_lines="skip")` 把这些行整行丢掉。
- 处理：`build_research_db.py` 改用 python 引擎，把多出的字段截到表头宽度，不再丢行。重建后除 F1 1920（疫情提前结束，279 场）外每季场数齐全。实盘只用 2122 起的 CSV，没有这种行，实盘读取未改。
- 位置：`_diag/expand/build_research_db.py`（`csv_for`）

### CSV 只有射门没有射正时 `load_season` 报 KeyError

- 状态：已解决（data 1.6.0）
- 日期：2026-10-25
- 现象：研究库导入 D1 0304、0405、0506 时 `KeyError: 'home_sot'`，整季没有写入。
- 原因：这几季 CSV 有 `HS/AS`、没有 `HST/AST`；`load_season` 只判断统计列非空就按四列取值。
- 处理：四列都在且非空才写 `match_stats`，否则只写赛果和赔率。加测试 `test_load_season_partial_stats_columns`。
- 位置：`football_prediction/data/loader.py`（`load_season`）

### 由赔率反推 λ 在高 λ 时偏差约 0.005

- 状态：已解决（model_dc_market 1.0.0 发布前修复）
- 日期：2026-10-24
- 现象：`lambdas_from_odds` 对 λ≈2.9 的合成泊松赔率反推出的 λ 偏 0.005。
- 原因：比分网格只到 10 球（`_MAXG=11`），λ≈3 时截掉的概率约 0.0002，1X2 之和小于 1。
- 处理：`_MAXG` 改为 16，测试辅助函数同步。用新网格重跑 `_diag/explore/dc_market.py`，log loss 只在第五位小数变化，w=0.3 的结论不变。
- 位置：`football_prediction/model_dc/market_dc.py`、`tests/test_models.py`

### FotMob `/matches/<slug>` 返回的不是要的那场

- 状态：已解决（data_fotmob 1.0.0）
- 日期：2026-10-24
- 现象：用赛程里的 `/matches/<slug>` 取页面，得到的是两队最近一场，赛季和比分都对不上。
- 原因：去掉 `#id` 后 FotMob 按对阵跳到最近一场。
- 处理：取页面时带上比赛 id，并核对页面 matchId，对不上就丢弃。
- 位置：`football_prediction/data/fotmob.py`（`fetch_match`）

### data 层两个文件超过 400 行

- 状态：已解决（拆分不改行为，data 仍为 1.5.0）
- 日期：2026-10-24
- 现象：`data/loader.py`、`data/oddsportal.py` 各 418 行，超过 `docs/modules.md` 的上限。
- 原因：v1.4.0 / v1.5.0 加快照、亚盘和爬虫时没有先拆文件。
- 处理：赛程与快照（`load_fixtures`、`save_snapshots`、`odds_movement`、`_FIX_ODDS_COLS`）移到 `data/fixtures.py`，调用方改为从这里导入；队名配对与 OddsHarvester 输出解析移到 `data/oddsportal_parse.py`，`oddsportal.py` 重新导出原名字。拆后 loader 327 行、oddsportal 约 270 行。
- 位置：`football_prediction/data/loader.py`、`fixtures.py`、`oddsportal.py`、`oddsportal_parse.py`

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
