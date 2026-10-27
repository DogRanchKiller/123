"""
agent/kb/  向量知识库（docs/agent-plan.md 第 7 节，docs/agent-dev.md 第 7 节）。
- whitelist.toml / whitelist.py：收哪些文件（逐个列出）和五条核对；不依赖 pymilvus。
- sources.py：白名单文件按 git 历史切块（available_at = 提交时间，未提交的改动不收）；
  match_chunks.py：比赛类的块（看法、存档、比分、评分、阵容）经 services 的读函数取。
- embed.py：BM25 用的预切词（中文按字二元）和向量函数（bge-m3；测试用哈希假向量）。
- index.py：Milvus Lite 索引（agent_data/kb/），--rebuild / --update，按 as_of 过滤的混合检索。
- __main__.py：python -m agent.kb，四个开关：--rebuild、--update、--stats、--eval。
只读库；索引只写 kb_path 目录。这里不在导入时加载 pymilvus，工具层按需导入。
"""
