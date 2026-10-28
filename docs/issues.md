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

### 中转站模型 id 改成小写开头后 Agent 全部 404

- 状态：未解决（等用户改 `.env`）
- 日期：2026-10-28
- 现象：`agent.eval.agent --run` 29 题全部 `error`，花费 0；报「模型调用失败：404」。
- 原因：中转站 `/models` 现在只列出 `deepSeek-v4.1-flash-1017`（d 小写）；按旧写法 `DeepSeek-v4.1-flash-1017` 请求返回 `model_not_found`（"not available for this group"）。模型名区分大小写，2026-10-27 用旧写法能调通。
- 处理：`agent/prices.toml` 追加新写法一条（单价沿用，旧条目保留）；本机用环境变量 `AGENT_MODEL=deepSeek-v4.1-flash-1017` 覆盖后调通。`.env` 里的 `AGENT_MODEL` 由用户改成新写法后本条移到已解决。同一轮里通过率比 2026-10-27 第二轮明显低（大多数题被第 1、2 条打回后降级），中转站背后是否换了模型未查清。
- 位置：`.env`（用户维护）、`agent/prices.toml`

### model_nn 评估时个别场次的候选比分矩阵是 NaN

- 状态：未解决
- 日期：2026-10-27
- 现象：G1 留出 T1（五联赛 B）候选 1747 场有 1X2 log loss，对照 1752 场；运行时 `model_market/implied.py:32` 报一次 `invalid value encountered in divide`。
- 原因：未查清。推断是候选输出的 λ 与 rho 让 `dc_matrix` 的 DC 修正项为负或矩阵和为 0：训练损失 `net.dc_nll` 把 tau 截断在 1e-6 以上，评估与 `NNModel.score_matrix` 用的 `dc_matrix` 没有截断。
- 处理：未处理。这几场被 `paired_compare` 的配对剔除，只会让候选看起来更好，T1 不通过的结论不变。下次在新留出集上评估前，先让评估和训练用同一套截断（或限制 rho 使修正项恒为正），并让 NaN 计为失败而不是剔除；这属于改算法，要升 `model_nn` 的 `LAYER_VERSION`。
- 位置：`football_prediction/model_nn/model.py`、`football_prediction/model_nn/net.py`、`_diag/model_nn/evaluate.py`

### 联赛增加后每日任务和临场档的抓取时间变长

- 状态：未解决
- 日期：2026-10-25
- 现象：2026-10-24 两次每日任务各约 26 分钟，其中时间窗内 15 场的 OddsPortal 抓取占大头。加入六个联赛后同一时间窗的场次会多一到两倍。
- 原因：OddsHarvester 逐页打开浏览器抓取，耗时随场次线性增长。`FootballPredictNear` 单次上限 40 分钟，周末同一开球时段（如北京时间 23:00）场次集中。
- 处理：未处理。先看 11 个联赛下 `logs/daily.log`、`logs/near.log` 的实际耗时；临场档超时被杀只会少存档 `*_t1`，不会写错数据。若超时，可选：临场档只抓部分联赛、调大计划任务上限，或把每日的 `--hours 30` 缩短。
- 位置：`run_daily.bat`、`run_near.bat`、`football_prediction/data/oddsportal.py`

### 临场档依赖电脑开机，且可能与每日任务争 SQLite 锁

