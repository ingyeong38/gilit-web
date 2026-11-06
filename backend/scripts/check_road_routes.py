"""수동 실조회 검사: backend에서 venv/bin/python scripts/check_road_routes.py.
REST 키는 .env에서만 읽고 출력하지 않는다. 두 구간, 최대 약 50회 외부 요청.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dataclasses import replace
from datetime import datetime, timedelta
from app.config import load_env_files, Settings, create_route_provider
from app.departure import KST
from app.api.routes import resolve_place
from app.routing import find_routes

load_env_files()
settings = replace(Settings.from_env(), route_provider="kakao")
if not settings.kakao_rest_api_key:
    print("REST key not configured")
    raise SystemExit(1)
provider = create_route_provider(settings)
arrive = (datetime.now(KST) + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
failed = False
for origin_name, dest_name in [("김해시청", "동의대학교 가야캠퍼스"), ("김해국제공항 국내선청사", "부산역")]:
    try:
        origin, dest = resolve_place(provider, origin_name), resolve_place(provider, dest_name)
        routes = find_routes(provider, settings.solver_config(), lambda: datetime.now(KST), origin, dest, arrive, 10)
        print(origin_name, "->", dest_name, "cards:", len(routes), flush=True)
        for route in routes:
            print({"id": route["id"], "points": len(route["path"]), "km": route["distanceKm"],
                   "minutes": route["durationMin"], "start": route["path"][0], "end": route["path"][-1]}, flush=True)
    except Exception as error:
        failed = True
        print("LIVE FAILED:", type(error).__name__, str(error).replace(settings.kakao_rest_api_key, "[REDACTED]"), flush=True)
print("External requests:", provider.request_count)
raise SystemExit(1 if failed else 0)
