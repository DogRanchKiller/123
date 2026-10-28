"""接口的响应模型：对应 football_prediction/services 读函数的返回（快照 match_view、首次存档、成绩单行）。
两个路由共用，所以单独成文件（docs/modules.md「后端文件」）。字段名与快照一致，前端类型由 OpenAPI 生成。"""
from typing import Literal

from pydantic import BaseModel

Tier = Literal["高", "中", "低"]
Side = Literal["主", "客"]


class AsianOutcome(BaseModel):
    """亚盘五种结算的概率（主队方向），五项之和为 1。"""
    win: float
    half_win: float
    push: float
    half_lose: float
    lose: float


class AsianBase(BaseModel):
    line: float
    line_source: Literal["市场线", "公平线"]
    outcome: AsianOutcome
    side: Side
    p_cover: float
    tier: Literal["高", "中", "低", "-"]
    historical_hit: float | None
    # 稳妥线（主队方向）：从选择方的线每次退 0.25，直到选择方等效赢盘概率 ≥ 0.65；找不到时为空
    safe_line: float | None = None
    safe_cover: float | None = None


class AsianCurrent(AsianBase):
    # 同一条线的主队赢盘：self = 主模型 dc_dyn；market = 该线水位去水；implied = 市场隐含比分矩阵（没有大小球赔率时空）
    self_home_cover: float | None
    market_home_cover: float | None
    implied_home_cover: float | None = None
    movement: str | None


class LikelyScore(BaseModel):
    score: str
    prob: float


class PrimaryModel(BaseModel):
    name: str
    version: str


class MatchView(BaseModel):
    """一场的本轮看法：实盘一轮按最新赔率算好写进快照。"""
    match_id: str
    league: str
    league_name: str
    home: str
    away: str
    kickoff_utc: str | None
    match_date: str
    model_name: str
    model_version: str
    recommended: bool
    recommendation_note: str | None
    odds_source: str | None
    asian: AsianCurrent
    probabilities: list[float]
    # 市场去水的主 / 平 / 客（对照）；本场没有胜平负赔率时空
    market_probabilities: list[float] | None = None
    probability_source: str
    score_source: str
    lean: str
    double: str
    confidence: Tier
    historical_first_hit: float
    historical_double_hit: float
    estimated_first_hit: float | None
    estimated_double_hit: float | None
    expected_goals: list[float | None]
    likely_scores: list[LikelyScore]
    over25: float | None
    btts: float | None
    self_models: dict[str, list[float | None]]
    movement: str | None
    hints: list[str]
    risks: list[str]


class ArchivedOdds(BaseModel):
    avg_h: float | None = None
    avg_d: float | None = None
    avg_a: float | None = None
    avg_over25: float | None = None
    avg_under25: float | None = None
    ah_line: float | None = None
    avg_ahh: float | None = None
    avg_aha: float | None = None


class ArchivedPrediction(BaseModel):
    """开赛前的首次存档与赛后评分：主模型 dc_dyn，v2.0.0 之前的场次依次用市场隐含、dc_market；
    临场档同形状（horizon=t1，市场隐含 market_implied_t1）。"""
    model_name: str
    model_version: str
    generated_at: str
    kickoff_utc: str | None
    probabilities: list[float | None]
    lean: str
    double: str
    confidence: Tier
    historical_first_hit: float
    historical_double_hit: float
    asian: AsianBase | None
    likely_scores: list[LikelyScore]
    over25: float | None
    odds: ArchivedOdds | None
    horizon: Literal["pre", "t1"] = "pre"
    n_books: int | None = None
    hours_to_ko: float | None = None
    scored: bool
    actual_outcome: Literal["home_win", "draw", "away_win"] | None
    log_loss: float | None
    brier: float | None
    ou25_log_loss: float | None
    score_log_loss: float | None
    ah_log_loss: float | None
    ah_hit: float | None
    result_src: str | None
    scored_at: str | None


class Score(BaseModel):
    home: int
    away: int


class MatchInfo(BaseModel):
    match_id: str
    league: str
    league_name: str
    home: str
    away: str
    match_date: str
    kickoff_utc: str | None
    score: Score | None
    score_source: Literal["football-data", "fotmob"] | None = None
    score_fetched_at: str | None = None


class RecentMatch(BaseModel):
    """最近已开球的一场：对阵与比分 + 首次存档 + 临场档（不是本轮看法）。"""
    match: MatchInfo
    archived: ArchivedPrediction
    near_archived: ArchivedPrediction | None = None


class ScorecardRow(BaseModel):
    """实盘成绩单一行（review/scorecard.live_report），按 log_loss 升序；同场对比同一档的市场基准 base
    （赛前档 market_avg，临场档 market_avg_t1 / market_avg_t2）。"""
    model_name: str
    model_ver: str
    matches: int
    log_loss: float | None
    brier: float | None
    hit_rate: float | None
    ou25_ll: float | None = None
    score_ll: float | None = None
    ah_n: int | None = None
    ah_ll: float | None = None
    ah_hit: float | None = None
    base: str | None = None
    paired_n: int | None = None
    diff_vs_base: float | None = None
    se: float | None = None


class ClosingRow(BaseModel):
    """对收盘参照一行（review/scorecard.closing_report），按 diff_vs_close 升序。首行 closing_avg 是收盘
    平均赔率（按比例去水）自身。收盘在存档时还看不到，只作参照，不进替换检查。"""
    model_name: str
    model_ver: str
    paired_n: int
    log_loss: float | None
    diff_vs_close: float | None
    se: float | None
