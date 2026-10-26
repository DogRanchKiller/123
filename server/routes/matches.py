"""GET /api/matches：本轮未开赛场次的看法 + 最近几天已开球场次（首次存档与比分）；
GET /api/matches/{match_id}：单场本轮看法 + 首次存档 + 临场档 + 赛果。
只读：快照由实盘一轮写，库用只读连接打开。还没跑过实盘一轮（无快照）时列表返回 503。"""
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from football_prediction import services
from server.routes.schemas import ArchivedPrediction, MatchInfo, MatchView, PrimaryModel, RecentMatch

router = APIRouter(prefix="/api/matches", tags=["matches"])

NO_SNAPSHOT = "还没有实盘快照：先运行 python -m football_prediction.live"


class MatchList(BaseModel):
    generated_at: str
    system_version: str
    primary_model: PrimaryModel
    matches: list[MatchView]
    recent: list[RecentMatch]


class MatchDetail(BaseModel):
    match: MatchInfo
    current: MatchView | None
    archived: ArchivedPrediction | None
    near_archived: ArchivedPrediction | None = None
    generated_at: str | None


def _open(request: Request):
    try:
        return services.open_readonly(request.app.state.db_path, fotmob_path=request.app.state.fotmob_path)
    except sqlite3.OperationalError as e:
        raise HTTPException(503, f"数据库暂时无法打开：{e}") from e


@router.get("", response_model=MatchList, summary="本轮未开赛场次 + 最近已开球场次")
def list_matches(request: Request,
                 recent_days: int = Query(services.RECENT_DAYS, ge=0, le=14,
                                          description="附带开球在最近几天内的已开球场次；0 为不附带")) -> dict:
    now = datetime.now(timezone.utc)
    data = services.read_current(now, request.app.state.snapshot_path)
    if data is None:
        raise HTTPException(503, NO_SNAPSHOT)
    if not recent_days:
        return data | {"recent": []}
    conn = _open(request)
    try:
        return data | {"recent": services.read_recent(conn, now, recent_days)}
    except sqlite3.OperationalError as e:           # 实盘写库超过等待时间
        raise HTTPException(503, f"数据库暂时无法读取：{e}") from e
    finally:
        conn.close()


@router.get("/{match_id}", response_model=MatchDetail, summary="单场详情",
            responses={404: {"description": "快照和库里都没有这场"}})
def get_match(match_id: str, request: Request) -> dict:
    conn = _open(request)
    try:
        data = services.read_match(conn, match_id, request.app.state.snapshot_path)
    except sqlite3.OperationalError as e:           # 实盘写库超过等待时间
        raise HTTPException(503, f"数据库暂时无法读取：{e}") from e
    finally:
        conn.close()
    if data is None:
        raise HTTPException(404, "找不到这场比赛")
    return data
