"""知识库的白名单、切块和预切词（agent/kb/whitelist.py、sources.py、embed.py），不需要 pymilvus，.venv 里也跑。
白名单五条核对（docs/agent-plan.md 第 7.2 节）用临时 git 仓库造违规；文档的时点（第 7.1 节）用固定提交时间的
临时仓库核对：available_at = 提交时间，改掉的段落在下一个提交被替代，未提交的改动不收。"""
import dataclasses
import os
import pathlib
import subprocess
from datetime import datetime, timezone

import pytest

from agent.kb import sources, whitelist
from agent.kb.embed import HashEmbedder, terms

ROOT = pathlib.Path(__file__).resolve().parent.parent


def git(repo: pathlib.Path, *args: str, when: str | None = None) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    if when:
        env |= {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
                   cwd=repo, env=env, check=True, capture_output=True)


def commit(repo: pathlib.Path, files: dict[str, str | None], when: str) -> None:
    """写入（None 为删除）并提交，提交时间固定为 when。"""
    for path, text in files.items():
        p = repo / path
        if text is None:
            git(repo, "rm", "-q", "-f", path)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        git(repo, "add", path)
    git(repo, "commit", "-q", "-m", "x", when=when)


@pytest.fixture
def repo(tmp_path) -> pathlib.Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    return r


def test_real_whitelist_passes():
    entries = whitelist.load()
    assert whitelist.check(entries, ROOT) == []
    paths = [e.path for e in entries]
    assert {"AGENTS.md", "docs/progress.md", "docs/issues.md"} <= set(paths)
    assert [e for e in entries if e.authority == "record"] == []             # 第一版不收交接记录


PROGRESS = """# 进度

### 研究 A

对照结果 −0.00597 与 0.540 在 `_diag/r/` 里，`analyze.py` 生成 `result.txt`。

### 只点名脚本

见 `run_it.py`：0.725、0.628。

### 重复

一

### 重复

二
"""


def _research_repo(repo: pathlib.Path) -> whitelist.Entry:
    commit(repo, {"docs/progress.md": PROGRESS,
                  "_diag/r/result.txt": "diff -0.00597 hit 0.540 other 0.5401\n",
                  "_diag/r/analyze.py": "open('result.txt', 'w')\n",
                  "_diag/r/run_it.py": "print(0.725)\n",
                  "_diag/r/run_it.log": "0.725 0.628\n",
                  "src.py": "x = 1\n", ".env.local": "KEY=\n"}, "2026-10-01T00:00:00+00:00")
    (repo / "loose.md").write_text("未提交\n", encoding="utf-8")
    (repo / "adir").mkdir()
    return whitelist.Entry(path="_diag/r/result.txt", authority="research",
                           cited_in="docs/progress.md#研究 A", basis="dir",
                           generated_by="_diag/r/analyze.py", anchors=("−0.00597", "0.540"))


def test_whitelist_rules_catch_violations(repo):
    good = _research_repo(repo)
    ok_script = whitelist.Entry(path="_diag/r/run_it.log", authority="research",
                                cited_in="docs/progress.md#只点名脚本", basis="script",
                                generated_by="_diag/r/run_it.py", redirect=True, anchors=("0.725", "0.628"))
    assert whitelist.check([good, ok_script, whitelist.Entry("docs/progress.md", "status")], repo) == []

    def bad(entry, word):
        problems = whitelist.check([entry], repo)
        assert problems and any(word in p for p in problems), problems

    rule = whitelist.Entry
    bad(rule("docs/*.md", "rule"), "通配符")                                   # 1. 路径
    bad(rule("adir", "rule"), "不是文件")
    bad(rule("nope.md", "rule"), "不存在")
    bad(rule("src.py", "rule"), "不收")
    bad(rule(".env.local", "rule"), "不收")
    bad(rule("docs/progress.md", "secret"), "authority")
    assert any("重复" in p for p in whitelist.check([good, good], repo))
    bad(rule("loose.md", "rule"), "没有提交")                                  # 5. 未提交的不收
    r = dataclasses.replace
    bad(r(good, cited_in="docs/progress.md#没有这一节"), "0 个")               # 2. 小节存在且唯一
    bad(r(good, cited_in="docs/progress.md#重复"), "2 个")
    bad(r(good, cited_in=None), "缺 cited_in")
    bad(r(good, basis="path"), "basis=path")                                   # 小节里没有完整路径
    bad(r(ok_script, generated_by="_diag/r/analyze.py"), "basis=script")       # 小节没点名这个脚本
    bad(r(good, generated_by="_diag/r/gone.py"), "不存在")                      # 3. generated_by
    bad(r(ok_script, redirect=False), "redirect")
    bad(r(good, anchors=("−0.00597",)), "少于两个")                             # 4. 锚点
    bad(r(good, anchors=("−0.00597", "0.54")), "没有同时出现")                  # 0.54 不算 0.540 的一部分
    assert whitelist.check([r(good, anchors=("−0.00597",), anchors_waived="文件是百分比")], repo) == []
    assert whitelist.anchor_in("−0.00597", "x -0.00597 y") and not whitelist.anchor_in("0.540", "0.5401")


