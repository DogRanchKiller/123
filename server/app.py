"""
server/app.py  只读 HTTP 接口（FastAPI）
GET /api/matches、/api/matches/{match_id}、/api/review，只调 football_prediction.services 的读函数：
读实盘一轮写的快照 reports/latest_round.json 和 football.db 里的首次存档（只读连接；fotmob.db 存在时只读挂上补比分），
不拟合、不写库、不联网。

没有鉴权。默认只监听 127.0.0.1；--host 0.0.0.0 给局域网用时，访问范围必须在网络层（防火墙 / 路由器）限制，
不要映射到公网。

  python -m server                         # http://127.0.0.1:8000 ，文档 /docs
  python -m server --host 0.0.0.0 --port 8000
  python -m server --openapi web/openapi.json   # 只导出 OpenAPI，前端据此生成类型
"""
import argparse
import json
import pathlib

from fastapi import FastAPI

from football_prediction import services, version
from server.routes import matches, review

OPENAPI_PATH = pathlib.Path("web") / "openapi.json"


def create_app(db_path: str = services.DB_PATH, snapshot_path: str = services.SNAPSHOT_PATH,
               fotmob_path: str | None = services.FOTMOB_DB) -> FastAPI:
    """路径相对启动目录（仓库根目录）；测试传临时路径。"""
    app = FastAPI(title="足球预测只读接口", version=version.SYSTEM_VERSION,
                  description="实盘一轮的本轮看法（亚盘为主）、首次存档与成绩单。只读，无鉴权，仅限本机 / 局域网。")
    app.state.db_path, app.state.snapshot_path, app.state.fotmob_path = db_path, snapshot_path, fotmob_path
    app.include_router(matches.router)
    app.include_router(review.router)
    return app


def openapi_text(app: FastAPI | None = None) -> str:
    """导出给前端的 OpenAPI（稳定排序，带换行结尾）；tests/test_server.py 检查 web/openapi.json 与它一致。"""
    return json.dumps((app or create_app()).openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m server", description="足球预测只读接口（无鉴权）")
    ap.add_argument("--host", default="127.0.0.1", help="默认只本机；0.0.0.0 为局域网，须在网络层限制访问")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--db", default=services.DB_PATH)
    ap.add_argument("--snapshot", default=services.SNAPSHOT_PATH)
    ap.add_argument("--fotmob", default=services.FOTMOB_DB, help="FotMob 库（补比分）；不存在时跳过")
    ap.add_argument("--openapi", metavar="PATH", help="只把 OpenAPI 写到 PATH 后退出")
    args = ap.parse_args(argv)
    app = create_app(args.db, args.snapshot, args.fotmob)
    if args.openapi:
        pathlib.Path(args.openapi).write_text(openapi_text(app), encoding="utf-8", newline="\n")
        print(f"已写出 {args.openapi}")
        return
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"⚠ 接口没有鉴权，正在监听 {args.host}：只在局域网用，并在防火墙 / 路由器上限制访问。")
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
