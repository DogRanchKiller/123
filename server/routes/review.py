"""GET /api/review：实盘成绩单（本轮快照里的 live_report），同场对比同一档的 market_avg；亚盘列只作参考。
closing 是对收盘平均赔率的参照（closing_report），不进替换检查。"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from football_prediction import services
from server.routes.matches import NO_SNAPSHOT
from server.routes.schemas import ClosingRow, PrimaryModel, ScorecardRow

router = APIRouter(prefix="/api/review", tags=["review"])


class Review(BaseModel):
    generated_at: str
    system_version: str
    primary_model: PrimaryModel
    scorecard: list[ScorecardRow]
    closing: list[ClosingRow] = []


@router.get("", response_model=Review, summary="实盘成绩单")
def get_review(request: Request) -> dict:
    data = services.read_scorecard(request.app.state.snapshot_path)
    if data is None:
        raise HTTPException(503, NO_SNAPSHOT)
    return data