- 状态：未解决
- 日期：2026-10-24（2026-10-25、2026-10-26 更新）
- 现象：`*_t1`（market_*_t1、lineup_t1 / lineup_base_t1）只有在开球前 1.5 小时内跑过 `live --near` 才会存档。
- 原因：OddsPortal 多家赔率和 FotMob 正式首发都要临场抓；开赛集中在北京时间 19:30–05:00，电脑关机或睡眠时没有存档。`run_near.bat` 与 `run_daily.bat` 都写 `football.db` / `fotmob.db`，同一时刻运行可能报 `database is locked`。
- 处理：2026-10-25 建了计划任务 `FootballPredictNear`（每天 18:13 起每 30 分钟一次，到 05:43；单次上限 40 分钟，上一轮未完则跳过）。`init_db` 连接加 `timeout=BUSY_TIMEOUT`（120 秒），遇锁先等待而不是立即报错。仍要求开赛时段电脑开机、不睡眠；失败的一轮只会少存档，不会写错数据（存档只认首次，下一轮会补）。2026-10-26 核对：三个任务都 `WakeToRun=False`，电池供电时 10 分钟无操作就睡眠，睡眠期间的轮次不会跑；`FootballPredictDaily_2337` 10-25 那次结果 0xC000013A（进程被中断，控制台关闭或 Ctrl+C 一类），已手动补跑，10-26 18:07 每日任务与临场档结果都是 0。要提高覆盖，需接电源并关闭睡眠，或给任务打开「唤醒计算机运行」（未改，属于用户的电源设置）。
- 位置：`run_near.bat`、`football_prediction/live.py`（`_run_near` / `_predict_near`）、`football_prediction/data/loader.py`（`BUSY_TIMEOUT`）

### understat robots.txt 为 `Disallow: /`，FotMob 使用条款未核验

- 状态：未解决
- 日期：2026-10-24
- 现象：understat 的 robots.txt 禁止全部路径；FotMob 的 robots.txt 只禁 `/api/` 等路径，但服务条款是否允许程序抓取没有核验。
- 原因：两者都是本项目 xG / 阵容的来源；understat 由用户确认照常使用（低频、已结束赛季缓存）。
- 处理：understat 抓不到时 `fotmob.backfill_xg` 补 `match_xg`。FotMob 只抓 HTML 页、间隔 3.5 秒、历史页缓存不重抓、只抓即将开赛或已完赛的联赛比赛。对方明确禁止或封禁时停用对应来源，不绕过。
- 位置：`football_prediction/data/understat.py`、`football_prediction/data/fotmob.py`

## 已解决

### 本机有 `web/.env.local` 时 e2e 读到实盘接口

- 状态：已解决（前端测试配置，不涉及层版本）
- 日期：2026-10-28
- 现象：`npm run test:e2e` 失败 13 条，首页显示「本机实盘」和实盘场次，而不是演示样本（断言找不到「阿森纳」）。
- 原因：实盘机的 `web/.env.local`（gitignore）配置了 `API_URL`，`next start` 启动时会自动加载它。`playwright.config.ts` 覆盖了 `AGENT_SERVE_URL` 和 `AGENT_SERVICE_TOKEN`，但没有覆盖 `API_URL`，127.0.0.1:8000 上的接口又在运行，于是 e2e 读到了实盘数据。
- 处理：在 e2e 网站进程的 env 里显式写 `API_URL: ""`。`@next/env` 不覆盖进程里已有的变量，空值让 `apiBase()` 回到演示样本。之后 29 条全部通过。
- 位置：`web/playwright.config.ts`

### 检索评测集有 7 条题在 main 上核对不通过

- 状态：已解决（评测集，不涉及层版本）
- 日期：2026-10-27
- 现象：在 Windows 实盘机上跑 `python -m agent.kb --eval`，报「评测集核对不通过」：r17、r23、r24、r31、r39、r57、r79 的 gold 块在 as_of 2026-10-27 05:00 时不可见。
- 原因：`agent/kb/sources.py` 沿 `git log --first-parent` 取文档版本。PR #4 是在 fork 上按线性历史写的，as_of 按 fork 上的提交时间定。合并进 main 后，第一父历史里只有 13:47 的合并提交，PR 新加的文档段落从这个时间才可见。后来撤回（16:24）再恢复（16:28），又把这些段落记成新的一版。
- 处理：把这 7 条的 as_of 改到 2026-10-27 15:00（合并之后、撤回之前）。其余题不受影响。以后要在 main 上评测从分支合入的文档，as_of 应按合并提交的时间定。
- 位置：`agent/eval/retrieval.jsonl`、`agent/kb/sources.py`

### 下载 bge-m3 时 Hugging Face 的 xet 传输卡住

