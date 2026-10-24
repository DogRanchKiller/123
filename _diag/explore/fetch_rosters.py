"""探索用：下载 understat 单场阵容（getMatchData），缓存 _cache/understat/matches/{id}.json。
只抓已结束场次；已缓存跳过；间隔 2.5 秒，失败退避 60s 递增。用法: python fetch_rosters.py E0 <part> <nparts>"""
import json, os, sys, time
import requests

lg, part, nparts = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
os.makedirs("_cache/understat/matches", exist_ok=True)
ids = []
for s in ["2526", "2627", "2425"]:   # 2324 已齐；测试季优先
    p = f"_cache/understat/{lg}_{s}.json"
    if os.path.exists(p):
        ids += [m["id"] for m in json.load(open(p, encoding="utf-8")) if m.get("isResult")]
todo = [i for k, i in enumerate(ids) if k % nparts == part and not os.path.exists(f"_cache/understat/matches/{i}.json")]
print(lg, "total", len(ids), "todo", len(todo), flush=True)
for k, mid in enumerate(todo):
    h = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest",
         "Referer": f"https://understat.com/match/{mid}"}
    for attempt in range(4):
        try:
            r = requests.get(f"https://understat.com/getMatchData/{mid}", headers=h, timeout=30)
            r.raise_for_status()
            ro = r.json()["rosters"]
            break
        except Exception as e:
            print("retry", mid, e, flush=True)
            time.sleep(60 * (attempt + 1))
    else:
        continue
    with open(f"_cache/understat/matches/{mid}.json", "w", encoding="utf-8") as f:
        json.dump(ro, f, ensure_ascii=False)
    if k % 100 == 0:
        print(k, flush=True)
    time.sleep(2.5)
print("done", flush=True)
