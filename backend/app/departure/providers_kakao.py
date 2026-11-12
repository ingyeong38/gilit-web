"""카카오모빌리티 미래 운행 정보 길찾기 API 어댑터.

GET https://apis-navi.kakaomobility.com/v1/future/directions
- 인증: Authorization: KakaoAK {REST API 키}
- 좌표는 "경도,위도" 순서다. 엔진의 Coordinate는 (위도, 경도)이므로 여기서 바꾼다.
- departure_time은 한국 시간 YYYYMMDDHHmm이다. 분 단위로 내려 보낸다.
- 경로가 없으면 HTTP 200에 routes[0].result_code != 0으로 온다 (예: 104 출발지와 도착지가 5m 이내).
- 일일 쿼터(5,000건)가 있으므로 같은 조회는 메모리 캐시로 다시 부르지 않는다.
  예측값이 갱신되도록 캐시 항목은 cache_ttl_sec(기본 10분)이 지나면 버린다.
- 경로 옵션은 priority(RECOMMEND, TIME, DISTANCE)와 avoid(toll 등, 여러 개면 |로 잇는다)로 고른다.
  요약 조회(get_route_summary)는 summary=true로 경로 좌표 없이 받고, 옵션마다 캐시를 따로 둔다.
"""

import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime

import requests

from app.departure.errors import (
    ProviderAuthError,
    ProviderBadRequestError,
    ProviderQuotaExceededError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RouteNotFoundError,
    RouteProviderError,
    UnsupportedTravelModeError,
)
from app.departure.models import (
    DEFAULT_ROUTE_OPTION,
    KST,
    ROUTE_AVOIDS,
    ROUTE_PRIORITIES,
    Coordinate,
    RouteOption,
    RouteSummary,
    TravelMode,
)
from app.departure.providers import RouteProvider

KAKAO_FUTURE_DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/future/directions"
MAX_DETAIL_LENGTH = 100  # 오류 메시지에 붙이는 카카오 안내 문구의 최대 길이
DEFAULT_CACHE_TTL_SEC = 600.0

CacheKey = tuple[Coordinate, Coordinate, datetime, RouteOption]