- 状态：已解决（环境，不涉及层版本）
- 日期：2026-10-27
- 现象：在 Windows 实盘机上用 `snapshot_download` 下载 `pytorch_model.bin`。文件停在 268,333,489 字节，8 分钟以上没有增长；进程占用约 2.1 GB 内存，CPU 不动。
- 原因：未查清。默认走 xet 后端时出现；本机经代理访问 HF。
- 处理：结束进程，删掉 `.lock` 文件，设 `HF_HUB_DISABLE_XET=1` 重新运行，改走 HTTP 后从断点续传完成，约 5 MB/s。`docs/stack.md` 的下载说明已加这一条。
- 位置：`docs/stack.md`（向量模型下载）

### Windows 上 Agent 数字校验放过「两成」「两倍」

- 状态：已解决（未升版本，`agent/` 不在 `LAYER_VERSIONS` 里）
- 日期：2026-10-27
- 现象：Windows 实盘机合并 PR #4 后，`python -m pytest tests` 有 3 项失败：`test_agent_facts.py` 的 `test_number_spellings_rejected[两成]`、`test_allow_list_does_not_hide_quantities[两档-两]`、`[两倍标准误-两]`，`find_numbers` 对含「两」的数量返回空。Mac 上同一份测试通过。
- 原因：`_is_num` 靠 `unicodedata.numeric` 判断数值字符。这台机器是 Python 3.12.10（Unicode 15.0），`unicodedata.numeric("两")` 报 not a numeric character；Mac 的 `.venv-ml` 是 Python 3.14（Unicode 更新，「两」有数值）。结果是 Agent 回答里「两成」这类没走事实的数量在 3.12 上不会被打回。
- 处理：`agent/facts/numbers.py` 把「两 / 兩」和「半」一起列进 `_EXTRA_NUM`，不再依赖 Unicode 版本。修后本机 395 passed、12 skipped。
- 位置：`agent/facts/numbers.py`、`tests/test_agent_facts.py`

### FotMob 历史赛季有 7 个队名配不上

- 状态：已解决（data_fotmob 1.2.1）
- 日期：2026-10-27
- 现象：11 联赛 2122–2526 的 FotMob 赛程 16064 场完赛里 632 场配不上 match_id，集中在英冠（每季约 50 场）、葡超、法甲、比甲、土超。
- 原因：`team_map` 的相似度低于 `TEAM_MIN` 0.9：Sheffield Wednesday / Sheffield Weds 0.84、AVS Futebol SAD / AVS 0.38、Saint-Étienne / St Etienne 0.86、Adana Demirspor / Ad. Demirspor 0.88、Bodrum FK / Bodrumspor 0.67、RWDM Brussels / RWD Molenbeek 0.50、Cova da Piedade SAD / Belenenses（football-data 2122 的叫法）0.23。
- 处理：在 `FOTMOB_ALIASES` 补这 7 个。补后剩 103 场配不上，都是 FotMob 有、football-data 没有的场次（比甲附加赛每季 24 场，英冠 / 荷甲升级附加赛每季 3–7 场），不用配。
- 位置：`football_prediction/data/fotmob_parse.py`

### Mac 上默认的 Node 26 跑 Vitest 全部失败

- 状态：已解决（不改代码）
- 日期：2026-10-27
- 现象：在 `web/` 用 shell 默认的 `node`（v26.8.2，`~/.local/bin/node`）跑 `npx vitest run`，12 个文件 60 项全部失败，报 `localStorage` 为 undefined（`tests/setup.ts` 的 `localStorage.clear()`）。
- 原因：项目要求 Node 24 LTS（`package.json` 的 `engines` 为 `>=24 <25`）；Node 25 起自带的全局 `localStorage` 遮住了 jsdom 的实现。
- 处理：用 Node 24 跑前端检查，Mac 上是 `PATH=/opt/homebrew/opt/node@24/bin:$PATH`（v24.22.1）；换成 Node 24 后 60 项全部通过。不为 Node 26 改测试。
- 位置：`web/package.json`、`web/tests/setup.ts`

### `.venv-ml` 里 `pytest tests` 在 model_nn 的 torch 测试处段错误

