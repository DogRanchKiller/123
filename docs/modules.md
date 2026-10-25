# 模块化规范

本文件是目录边界、调用方向和单文件尺度的唯一规范。技术选型见 [stack.md](stack.md)。训练、版本和预测规则见 [ml-stack.md](ml-stack.md) 与 `AGENTS.md`。

两人同时改这个仓库时，按目录认领，按下面的箭头调用。不要把规则记在聊天里。

## 三层

调用只有一个方向：

```
web  --HTTP-->  server  -->  services  -->  领域包
live.py / main.py  --------^
```

| 层 | 目录 | 做什么 | 不做什么 |
|---|---|---|---|
| 前端 | `web/` | 展示、发请求、把 OpenAPI 类型交给页面 | 不算概率，不读 `football.db`，不引用 Python |
| 后端 | `server/` | FastAPI 路由、Pydantic 校验、HTTP 状态 | 不写 SQL，不 `fit`，不编排多个模型 |
| 中间层 | `football_prediction/services/` | 一个用例一份编排：实盘一轮、回测一轮、给接口读的报告和成绩单 | 不 import FastAPI，不渲染页面 |
| 领域 | `football_prediction/` 里除 `services/` 以外的包 | 数据、特征、模型、校准、市场分解、落库、回测指标 | 不 import `server`、`web`、`services` |

前端和后端是两个目录、两个进程。中间层是两边的唯一业务入口：`server/` 的路由和命令行入口都调用它，不再各写一套「更新数据 → 评分 → 预测 → 报告」。

`server/` 和 `services/` 还没有。开始写 `server/` 的那一次改动里同时建立 `services/`，把 `live.py` 的编排挪进 `services/live_round.py`，把 `main.py` 的编排挪进 `services/backtest_run.py`。入口文件只保留参数、打印和调用。在那之前，`live.py`、`explain.py` 和 `main.py` 临时充当中间层。不要先建空包，也不要在路由里抄一份 `live.py`。

现有的两处例外，建 `services/` 时一并处理，在那之前不要新增同类引用：

- `output/pipeline.py`（`ModelCache`、`analyse_match`）会拟合模型，是报告和 `explain.py` 共用的编排，实际属于中间层。建 `services/` 时挪进去。
- `model_market/implied.py` 引用 `output/derive.py` 的亚盘结算函数（`margin_pmf`、`ah_outcome`、`ah_fair_prob`）来拟合市场隐含 λ。

## 领域包

一个包一种修改理由。新能力优先放进已有的包；只有出现第二种修改理由时才新开包。

| 包 | 修改理由 | 可以引用 | 不可以引用 |
|---|---|---|---|
| `data/` | 外部赛果、赔率、赛程、xG 如何进库 | 同包模块 | 特征、模型、报告、评分 |
| `features/` | 截止日之前的特征 | `data` 的表 | 模型、报告、评分 |
| `model_*/` | 一种预测模型怎么拟合和出概率 | `features`；同族变体可继承同包里的模型 | `review`、`output`、`live`、`server` |
| `calibration/` | 概率校准 | 已算好的概率 | 实盘主流程以外的新入口 |
| `output/` | 比分矩阵和报告长什么样 | 矩阵和已落库的预测 | 拟合、下载 |
| `review/` | 预测怎么落库、怎么赛后评分 | 已写入的概率 | 模型类 |
| `validation/` | 时间外回测和同场比较 | 模型、`output`、指标函数 | `save_prediction` |
| `services/` | 用例怎么把上面几包串起来 | 领域包的公开函数 | FastAPI、页面 |

同族变体留在同包。`model_dc/` 里的 Dixon-Coles、射正版、xG 版是同一比分模型的三种强度估计。新的模型族用新包 `model_<name>/`，不要塞进 `model_dc/`。

领域包之间的箭头不能反向。`data` 不能为了方便去调用模型。两个模型族需要同一段计算时，先让调用留在各自文件里；第二处真正出现后，再抽到一个用职责命名的模块。不要先建 `common.py`。

`大模型项目/` 不在这张依赖图里。任何层都不 import 它。

## 中间层的文件

