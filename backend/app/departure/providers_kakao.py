"""카카오모빌리티 미래 운행 정보 길찾기 API 어댑터.

GET https://apis-navi.kakaomobility.com/v1/future/directions
- 인증: Authorization: KakaoAK {REST API 키}
- 좌표는 "경도,위도" 순서다. 엔진의 Coordinate는 (위도, 경도)이므로 여기서 바꾼다.
- departure_time은 한국 시간 YYYYMMDDHHmm이다. 분 단위로 내려 보낸다.
- 경로가 없으면 HTTP 200에 routes[0].result_code != 0으로 온다 (예: 104 출발지와 도착지가 5m 이내).
- 일일 쿼터(5,000건)가 있으므로 같은 조회는 메모리 캐시로 다시 부르지 않는다.
  예측값이 갱신되도록 캐시 항목은 cache_ttl_sec(기본 10분)이 지나면 버린다.
"""

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
from app.departure.models import KST, Coordinate, TravelMode
from app.departure.providers import RouteProvider

KAKAO_FUTURE_DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/future/directions"
MAX_DETAIL_LENGTH = 100  # 오류 메시지에 붙이는 카카오 안내 문구의 최대 길이
DEFAULT_CACHE_TTL_SEC = 600.0

CacheKey = tuple[Coordinate, Coordinate, datetime, TravelMode]


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
        self._cache: OrderedDict[CacheKey, tuple[int, float]] = OrderedDict()  # 값: (소요시간 초, 만료 시각)

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
        if depart_at.tzinfo is None:
            raise ValueError("depart_at에는 시간대 정보가 있어야 합니다.")
        depart_local = depart_at.astimezone(KST).replace(second=0, microsecond=0)

        key = (origin, dest, depart_local, travel_mode)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        seconds = self._request_duration(origin, dest, depart_local)
        self._cache_put(key, seconds)
        return seconds

    def _cache_get(self, key: CacheKey) -> int | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            seconds, expires_at = entry
            if self._monotonic() >= expires_at:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return seconds

    def _cache_put(self, key: CacheKey, seconds: int) -> None:
        if self.cache_ttl_sec == 0:
            return
        with self._lock:
            self._cache[key] = (seconds, self._monotonic() + self.cache_ttl_sec)
            self._cache.move_to_end(key)
            if len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)

    def _request_duration(self, origin: Coordinate, dest: Coordinate, depart_local: datetime) -> int:
        params = {
            "origin": _lng_lat(origin),
            "destination": _lng_lat(dest),
            "departure_time": depart_local.strftime("%Y%m%d%H%M"),
        }
        with self._lock:
            self.request_count += 1
        # requests 예외는 종류만 남기고 except 밖에서 새로 던진다. 원래 예외가 __context__로 따라붙지 않아
        # 요청 정보가 로그나 traceback으로 퍼지지 않는다 (from None은 출력만 숨기고 __context__는 남긴다).
        failure: type[requests.RequestException] | None = None
        try:
            response = self._session.get(
                self.url,
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
            route = response.json()["routes"][0]
            result_code = int(route["result_code"])
        except (ValueError, KeyError, IndexError, TypeError):
            raise RouteProviderError("길찾기 응답 형식이 올바르지 않습니다.") from None
        if result_code != 0:
            detail = self._clean(route.get("result_msg"))
            raise RouteNotFoundError(f"경로를 찾을 수 없습니다{_suffix(detail)} (result_code={result_code})", result_code)
        try:
            seconds = int(route["summary"]["duration"])
        except (ValueError, KeyError, TypeError):
            raise RouteProviderError("길찾기 응답에 소요시간이 없습니다.") from None
        if seconds < 0:
            raise RouteProviderError("길찾기 응답의 소요시간이 올바르지 않습니다.")
        return seconds

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


def _suffix(detail: str) -> str:
    return f": {detail}" if detail else ""
