"""Measure GET /api/routes over loopback HTTP using the existing route handler.

From the repository root, with backend/requirements.txt installed:
  PYTHONDONTWRITEBYTECODE=1 python backend/scripts/benchmark_route_query.py --mode mock --requests 21
  PYTHONDONTWRITEBYTECODE=1 python backend/scripts/benchmark_route_query.py --mode kakao --requests 5

Kakao mode uses the configured REST key and consumes external API quota.
"""

import argparse
from collections import Counter
from datetime import datetime, timedelta
from http.client import HTTPConnection, HTTPException
import json
from math import ceil, isfinite
from pathlib import Path
import socket
from statistics import median
import sys
from threading import Thread
from time import monotonic, perf_counter, sleep
from urllib.parse import urlencode

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.factory import create_app
from app.api.schemas import RouteCardResponse
from app.config import Settings, load_env_files
from app.departure import KST

ORIGIN = (35.2285, 128.8894)
DESTINATION = (35.1441, 129.0336)
BUFFER_MIN = 10


def route_query(arrival):
    return "/api/routes?" + urlencode({
        "from": "김해시청",
        "to": "동의대학교 가야캠퍼스",
        "fromLat": ORIGIN[0],
        "fromLng": ORIGIN[1],
        "toLat": DESTINATION[0],
        "toLng": DESTINATION[1],
        "arrive": arrival.isoformat(),
        "buffer": BUFFER_MIN,
    })


def validate_routes(cards, mode, arrival, now):
    if not isinstance(cards, list) or not cards:
        raise ValueError("Missing route cards")
    options_seen = set()
    for payload in cards:
        card = RouteCardResponse.model_validate(payload)
        if card.dataSource != mode or card.id not in card.options:
            raise ValueError("Unexpected route source or option")
        if options_seen.intersection(card.options) or len(set(card.options)) != len(card.options):
            raise ValueError("Duplicate route options")
        options_seen.update(card.options)
        if not isfinite(card.distanceKm) or card.distanceKm <= 0 or card.durationMin <= 0:
            raise ValueError("Invalid distance or duration")
        deadline = arrival - timedelta(minutes=BUFFER_MIN if card.bufferApplied else 0)
        if not now <= card.departTime < card.arriveTime <= deadline:
            raise ValueError("Invalid route timing")
        if ceil((card.arriveTime - card.departTime).total_seconds() / 60) != card.durationMin:
            raise ValueError("Duration does not match departure and arrival")
        points = [(point.lat, point.lng) for point in card.path]
        if len(set(points)) < 2 or any(
            not (-90 <= lat <= 90 and -180 <= lng <= 180) for lat, lng in points
        ):
            raise ValueError("Invalid route geometry")
        if mode == "mock" and (points[0], points[-1]) != (ORIGIN, DESTINATION):
            raise ValueError("Mock path endpoints do not match the input")


def fetch(port, path):
    connection = HTTPConnection("127.0.0.1", port, timeout=180)
    started = perf_counter()
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        return response.status, body, (perf_counter() - started) * 1000
    finally:
        connection.close()


def report(label, outcomes):
    successful = sorted(ms for status, ms in outcomes if status == "HTTP 200 + valid route")
    print(f"{label}: success={len(successful)} failure={len(outcomes) - len(successful)}")
    print(f"  outcomes={dict(Counter(status for status, _ in outcomes))}")
    if successful:
        p95 = successful[ceil(0.95 * len(successful)) - 1]
        print(f"  median={median(successful):.2f} ms p95={p95:.2f} ms (successful requests only)")


def wait_for_server(server, thread):
    deadline = monotonic() + 10
    while not server.started:
        if not thread.is_alive() or monotonic() >= deadline:
            raise RuntimeError("Local HTTP server failed to start")
        sleep(0.01)


def benchmark(port, mode, now, arrival, count):
    path = route_query(arrival)
    outcomes = []
    reference = None
    for _ in range(count):
        try:
            status, body, elapsed = fetch(port, path)
        except (OSError, HTTPException) as error:
            outcomes.append((f"Transport failure ({type(error).__name__})", None))
            continue

        outcome = f"HTTP {status}"
        if status == 200:
            try:
                cards = json.loads(body)
                validate_routes(cards, mode, arrival, now)
                if mode == "mock" and reference is not None and cards != reference:
                    raise ValueError("Mock result changed for identical input")
            except (ValueError, TypeError):
                outcome += " + invalid route"
            else:
                outcome += " + valid route"
                if reference is None:
                    reference = cards
                    for card in cards:
                        print(
                            f"  {card['id']}: options={','.join(card['options'])} "
                            f"distance={card['distanceKm']:.3f} km "
                            f"duration={card['durationMin']} min points={len(card['path'])}"
                        )
        outcomes.append((outcome, elapsed))

    report("First", outcomes[:1])
    report("Repeated", outcomes[1:])
    return all(status == "HTTP 200 + valid route" for status, _ in outcomes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("mock", "kakao"), required=True)
    parser.add_argument("--requests", type=int, required=True, help="Total including the first request")
    args = parser.parse_args()
    if args.requests < 2:
        parser.error("--requests must be at least 2")

    key = None
    if args.mode == "kakao":
        import os

        load_env_files()
        key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
        if not key:
            parser.error("KAKAO_REST_API_KEY is unavailable")
    settings = Settings(route_provider=args.mode, kakao_rest_api_key=key)
    now = datetime.now(KST)
    arrival = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    app = create_app(settings=settings, clock=lambda: now)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    print(f"mode={args.mode} route=김해시청 → 동의대학교 가야캠퍼스 arrive={arrival.isoformat()}")
    print(f"requests={args.requests} sequential, fresh client connection per request, buffer={BUFFER_MIN} min")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            wait_for_server(server, thread)
            passed = benchmark(port, args.mode, now, arrival, args.requests)
        finally:
            server.should_exit = True
            thread.join(timeout=5)
    if args.mode == "kakao":
        print(f"External requests: {app.state.provider.request_count}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