def test_split_markdown_and_plain():
    md = "前言\n\n# 一\n\n正文一\n\n```\n# 不是标题\n```\n\n## 子\n\n子正文\n\n## 空\n\n# 二\n\n" + "长段落。" * 400
    parts = sources.split_markdown(md)
    heads = [h for h, _ in parts]
    assert heads[:3] == ["", "一", "一 > 子"] and "一 > 空" not in heads    # 只有标题的节不出块
    assert "# 不是标题" in parts[1][1]                                          # 代码块里的 # 不切
    assert heads.count("二") > 1 and all(len(p) <= sources.MAX_CHARS for _, p in parts)
    assert sources.split_plain("a\n\nb\n") == [("", "a\n\nb")]


def test_doc_chunks_follow_commits(repo):
    t1, t2, t3 = "2026-10-01T08:00:00+08:00", "2026-10-02T00:00:00+00:00", "2026-10-03T00:00:00+00:00"
    commit(repo, {"r.md": "# 一\n\n旧说法\n\n# 二\n\n不变\n"}, t1)
    commit(repo, {"r.md": "# 一\n\n新说法\n\n# 二\n\n不变\n"}, t2)
    commit(repo, {"r.md": "# 一\n\n旧说法\n\n# 二\n\n不变\n"}, t3)               # 改回去：算新的一段
    (repo / "r.md").write_text("# 一\n\n工作区里没提交的\n", encoding="utf-8")
    cs = sources.doc_chunks(whitelist.Entry("r.md", "rule"), repo)
    utc = lambda s: datetime.fromisoformat(s).astimezone(timezone.utc)
    life = [(c.text.split("\n")[1], c.available_at, c.superseded_at) for c in cs]
    assert life == [("旧说法", utc(t1), utc(t2)), ("不变", utc(t1), None),
                    ("新说法", utc(t2), utc(t3)), ("旧说法", utc(t3), None)]
    assert len({c.chunk_id for c in cs}) == 4 and cs[3].chunk_id.endswith(".r1")
    assert all(c.at_source == "git_commit" and c.meta["path"] == "r.md" for c in cs)
    assert cs[0].text.startswith("r.md > 一\n") and not any("没提交" in c.text for c in cs)
    commit(repo, {"r.md": None}, "2026-10-04T00:00:00+00:00")                   # 删掉文件：全部被替代
    assert all(c.superseded_at for c in sources.doc_chunks(whitelist.Entry("r.md", "rule"), repo))


def test_terms_and_hash_embedder():
    assert terms("主-0.75") == terms("主−0.75") == "主 m0_75 0_75"
    assert terms("亚盘信心") == "亚盘 盘信 信心" and terms("兜") == "兜"
    assert terms("v1.12.0") == terms("1.12.0") == "1_12_0"
    assert terms("AH_TIERS E0") == "ah_tiers e0"
    e = HashEmbedder(16)
    a, b, z = e.encode(["亚盘 信心", "亚盘 信心", ""])
    assert a == b and abs(sum(x * x for x in a) - 1) < 1e-9 and sum(z) == 1.0