- 状态：已解决（未升版本，只改测试）
- 日期：2026-10-27
- 现象：Mac 上 `.venv-ml/bin/python -m pytest tests` 跑到 `test_model_nn.py` 第一个 torch 测试时进程退出（139，`Fatal Python error: Segmentation fault`，没有栈）。单独跑 `test_model_nn.py` 通过；先跑 `test_agent_kb.py` 里任一个建索引的测试再跑它就复现。`.venv` 不受影响（torch 测试跳过）。
- 原因：未完全查清。`OMP_NUM_THREADS=1` 时不崩，`KMP_DUPLICATE_LIB_OK=TRUE` 仍崩；`.venv-ml` 里 torch、sklearn、faiss 各带一份 `libomp.dylib`。只建一个 Milvus Lite 集合再跑 torch 的最小脚本不崩，所以与知识库测试里具体哪一步有关没有定位。
- 处理：`tests/test_model_nn.py` 加 autouse fixture，torch 测试前 `torch.set_num_threads(1)`；`.venv-ml` 440 passed。选参和留出脚本不加载 Milvus，照常多线程。以后别的测试在同一进程里同时用 Milvus 和 torch 时同样处理。
- 位置：`tests/test_model_nn.py`

### 知识库检索偶尔返回「正在被另一个进程使用」

- 状态：已解决（未升版本，`agent/` 不在 `LAYER_VERSIONS` 里）
- 日期：2026-10-27
- 现象：P3 第一轮真实评测里 `kb_search` 两次返回「知识库正在被另一个进程使用」，当时没有 `--rebuild` / `--update` 在跑；同一轮紧接着的另一次检索正常。日志里同时有 gRPC `GOAWAY ... too_many_pings` 和 `Fail connecting to server on 127.0.0.1`。
- 原因：Milvus Lite 在本进程里起本地服务，客户端的 gRPC 连接偶尔被对端以 `too_many_pings` 断开，新建 `MilvusClient` 时重连失败抛 `MilvusException`；`_client` 把所有打开失败都当成「另一进程锁着目录」。
- 处理：打开失败隔 1 秒重试一次（`OPEN_ATTEMPTS`、`OPEN_WAIT`），两次都失败才报 `KBBusy`；测试模拟第一次失败、第二次成功。第二轮评测 gRPC 断开仍出现 3 次，都由重试接住，没有再返回这句说明。
- 位置：`agent/kb/index.py`、`tests/test_agent_kb.py`

### Mac 的 `.venv` 没装 httpx，接口测试被跳过

- 状态：已解决（依赖未变，只补装本机 `.venv`）
- 日期：2026-10-27
- 现象：Mac 上 `.venv/bin/python -m pytest tests -q` 是 210 passed、1 skipped，跳过原因 `tests/test_server.py:11: could not import 'httpx'`，`test_server.py` 的 8 项都没跑。同一份测试在装齐 `requirements.txt` 的 `.venv-ml` 里是 218 passed。
- 原因：`requirements.txt` 的 `httpx==0.28.1` 是 2026-10-26 提交 `7f2aba5` 加的；Mac 的 `.venv` 建于 2026-10-24（`pyvenv.cfg` 修改时间），之后没按新的 `requirements.txt` 重装。Windows 实盘机的 `.venv` 有没有装，未核对。
- 处理：2026-10-27 经用户同意，`.venv/bin/python -m pip install -r requirements.txt -c <当时的 pip freeze>`（锁住已有包的版本），只多装了 httpx 0.28.1 和 httpcore 1.0.9，`pip check` 无冲突。Mac 上 `.venv` 和 `.venv-ml` 都是 218 passed。`.venv` 里有一条 Starlette 的弃用提示（`starlette.testclient` 建议用 `httpx2`），不影响结果。Windows 实盘机拉取后自行核对，见 `docs/agent-dev.md` 第 3 节。
- 位置：`.venv`（本机）、`requirements.txt`、`tests/test_server.py`、`constraints-ml.txt`

### 新增六个联赛没有历史 xG，dc_xg 在这些联赛基本等于进球版