class KakaoRouteProvider(RouteProvider):
    """카카오모빌리티 미래 운행 정보로 출발시각별 자동차 소요시간을 조회한다.

    API 키는 _api_key에만 두고 repr, 오류 메시지, 예외 체인 어디에도 드러내지 않는다.
    캐시는 프로세스 메모리에 두는 LRU다. cache_size를 넘으면 가장 오래 안 쓴 항목을, cache_ttl_sec이 지나면
    그 항목을 버린다. cache_ttl_sec=0이면 캐시하지 않는다.
    웹 서버는 인스턴스 하나를 여러 요청 스레드가 함께 쓰므로 캐시는 잠금 안에서만 고친다.
    API 호출은 잠금 밖에서 하므로, 같은 조회가 동시에 들어오면 둘 다 API를 부를 수 있다.
    """

    def __init__(
        self,
        api_key: str,
        *,
        session: requests.Session | None = None,
        timeout: float = 10.0,
        cache_size: int = 1024,
        cache_ttl_sec: float = DEFAULT_CACHE_TTL_SEC,
        url: str = KAKAO_FUTURE_DIRECTIONS_URL,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("KAKAO_REST_API_KEY가 비어 있습니다.")
        if cache_size < 1:
            raise ValueError("cache_size는 1 이상이어야 합니다.")
        if cache_ttl_sec < 0:
            raise ValueError("cache_ttl_sec은 0 이상이어야 합니다.")
        self._api_key = api_key.strip()
        self._session = session or requests.Session()
        self.timeout = timeout
        self.cache_size = cache_size
        self.cache_ttl_sec = cache_ttl_sec
        self.url = url
        self.request_count = 0  # 실제로 API를 부른 횟수 (쿼터 확인용, 캐시 적중은 세지 않는다)
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._cache: OrderedDict[CacheKey, tuple[RouteSummary, float]] = OrderedDict()  # 값: (요약, 만료 시각)

    def __repr__(self) -> str:
        return (
            f"KakaoRouteProvider(timeout={self.timeout}, cache_size={self.cache_size}, "
            f"cache_ttl_sec={self.cache_ttl_sec})"
        )

    def get_duration(
        self,
        origin: Coordinate,
        dest: Coordinate,
        depart_at: datetime,
        travel_mode: TravelMode = TravelMode.CAR,
    ) -> int:
        travel_mode = TravelMode(travel_mode)
        if travel_mode is not TravelMode.CAR:
            raise UnsupportedTravelModeError("대중교통은 아직 지원하지 않습니다.")
        # 우선순위를 정하지 않은 조회는 추천 경로다. 경로 비교의 recommend 옵션과 같은 캐시를 쓴다.
        return self.get_route_summary(origin, dest, depart_at, DEFAULT_ROUTE_OPTION).duration_sec

    def get_route_summary(
        self,
        origin: Coordinate,
        dest: Coordinate,
        depart_at: datetime,
        option: RouteOption = DEFAULT_ROUTE_OPTION,
    ) -> RouteSummary:
        """경로 옵션별 요약(소요시간·거리·통행료). (출발지, 목적지, 출발시각(분), 옵션)마다 캐시한다."""
        if depart_at.tzinfo is None:
            raise ValueError("depart_at에는 시간대 정보가 있어야 합니다.")
        depart_local = depart_at.astimezone(KST).replace(second=0, microsecond=0)

        key = (origin, dest, depart_local, option)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        summary = self._request_summary(origin, dest, depart_local, option)
        self._cache_put(key, summary)
        return summary

    def _cache_get(self, key: CacheKey) -> RouteSummary | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            summary, expires_at = entry
            if self._monotonic() >= expires_at:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return summary

    def _cache_put(self, key: CacheKey, summary: RouteSummary) -> None:
        if self.cache_ttl_sec == 0:
            return
        with self._lock:
            self._cache[key] = (summary, self._monotonic() + self.cache_ttl_sec)
            self._cache.move_to_end(key)
            if len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)

    def _request_summary(
        self, origin: Coordinate, dest: Coordinate, depart_local: datetime, option: RouteOption
    ) -> RouteSummary:
        params = {
            "origin": _lng_lat(origin),
            "destination": _lng_lat(dest),
            "departure_time": depart_local.strftime("%Y%m%d%H%M"),
            "priority": option.priority,
            "summary": "true",  # 경로 좌표(sections) 없이 요약만 받는다
            **_avoid_param(option.avoid),
        }
        body = self._request_json(self.url, params)
        try:
            route = body["routes"][0]
            result_code = int(route["result_code"])
        except (ValueError, KeyError, IndexError, TypeError):
            raise RouteProviderError("길찾기 응답 형식이 올바르지 않습니다.") from None
        if result_code != 0:
            detail = self._clean(route.get("result_msg"))
            raise RouteNotFoundError(f"경로를 찾을 수 없습니다{_suffix(detail)} (result_code={result_code})", result_code)
        return _parse_summary(route)

    def _request_json(self, url: str, params: dict) -> dict:
        """기존 인증·타임아웃·키 비노출 오류 처리를 상세 경로와 장소 검색에서도 공유한다."""
        with self._lock:
            self.request_count += 1
        # requests 예외는 종류만 남기고 except 밖에서 새로 던진다. 원래 예외가 __context__로 따라붙지 않아
        # 요청 정보가 로그나 traceback으로 퍼지지 않는다 (from None은 출력만 숨기고 __context__는 남긴다).
        failure: type[requests.RequestException] | None = None
        try:
            response = self._session.get(
                url,
                params=params,
                headers={"Authorization": f"KakaoAK {self._api_key}"},
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            failure = type(error)
        if failure is not None:
            if issubclass(failure, requests.Timeout):
                raise ProviderTimeoutError("길찾기 서버 응답이 늦습니다. 잠시 후 다시 시도해 주세요.")
            raise ProviderUnavailableError(
                f"길찾기 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요. ({failure.__name__})"
            )

        status = response.status_code
        # 인증 오류 응답 본문에는 키가 그대로 들어 있으므로 본문을 읽지 않는다.
        if status in (401, 403):
            raise ProviderAuthError(
                f"카카오 API 인증에 실패했습니다 (HTTP {status}). "
                "KAKAO_REST_API_KEY와 카카오모빌리티 API 사용 설정을 확인하세요."
            )
        if status == 429:
            raise ProviderQuotaExceededError("길찾기 API 호출 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.")
        if status >= 500:
            raise ProviderUnavailableError(f"길찾기 서버 오류입니다 (HTTP {status}). 잠시 후 다시 시도해 주세요.")
        if status != 200:
            detail = self._error_detail(response)
            raise ProviderBadRequestError(f"길찾기 요청이 거부되었습니다 (HTTP {status}){_suffix(detail)}")

        try:
            body = response.json()
        except ValueError:
            raise RouteProviderError("카카오 응답 형식이 올바르지 않습니다.") from None
        if not isinstance(body, dict):
            raise RouteProviderError("카카오 응답 형식이 올바르지 않습니다.")
        return body

    def get_detailed_route(
        self,
        origin: Coordinate,
        dest: Coordinate,
        depart_at: datetime,
        priority: str,
        avoid: tuple[str, ...] = (),
    ) -> dict:
        if priority not in ROUTE_PRIORITIES:
            raise ValueError("지원하지 않는 경로 우선순위")
        if any(value not in ROUTE_AVOIDS for value in avoid):
            raise ValueError("지원하지 않는 회피 옵션")
        body = self._request_json(self.url, {
            "origin": _lng_lat(origin), "destination": _lng_lat(dest),
            "departure_time": depart_at.astimezone(KST).strftime("%Y%m%d%H%M"),
            "priority": priority, "summary": "false", "alternatives": "false", "road_details": "true",
            **_avoid_param(avoid),
        })
        try:
            route = body["routes"][0]
            code = int(route["result_code"])
        except (KeyError, IndexError, TypeError, ValueError):
            raise RouteProviderError("길찾기 응답 형식이 올바르지 않습니다.") from None
        if code != 0:
            # 공급자 원문에는 입력/키가 들어갈 수 있으므로 사용자 오류에는 정적 문장만 사용한다.
            raise RouteNotFoundError("해당 조건으로 자동차 경로를 찾을 수 없습니다.", code)
        return route

    def search_places(self, query: str) -> list[dict]:
        query = query.strip()
        if not query:
            return []
        body = self._request_json("https://dapi.kakao.com/v2/local/search/keyword.json", {"query": query, "size": 15})
        try:
            documents = body["documents"]
            result = [{"id": str(p["id"]), "name": p["place_name"],
                       "address": p.get("road_address_name") or p.get("address_name", ""),
                       "lat": float(p["y"]), "lng": float(p["x"])} for p in documents]
            if not result:
                body = self._request_json("https://dapi.kakao.com/v2/local/search/address.json", {"query": query, "size": 15})
                result = [{"id": f"address-{i}", "name": p["address_name"], "address": p["address_name"],
                           "lat": float(p["y"]), "lng": float(p["x"])} for i, p in enumerate(body["documents"])]
            for place in result:
                Coordinate(place["lat"], place["lng"])
        except (KeyError, TypeError, ValueError):
            raise RouteProviderError("장소 검색 응답 형식이 올바르지 않습니다.") from None
        return result

    def _error_detail(self, response: requests.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return ""
        return self._clean(body.get("msg") if isinstance(body, dict) else None)

    def _clean(self, message: object) -> str:
        """카카오 안내 문구를 메시지에 붙일 수 있게 다듬는다. 혹시 키가 섞여 있으면 가린다."""
        text = str(message or "").replace(self._api_key, "***").strip()
        return text[:MAX_DETAIL_LENGTH]


def _lng_lat(coordinate: Coordinate) -> str:
    return f"{coordinate.lng},{coordinate.lat}"


def _avoid_param(avoid: tuple[str, ...]) -> dict[str, str]:
    """회피 옵션이 없으면 파라미터를 보내지 않는다 (카카오 기본값)."""
    return {"avoid": "|".join(avoid)} if avoid else {}


def _parse_summary(route: dict) -> RouteSummary:
    """routes[0].summary를 읽는다. 통행료(fare.toll)는 없을 수 있다."""
    try:
        summary = route["summary"]
        duration = int(summary["duration"])
    except (ValueError, KeyError, TypeError):
        raise RouteProviderError("길찾기 응답에 소요시간이 없습니다.") from None
    if duration < 0:
        raise RouteProviderError("길찾기 응답의 소요시간이 올바르지 않습니다.")
    try:
        distance = int(summary["distance"])
    except (ValueError, KeyError, TypeError):
        raise RouteProviderError("길찾기 응답에 거리가 없습니다.") from None
    if distance < 0:
        raise RouteProviderError("길찾기 응답의 거리가 올바르지 않습니다.")
    fare = summary.get("fare")
    toll = fare.get("toll") if isinstance(fare, dict) else None
    if toll is not None and (isinstance(toll, bool) or not isinstance(toll, int | float) or not math.isfinite(toll) or toll < 0):
        raise RouteProviderError("길찾기 응답의 통행료가 올바르지 않습니다.")
    return RouteSummary(duration_sec=duration, distance_m=distance, toll=None if toll is None else int(toll))


def _suffix(detail: str) -> str:
    return f": {detail}" if detail else ""