按用例分文件，不按领域名词再切一层。

| 文件 | 用例 |
|---|---|
| `services/live_round.py` | 实盘一轮：更新数据、赛后评分、未开赛预测、主模型报告、成绩单、替换检查 |
| `services/backtest_run.py` | 回测演示：现在 `main.py` 里的串联 |

读接口如果只是把这一轮已经算好的报告或成绩单送出去，函数就放在 `live_round.py` 并在 `services/__init__.py` 再导出。出现第二种读法，或这个文件超过下面的行数上限时，再拆成第二个用例文件。

`services/__init__.py` 只做再导出。路由和命令行从 `football_prediction.services` 引用用例函数，不从领域包里自己拼流程。

## 后端文件

```
server/app.py            创建应用、挂上路由
server/routes/<资源>.py  一个资源一个文件，例如 report、review
```

一个路由函数只做三件事：校验请求、调用一个用例函数、把结果或错误变成 HTTP。Pydantic 模型写在使用它的路由文件里。两个路由共用同一个模型，或路由文件超过行数上限时，再把模型挪到 `server/routes/schemas.py`。

## 前端文件

```text
web/src/app/          Next.js 路由、布局、metadata、Provider；页面只组装
web/src/features/     predictions、match、following、review；按业务分模块
web/src/components/   多模块共用展示组件
web/src/lib/          按职责命名的基础能力；服务端模块标明 server-only
web/src/styles/       主题变量、全局样式
web/src/api/          未来 OpenAPI 生成物，禁止手改；本轮不建
```

前端骨架不建立 server/services，不迁移 Python 编排，不创建 web/src/app/api 或 /api 代理。演示数据从 server-only 模块由服务端组件直接读取，序列化后交给客户端组件；只传页面所需的公开数据。

调用方向：app 组装 features / components；features 可以使用 components / lib；components 不反向引用 features。跨功能调用仅使用模块公开入口，其他模块内部文件通过 ESLint 禁止引用。app 只负责页面组合与路由语义；业务交互放功能组件和 hook。Provider 只在实际使用时创建。

客户端不得导入 .server 模块、演示源或 server-only。未来请求入口放功能 hook，底层 HTTP 能力放职责明确的 lib 文件；服务端取数与客户端刷新隔离。生成类型与展示模型分开，展示类型放使用它的功能模块；不要在 api/ 放手写契约。

### 演示契约与状态

每场含 ID、联赛/球队、UTC 开球时间、状态、推荐标记、档名、历史命中率、模型及来源、当前预测、首次预测存档、来源/获取/预测三种时间、可空比分、inplay 状态。无赔率来源可为 blend 或 dc_xg，前端只显示字段，不重新兜底。高信心推荐由契约提供，不重算概率阈值。

筛选不进入 URL，通过 sessionStorage 保存筛选与滚动；关注用 localStorage，客户端 effect 读取，读完前不写空默认值。服务端与客户端首次渲染一致，存储被禁用时保留内存交互并提示无法保存。数据刷新不得重置交互状态。

### 展示与错误边界

主题与移动适配遵循 stack.md：只用语义色变量，inplay 表示滚球，UTC 比较、北京时间展示。页面不写模型规则；当前结果和首次存档分区显示。缺数据显示暂无数据，不补零。

比赛页按请求动态渲染，metadata 与正文复用请求内读取；检查完成前不开始 streaming，不缓存失败结果。未知 ID 使用 notFound 返回 404；读取失败有旧值则展示旧值和延迟，无旧值则抛错误并返回 5xx。客户端刷新错误不等于文档 404。只用服务端测试配置注入故障，不增加公开测试路由。生产 HTTP 测试必须覆盖失败恢复及状态码。

演示站整站禁止收录，不建 sitemap。canonical 使用 SITE_URL 和稳定 match_id，不带客户端筛选状态。真实比赛由后端传入已有 ID，前端不重新哈希。

## 单文件尺度

行数用物理行，`wc -l` 即可，含文档字符串和注释。这是警报，不是凑行数的目标。