- 状态：已解决（output 1.7.0 / 系统 1.12.0）
- 日期：2026-10-25
- 现象：英冠 E1、荷甲 N1、葡超 P1、苏超 SC0、比甲 B1、土超 T1 的 2122–2526 在 `match_xg` 里是 0 场。
- 原因：understat 只有英超、德甲、西甲、意甲、法甲（`understat.US_LEAGUES`）。FotMob 只补抓了 2627（每日 `data.fotmob` 抓当前赛季），`backfill_xg` 只补已抓的场次。xg_dc 缺 xG 时用进球代替。
- 处理：主模型是 `market_implied`，这些联赛 football-data 的赔率齐全（只有 T1 2223 缺 29 场），报告不受影响；受影响的是无赔率时的兜底和并行存档的 dc_xg。可选两条路：`python -m football_prediction.data.fotmob --leagues E1,N1,P1,SC0,B1,T1 --history 2425,2526` 补历史（每季约 2000 页，两季按 3.5 秒间隔约 4 小时）；或读 football-data 2627 起新增的 `HxG` / `AxG` 列（11 个联赛 2627 都有，2526 及以前没有）。2026-10-26：无赔率时的兜底改为 `dc_market`（进球 + 历史赔率估强度，不用 xG；11 联赛 2324–2627 对 blend −0.0060±0.0010，新六联赛 −0.0092±0.0015），兜底不再受缺 xG 影响；2627 的 xG 已由 FotMob 补齐，HxG 没有历史赛季，不接入。dc_xg 只剩并行存档，在这六个联赛 2122–2526 仍近似进球版。
- 位置：`football_prediction/data/understat.py`、`football_prediction/data/fotmob.py`、`football_prediction/model_dc/xg_dc.py`

### football-data 2526 起部分场次的赛前平均亚盘客队水位错误

- 状态：已解决（data 1.9.0）
- 日期：2026-10-26
- 现象：`football.db` 的 `match_odds` 里有 78 场（2526 有 77 场，2627 有 1 场，比赛日期从 2025-11-28 到 2026-10-18）`avg_aha` 约为 4.4，主队水位却正常（约 1.9），两边隐含概率加起来不到 1。`research.db` 2526 有 38 场同样的问题。2122–2425 没有这种行，收盘列（`avgc_ahh` / `avgc_aha`）也没有。用这些行反推，选择方赢盘概率会偏到 0.56 以上：2526 留出季亚盘「高」档的 37 场里有 36 场是坏行（命中 0.444）。`AH_TIERS` 注释里「高 0.457（n=35），未确认」那一项因此不能作为高档失效的证据。实盘存档用的是赛程表和多家赔率，赛程表 102 行里没有这种行。
- 原因：源数据本身有误。`_cache/fd_research/E0_2526.csv` 里 Brentford–Burnley 一行 `AvgAHA` = 4.32，`MaxAHA` = 22.0，而 B365、Pinnacle、Betfair 交易所的客队水位都在 1.83–1.87。推断是某一家公司挂了异常赔率，把平均值拉高了。入库时没有检查两边水位是否合理。
- 处理：data 1.9.0 起入库前检查每组赔率（`loader.clean_odds` / `bad_market`）：胜平负、大小 2.5、亚盘（赛前 / 收盘 / Pinnacle / B365）各项隐含概率之和 < 1 时整组当作缺失，亚盘连盘口线一起；`fixtures.csv` 赛程赔率同样处理，多家中位数 `book_consensus` 的胜平负 / 大小 2.5 也这样处理，亚盘不选这样的线（`book_odds` 逐家原始赔率照存）。用本地 `_cache/fd_raw` 的 2526 / 2627 CSV 核对，新规则剔除的正好是库里已有的坏行：亚盘 78、胜平负 1、收盘胜平负 2、大小 2.5 1、收盘大小 2.5 2、Pinnacle 收盘 1，别的行不动。库里已有的这些行按「只补不改」不改写；它们只被研究脚本读（实盘存档用赛程表和多家赔率，两者当前都没有坏行），研究脚本继续用 `1/avg_ahh + 1/avg_aha >= 1` 过滤，或用 `loader.bad_market` 判断。`research.db` 用 `load_season` 重建时会自动剔除。
- 原先的可选做法与复核：入库或反推时把两边隐含概率和小于 1 的亚盘水位当作缺失（data 层行为变化，要升版本）；研究脚本先用 `1/avg_ahh + 1/avg_aha >= 1` 过滤。剔除坏行后，football.db 2122–2627 里亚盘「高」档只有 8 场，「中」档命中 0.599（2122–2425，n=601）和 0.586（2526–2627，n=174）。稳妥线基本不受影响（`_diag/explore/ah_clean_recheck.py`）：research.db 留出 2526 命中 0.674 → 剔除后 0.677，football.db 2526–2627 0.671 → 0.672。同类「两边隐含概率和 < 1」在胜平负 2526 各库有 1 行、大小 2.5 research.db 1819 有 1 行，影响可忽略。
- 位置：`football_prediction/data/loader.py`（`clean_odds`）、`football_prediction/data/fixtures.py`、`football_prediction/data/oddsportal.py`（`book_consensus`）、`football_prediction/output/analysis.py`（`AH_TIERS` 注释）、`_diag/algo_sweep/`、`_diag/explore/ah_clean_recheck.py`

