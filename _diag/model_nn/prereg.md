# model_nn G1 预注册（留出 2526）

按 `docs/agent-plan.md` 9.1 写，在任何 2526 评估之前单独提交一次。提交之后不改本文件；`holdout.py` 读下面的 toml 块，每个检验只跑一次。

## 数据

- 冻结副本 `checkpoints/g1/football_20261027.db`：SQLite backup 接口从 `football.db` 复制，只读；md5 `741fe073a526afce46fb55e50420904a`，最晚一场 2026-10-21。选参和留出都只用这一份。
- 留出：2526 全季已完赛场次。五联赛 1752 场（2025-08-15 – 2026-05-24），六联赛 2009 场（2025-07-25 – 2026-05-24），都有赛前平均赔率。
- `eval_log.md` 里本文件提交之前没有任何 2526 的范围（选参只用 2425，脚本里断言）。

## 检验家族

一个家族，m = 4，家族合计单侧 α = 2.28%，Bonferroni 后每个检验 α = 0.57%，z = 2.54（`norm.isf(0.02275/4)` = 2.531，向上取两位）。主指标是 1X2 log loss 的同场差值（候选 − 对照），通过条件：差值 + 2.54 × SE < 0。Brier、比分 log loss、亚盘五种结算 log loss、按联赛 / 按月的结果只作描述，不参与判定。每个联赛组合并成一个总体，不按单个联赛判定。每个检验单独生效。

| 检验 | 联赛组 | 候选 | 对照 |
|---|---|---|---|
| T1 | 五联赛 E0 / D1 / SP1 / I1 / F1 | B/no_xg h32 d0.3 | `market_implied` |
| T2 | 五联赛 | A/full h128-64 d0.1 lr3e-4 | `dc_market` |
| T3 | 六联赛 E1 / N1 / P1 / SC0 / B1 / T1 | B/no_xg h32 d0.3（同 T1） | `market_implied` |
| T4 | 六联赛 | A/no_xg h64-32 d0.1 | `dc_market` |

B 的主配置本身是 `no_xg`，T3 用同一个配置。A 的主配置是 `full`，T4 用五联赛 2425 上 A 最好的 `no_xg` 配置，与主配置同时冻结。六联赛不重选任何超参。

## 训练与评估规则（上线时原样使用）

- 训练窗口：从 2122 起全量，`match_date < cutoff`；每月 1 日重训一次，预测该月场次。留出时五联赛用 2122–2425 和 2526 当月之前的场次，六联赛同样。
- 联赛合并：同一联赛组的联赛合并训练（`pool = "group"`）。
- 特征：每场按它自己的日期生成（同日互不可见），`FEATURES_VER = "1"`；xG 用 `match_xg`（understat，缺的由 FotMob 补），只有 `full` 用。B 另加该场赛前平均赔率（`Avg*`，不用收盘价）的去水概率、亚盘线与市场隐含 λ。
- 训练轮数：不固定成一个数。每次重训先在训练窗口最后 120 天上早停（patience 15，最多 200 轮）得出轮数，再用同一种子在整个窗口上训练这么多轮。2425 选参时平均 4–11 轮。
- 种子 0，CPU（MPS 在 2425 上慢约 2.5 倍，结果也不逐位相同）。
- 对照：`market_implied` 用同一行的赛前平均赔率反推 λ，rho = `DEFAULT_RHO`（−0.05），不拟合。`dc_market` 每个联赛**每个比赛日**按当天之前的场次重拟合。这一点与方案写的「按月 cutoff」不同：候选的特征逐场更新，按月冻结的 `dc_market` 会让 A 占时效便宜；2425 上按月改成逐日，`dc_market` 的 1X2 LL 从 0.98157 降到 0.97919，A/full 的领先从 −0.00673 缩到 −0.00434。实盘里 `dc_market` 每轮都重拟合，逐日更接近实盘。
- 指标函数：`validation.backtest` 的 `_log_loss_one`、`_brier_one`、`paired_compare`；亚盘用 `derive.ah_outcome` 与 `review.store.ah_settle`，线取该场赛前市场线。

## 选参依据（2425，五联赛 1752 场，同场 1X2 LL 差值 ± SE）

| 配置 | 种子 0 | 种子 1 | 种子 2 | 对照 |
|---|---|---|---|---|
| B/no_xg h32 d0.3 | −0.00324±0.00106 | −0.00284±0.00091 | −0.00308±0.00097 | market_implied |
| A/full h128-64 d0.1 lr3e-4 | −0.00673±0.00309 | −0.00826±0.00327 | −0.00802±0.00310 | dc_market（按月） |
| A/no_xg h64-32 d0.1 | −0.00411±0.00309 | −0.00372±0.00309 | −0.00409±0.00320 | dc_market（按月） |

dc_market 改为逐日后（种子 0）：A/full −0.00434±0.00292，A/no_xg −0.00173±0.00294。B 的输入全部置 0（只剩对市场 λ 与 rho 的校准）是 −0.0007 左右，只留市场列是 −0.0009 到 −0.0011；完整输入的约 −0.003 里大部分来自球队特征。网格共 96 个配置，2425 的数字有选择偏差，留出上的差值预计更小。全部记录在 `select.log`。

## 冻结

```toml
[frozen]
path = "checkpoints/g1/football_20261027.db"
md5 = "741fe073a526afce46fb55e50420904a"
features_ver = "1"
layer_version = "0.1.0"

[holdout]
season = "2526"

[[tests]]
id = "T1"
group = "five"
baseline = "market_implied"
z = 2.54
config = { variant = "B", feature_set = "no_xg", hidden = [32], dropout = 0.3, weight_decay = 1e-4, lr = 1e-3, batch_size = 256, max_epochs = 200, patience = 15, val_days = 120, refit = true, first_season = "2122", pool = "group", seed = 0, device = "cpu" }

[[tests]]
id = "T2"
group = "five"
baseline = "dc_market"
dc_market_refit = "daily"
z = 2.54
config = { variant = "A", feature_set = "full", hidden = [128, 64], dropout = 0.1, weight_decay = 1e-4, lr = 3e-4, batch_size = 256, max_epochs = 200, patience = 15, val_days = 120, refit = true, first_season = "2122", pool = "group", seed = 0, device = "cpu" }

[[tests]]
id = "T3"
group = "six"
baseline = "market_implied"
z = 2.54
config = { variant = "B", feature_set = "no_xg", hidden = [32], dropout = 0.3, weight_decay = 1e-4, lr = 1e-3, batch_size = 256, max_epochs = 200, patience = 15, val_days = 120, refit = true, first_season = "2122", pool = "group", seed = 0, device = "cpu" }

[[tests]]
id = "T4"
group = "six"
baseline = "dc_market"
dc_market_refit = "daily"
z = 2.54
config = { variant = "A", feature_set = "no_xg", hidden = [64, 32], dropout = 0.1, weight_decay = 1e-4, lr = 1e-3, batch_size = 256, max_epochs = 200, patience = 15, val_days = 120, refit = true, first_season = "2122", pool = "group", seed = 0, device = "cpu" }
```