| 情况 | 尺度 |
|---|---|
| 目标 | 80–300 行 |
| 必须拆 | 超过 400 行。拆开的依据是第二种职责，拆到同包的新文件 |
| 不要新建 | 不足 80 行，又说不清独立职责 |

例外可以短：

- `__init__.py`、`version.py` 这种注册表。`__init__.py` 里不写业务。
- 同族模型的完整变体。`xg_dc.py` 短，是因为它只换数据源和权重，父类行为仍在 `sot_dc.py`。不要为了凑行数把父类抄进子文件。
- 测试文件不受 80 行下限约束。
- 前端路由、布局、配置、明确职责的小组件与类型可短；不为凑行数混合职责。

现有文件保持原样。`validation/backtest.py` 约 310 行，仍在上限内。`data/loader.py`、`data/oddsportal.py` 已到 418 行，下次改它们之前先拆（见 `docs/issues.md`）。不要为了贴合本规范专门去拆或去合并其他文件。下一次改动如果会让文件超过 400 行，先拆再加功能。

禁止碎片化：

- 不一个函数一个文件。
- 不建 `utils.py`、`helpers.py`、`common.py`、`misc.py`、`base.py`、`manager.py`。
- 只被一个文件使用的函数，以 `_` 开头，留在那个文件里。
- 第二个调用方出现，或文件因此超过 400 行，再提到新模块，并用职责命名。

`.ts` 和 `.tsx` 用同一把尺子。不要为单个 Tailwind 节点建组件文件。

## 公开表面

跨包只引用对方的公开函数：没有 `_` 前缀，并且出现在该包 `__init__.py` 的 `__all__` 或文件已有的调用约定里。现有代码直接引用具体模块（如 `football_prediction.data.loader`），继续这样写，不要再包一层转发。

包内可以互用私有函数。包外不引用 `_` 函数。改公开函数的参数或返回字段时，同一次改动里改掉调用方和测试。

## 新代码放哪

按这个顺序决定，停在第一条说得通的：

1. 现有文件里的一个私有函数就能完成。
2. 同一包已有同一职责的文件，放进去后仍不超过 400 行。
3. 同一包里出现了第二种职责：同包新文件。
4. 一种新的数据源、模型族或用例：新包，或 `services/` 里的新用例文件。

判断标准是「以后改它的理由是否和这个文件原来的理由相同」。只为了让原文件看起来短，不开新文件。

新增带 `LAYER_VERSION` 的领域模块时，仍走 `AGENTS.md` 的「改一层时」。`services/` 和 `server/` 不单独登记预测版本；它们改变的是编排或 HTTP，预测算法变了才升对应领域层的版本。

## 两人协作

按目录分工，不按「谁有空谁改一行」。

| 目录 | 负责 | 另一人使用的方式 |
|---|---|---|
| `web/` | 页面 | 只看 OpenAPI，不改 Python |
| `server/` | HTTP | 只调 `services` 的公开函数 |
| `services/` | 用例契约 | 改签名的人同时改路由、命令行和测试 |
| `data/` `features/` `model_*/` `calibration/` `validation/` | 数据与模型 | 通过用例使用，不从 `web/` 或 `server/` 调用 |
| `output/` `review/` | 预测结果的形状 | 通过用例使用 |
| `version.py` | 谁改变了行为谁更新 | 另一人不要在同一轮改版本号 |

同一轮不要两个人改同一个领域包。要改 `services` 的公开签名、OpenAPI 响应字段或 `version.py` 时，先看这个文件是否已有未合并的改动，并在同一次改动里更新调用方。

一次改动穿过相邻的两层为止：例如一个领域包加上调用它的用例，或一个路由加上用例签名。算法改动不顺手改页面文案，页面改动不改 SQL。响应字段要两边一起变时，这次改动只含契约和它的调用方。

Python 测试跟着被测模块走，放在 `tests/test_<模块>.py`。已有文件能放下就写进已有文件；超过 400 行再按被测模块拆。新测试保持离线，用内存 SQLite，不碰 `football.db`。

前端组件测试放在所属功能目录，生产 HTTP/浏览器测试放 web/tests。源文件长度由 ESLint 检查（物理行，400 行上限），生成物除外。
