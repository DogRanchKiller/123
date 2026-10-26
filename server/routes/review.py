"""GET /api/review：实盘成绩单（本轮快照里的 live_report），同场对比 market_avg；亚盘列只作参考。"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from football_prediction import services
from server.routes.matches import NO_SNAPSHOT
from server.routes.schemas import PrimaryModel, ScorecardRow

router = APIRouter(prefix="/api/review", tags=["review"])


class Review(BaseModel):
    generated_at: str
    system_version: str
    primary_model: PrimaryModel
    scorecard: list[ScorecardRow]


@router.get("", response_model=Review, summary="实盘成绩单")
def get_review(request: Request) -> dict:
    data = services.read_scorecard(request.app.state.snapshot_path)
    if data is None:
        raise HTTPException(503, NO_SNAPSHOT)
    return data