### 临场档在开球后才存档，多家赔率的抓取时间记早了

- 状态：已解决（data 1.8.0 / review 1.7.0 / live 1.10.1）
- 日期：2026-10-26
- 现象：Sparta Rotterdam – Ajax（`d6878bf5e28f44ec`，开球 2026-10-25 15:45 UTC）的 `lineup_t1` / `lineup_base_t1` 在 16:08 存档，已开球 23 分钟。库里开球后才存的只有这 2 行；`book_odds` 没有记在开球后的行，但这一批的 `fetched_at` 比实际抓回时间早。
- 原因：临场档 15:43 开始，`now` 在一轮开始时定下，窗口判断和"未开球"都按它算；OddsPortal 抓取约 25 分钟，阵容档在抓完后才存。`collect` 把整批的 `fetched_at` 都记成开始时刻，赔率新鲜度（90 分钟）因此偏宽。
- 处理：`services.round_clock` 给每轮一个随真实时间走的时钟，`predict_upcoming` / `predict_near` 存档前按它重新判断，已开球就跳过；`save_prediction` 新增 `at`，`generated_at` 记真实存档时刻，`extra.kickoff_utc` 不晚于它时不存。`oddsportal.collect` 的 `fetched_at` 改为每组抓回时刻，抓回时已开球的场次不入库。旧行不删，成绩单与 `promotion_check` 的 `_scored_first` 排除 `generated_at ≥ kickoff_utc` 的行。
- 位置：`football_prediction/services/live_round.py`（`round_clock`）、`football_prediction/services/near_round.py`、`football_prediction/review/store.py`（`started` / `save_prediction`）、`football_prediction/review/scorecard.py`、`football_prediction/data/oddsportal.py`

### football-data 赛果晚几天，实盘评分一直落后

- 状态：已解决（review 1.5.0 / data_fotmob 1.1.0 / live 1.8.0）
- 日期：2026-10-25
- 现象：2026-10-25 检查时 `predictions` 已评分 0 条；存档覆盖 10-23 至 10-26 的场次，而 `matches` 最新赛果是 10-21。成绩单和 `promotion_check` 拿不到样本。
- 原因：评分只认 `matches`，而 `matches` 只来自 football-data 赛季 CSV，它在完赛后数天才更新。
- 处理：`live` 更新数据时抓 FotMob 各联赛页的完赛比分写入 `fotmob.db` 的 `fotmob_results`（不进 `matches`，不影响模型拟合）；`matches` 没有赛果时先用它评分（`result_src='fotmob'`），football-data 到达后 `reconcile_results` 核对，不一致按 football-data 重评并在日志里打印。判负 / 取消的场次不取。成绩单和 `promotion_check` 取已评分预测时原先 `JOIN matches`，会漏掉 FotMob 先评的场次，已去掉这个 JOIN（复制库实测：14 场进入成绩单）。
- 位置：`football_prediction/data/fotmob.py`（`collect_results`）、`football_prediction/review/store.py`（`score_predictions` / `reconcile_results`）、`football_prediction/live.py`

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
