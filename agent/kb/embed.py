"""
agent/kb/embed.py  BM25 的预切词和向量函数。
- terms(text)：Milvus 的 standard 分词只按 \\w+ 切、不懂中文，所以先在 Python 里切好再交给它：
  中文按字二元（单字成段时保留单字），英文 / 代码词转小写；数字只留 \\w 字符，负号写成 m、小数点写成 _
  （-0.75 → m0_75，另加不带符号的 0_75；v1.12.0 → 1_12_0），所以「-0.75」和「−0.75」「0.75」都能对上。
- BgeEmbedder：本地目录里的 BAAI/bge-m3（sentence-transformers，local_files_only，不联网），1024 维、归一化。
- HashEmbedder：测试用的假向量（词哈希到固定维数），不加载模型。
get_embedder(cfg)：cfg.embedder 不为空时用它（测试注入），否则按 cfg.embed_model 加载并缓存。
"""
import hashlib
import math
import pathlib
import re

_TOKEN = re.compile(r"[一-鿿㐀-䶿]+|[+\-−]?\d+(?:\.\d+)*%?|v(?=\d)|[A-Za-z_][A-Za-z0-9_]*")
_CJK = re.compile(r"[一-鿿㐀-䶿]")


def _number(tok: str) -> list[str]:
    sign = tok[0] in "+-−"
    body = tok.lstrip("+-−").rstrip("%").replace(".", "_")
    out = [body]
    if sign:
        out.insert(0, ("m" if tok[0] in "-−" else "p") + body)
    return out


def terms(text: str) -> str:
    """text → 空格分隔的检索词（建索引和查询用同一个函数）。"""
    out: list[str] = []
    for tok in _TOKEN.findall(text):
        if tok == "v":                      # 版本号前的 v：v1.12.0 与 1.12.0 切成同样的词
            continue
        if _CJK.match(tok):
            out += [tok] if len(tok) == 1 else [tok[i:i + 2] for i in range(len(tok) - 1)]
        elif tok[0].isdigit() or tok[0] in "+-−":
            out += _number(tok)
        else:
            out.append(tok.lower())
    return " ".join(out)


class HashEmbedder:
    """假向量：检索词哈希到 dim 维再归一化。同样的词得到同样的方向，够测试检索流程用。"""
    name = "hash"

    def __init__(self, dim: int = 64):
        self.dim = dim

    def encode(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for w in terms(t).split():
                h = int.from_bytes(hashlib.blake2b(w.encode(), digest_size=8).digest(), "little")
                v[h % self.dim] += 1.0 if (h >> 32) & 1 else -1.0
            n = math.sqrt(sum(x * x for x in v))
            out.append([x / n for x in v] if n else [1.0] + [0.0] * (self.dim - 1))
        return out


class BgeEmbedder:
    """BAAI/bge-m3 稠密向量。只从本地目录加载（目录见 config.EMBED_MODEL），没有时报错并说明怎么下载。"""
    name = "bge-m3"
    dim = 1024
    batch_size = 16
    max_seq_length = 1024      # 块按约 1000 字切，够用；比默认 8192 省内存

    def __init__(self, path: str):
        if not (pathlib.Path(path) / "modules.json").exists():
            raise FileNotFoundError(f"找不到 bge-m3 模型目录 {path}；下载方法见 docs/stack.md")
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(path, local_files_only=True)
        self.model.max_seq_length = self.max_seq_length
        self.dim = self.model.get_embedding_dimension()

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        v = self.model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                              convert_to_numpy=True, show_progress_bar=len(texts) > 64)
        return v.tolist()


_CACHE: dict[str, BgeEmbedder] = {}


def get_embedder(cfg):
    """测试注入的 cfg.embedder 优先；否则按 cfg.embed_model 加载 bge-m3，同一进程只加载一次。"""
    if cfg.embedder is not None:
        return cfg.embedder
    if cfg.embed_model not in _CACHE:
        _CACHE[cfg.embed_model] = BgeEmbedder(cfg.embed_model)
    return _CACHE[cfg.embed_model]
