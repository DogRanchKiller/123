"""探索用：下载 football-data CSV 的红黄牌列，按 loader 同算法生成 match_id，存 _diag/explore/cards.csv。
不写数据库（数据层未改版本）。"""
import pandas as pd
from football_prediction.data.loader import (_CSV_URL, _download_csv, _normalize,
                                             _parse_date, _make_match_id)

rows = []
for lg in ["E0", "D1", "SP1"]:
    for s in ["2122", "2223", "2324", "2425", "2526", "2627"]:
        df = _download_csv(_CSV_URL.format(season=s, league=lg))
        df = df.dropna(subset=["HomeTeam", "AwayTeam", "FTHG", "FTAG"])
        for _, r in df.iterrows():
            d = _parse_date(r["Date"])
            if d is None:
                continue
            rows.append({
                "match_id": _make_match_id(lg, s, d, _normalize(str(r["HomeTeam"])),
                                           _normalize(str(r["AwayTeam"]))),
                "hr": r.get("HR"), "ar": r.get("AR"),
                "hy": r.get("HY"), "ay": r.get("AY"),
            })
        print(lg, s, len(df), flush=True)
pd.DataFrame(rows).to_csv("_diag/explore/cards.csv", index=False)
print("saved", len(rows))
