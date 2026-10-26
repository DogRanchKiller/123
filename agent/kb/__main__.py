"""
python -m agent.kb  知识库的命令行（只在 .venv-ml 里跑；先手动跑，不接进 run_daily.bat）。
  --rebuild：完整重建（旧块不保留）
  --update：增量，只给新块算向量，改替代时间和评分元数据
  --stats：块数、按类和权威级别的分布、索引大小
  --eval：检索评测（agent/eval/retrieval.jsonl）：三种方式的 recall@5、MRR 和泄漏检查
库只读；索引写在 AGENT_KB_PATH（默认 agent_data/kb/）。
"""
import argparse
import json
import sys

from agent import config
from agent.kb import build, index


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m agent.kb", description="Agent 向量知识库")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--rebuild", action="store_true", help="完整重建")
    g.add_argument("--update", action="store_true", help="增量更新")
    g.add_argument("--stats", action="store_true", help="索引统计")
    g.add_argument("--eval", nargs="?", const="", metavar="FILE", help="检索评测（默认 agent/eval/retrieval.jsonl）")
    a = ap.parse_args(argv)
    cfg = config.current()
    try:
        if a.rebuild or a.update:
            out = build.run("rebuild" if a.rebuild else "update")
            print("索引目录：", cfg.kb_path)
        elif a.stats:
            out = index.stats(cfg.kb_path)
        else:
            from agent.eval import retrieval
            out = retrieval.run(a.eval or None)
    except (ValueError, index.KBUnavailable, index.KBBusy) as e:
        print(e, file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
