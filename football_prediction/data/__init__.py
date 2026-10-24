"""数据层 — 负责下载、入库、标准化球队ID"""
from .loader import load_season, init_db

__all__ = ["load_season", "init_db"]
