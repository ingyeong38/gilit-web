"""AI 경로 요약 (POST /api/routes/summary). 실제 GeminiClient에 가짜 HTTP 세션(Mock(spec=requests.Session))을 넣는다.

Gemini는 recommendedRouteId·headline·keywords만 만들고, 숫자와 label은 서버가 요청 카드 값으로 계산한다.
Gemini 쪽 실패는 모두 200 + source="rule"이다. 요청 값 오류만 400 {message, code}다.
"""

import json
import logging
from unittest.mock import Mock

import pytest
import requests
from fastapi.testclient import TestClient

from app.ai_summary import GeminiClient
from app.ai_summary.service import SummaryInput, SummaryRoute, rule_route, slack_min
from app.api.factory import create_app
from app.config import Settings, create_summary_client
from tests.conftest import NOW, kst

API_KEY = "test-gemini-key-0123456789abcdef"
MODEL = "gemini-test-model"
URL = "/api/routes/summary"
HEADLINE = "정체가 적은 최단시간 길로 가요"
KEYWORDS = ["정체 회피", "빠른 도착"]


def card(route_id, depart, arrive, duration, distance=31.2, toll=1500, **extra):
    return {"id": route_id, "departTime": depart, "arriveTime": arrive, "durationMin": duration,
            "distanceKm": distance, "toll": toll, **extra}


ARRIVE = "2026-11-05T09:00:00+09:00"
ROUTES = [
    card("recommend", "2026-11-05T08:12:00+09:00", "2026-11-05T08:50:30+09:00", 39),
    card("time", "2026-11-05T08:15:00+09:00", "2026-11-05T08:53:00+09:00", 38),
    card("free", "2026-11-05T08:02:00+09:00", "2026-11-05T08:49:00+09:00", 47, distance=29.8, toll=0),
]


def body(**overrides):
    return {"arrive": ARRIVE, "buffer": 10, "routes": ROUTES, **overrides}


def http_response(status=200, payload=None, json_error=False):
    fake = Mock(spec=requests.Response)
    fake.status_code = status
    if json_error:
        fake.json.side_effect = ValueError("not json")
    else:
        fake.json.return_value = payload
    return fake


def gemini_text(text):
    return http_response(payload={"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}]})


def gemini_json(value):
    return gemini_text(json.dumps(value, ensure_ascii=False))


def good_output(**overrides):
    return {"recommendedRouteId": "time", "headline": HEADLINE, "keywords": KEYWORDS, **overrides}


def fake_session(*responses):
    session = Mock(spec=requests.Session)
    session.post.side_effect = list(responses)
    return session


class Env:
    def __init__(self, session=None, settings=None, client="default"):
        self.session = session
        self.history = Mock()
        if client == "default":
            client = GeminiClient(API_KEY, MODEL, session=session, timeout=6) if session is not None else None
        self.app = create_app(settings=settings or Settings(), clock=lambda: NOW, history=self.history,
                              summary_client=client)
        self.client = TestClient(self.app)

    def post(self, payload, **kwargs):
        return self.client.post(URL, json=payload, **kwargs)


def summarize_with(*responses, payload=None):
    env = Env(fake_session(*responses))
    return env, env.post(payload or body())


# --- 정상 응답 ---


def test_gemini_success_uses_ai_text_and_server_numbers():
    env, response = summarize_with(gemini_json(good_output()))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "source": "gemini",
        "recommendedRouteId": "time",
        "recommendedDepartTime": "2026-11-05T08:15:00+09:00",
        "headline": HEADLINE,
        "keywords": KEYWORDS,
        "slackMin": 7,
        "bufferMin": 10,
        "comparison": [
            {"routeId": "recommend", "label": "추천", "durationMin": 39, "slackMin": 9, "toll": 1500,
             "departTime": "2026-11-05T08:12:00+09:00"},
            {"routeId": "time", "label": "최단시간", "durationMin": 38, "slackMin": 7, "toll": 1500,
             "departTime": "2026-11-05T08:15:00+09:00"},
            {"routeId": "free", "label": "무료도로", "durationMin": 47, "slackMin": 11, "toll": 0,
             "departTime": "2026-11-05T08:02:00+09:00"},
        ],
    }
    assert env.session.post.call_count == 1


def test_wrong_numbers_from_gemini_are_ignored():
    wrong = good_output(slackMin=999, bufferMin=0, recommendedDepartTime="2026-11-05T05:00:00+09:00",
                        comparison=[{"routeId": "time", "durationMin": 1, "slackMin": 500, "toll": 0}],
                        label="엉뚱한 이름")
    _, response = summarize_with(gemini_json(wrong))

    data = response.json()
    assert data["source"] == "gemini"
    assert (data["slackMin"], data["bufferMin"], data["recommendedDepartTime"]) == (7, 10, "2026-11-05T08:15:00+09:00")
    assert [row["durationMin"] for row in data["comparison"]] == [39, 38, 47]
    assert [row["slackMin"] for row in data["comparison"]] == [9, 7, 11]
    assert [row["label"] for row in data["comparison"]] == ["추천", "최단시간", "무료도로"]


def test_other_time_zone_input_is_returned_in_kst():
    routes = [card("recommend", "2026-11-04T23:12:00Z", "2026-11-04T23:50:00Z", 38)]
    _, response = summarize_with(gemini_json(good_output(recommendedRouteId="recommend")),
                                 payload=body(arrive="2026-11-05T00:00:00Z", routes=routes))

    data = response.json()
    assert data["recommendedDepartTime"] == "2026-11-05T08:12:00+09:00"
    assert data["slackMin"] == 10


def test_negative_slack_when_card_arrives_late():
    routes = [card("recommend", "2026-11-05T08:30:00+09:00", "2026-11-05T09:01:00+09:00", 31)]
    _, response = summarize_with(gemini_json(good_output(recommendedRouteId="recommend")), payload=body(routes=routes))

    assert response.json()["slackMin"] == -1


def test_extra_card_fields_are_ignored_and_not_sent():
    routes = [card("recommend", "2026-11-05T08:12:00+09:00", "2026-11-05T08:50:00+09:00", 38,
                   name="비밀도로 경유", label="가짜", path=[{"lat": 35.1, "lng": 129.0}])]
    env, response = summarize_with(gemini_json(good_output(recommendedRouteId="recommend")), payload=body(routes=routes))

    assert response.status_code == 200
    sent = json.dumps(env.session.post.call_args.kwargs["json"], ensure_ascii=False)
    assert "비밀도로" not in sent and "가짜" not in sent and "35.1" not in sent


# --- rule 대체 ---


def assert_rule(response, route_id="recommend"):
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["source"] == "rule"
    assert data["recommendedRouteId"] == route_id
    assert data["keywords"] == []
    assert data["headline"]
    return data


def test_rule_when_key_missing():
    settings = Settings(gemini_model=MODEL)
    assert create_summary_client(settings) is None
    env = Env(settings=settings, client=None)

    data = assert_rule(env.post(body()))
    assert data["slackMin"] == 9
    assert data["recommendedDepartTime"] == "2026-11-05T08:12:00+09:00"


def test_rule_when_model_missing():
    settings = Settings(gemini_api_key=API_KEY)
    assert create_summary_client(settings) is None
    assert_rule(Env(settings=settings, client=None).post(body()))


def test_app_starts_without_any_gemini_settings():
    app = create_app(settings=Settings(), clock=lambda: NOW)
    assert app.state.summary_client is None
    assert_rule(TestClient(app).post(URL, json=body()))


def test_summary_client_is_created_from_settings():
    client = create_summary_client(Settings(gemini_api_key=API_KEY, gemini_model=MODEL, ai_summary_timeout_sec=4.5))
    assert isinstance(client, GeminiClient)
    assert (client.model, client.timeout) == (MODEL, 4.5)


@pytest.mark.parametrize("error", [requests.Timeout("slow"), requests.ConnectionError("down")])
def test_rule_on_network_errors(error):
    _, response = summarize_with(error)
    assert_rule(response)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503])
def test_rule_on_http_errors(status):
    _, response = summarize_with(http_response(status, payload={"error": {"message": "내부 오류 문구"}}))
    assert_rule(response)


@pytest.mark.parametrize("fake", [
    http_response(json_error=True),  # 본문이 JSON이 아님
    http_response(payload=[]),  # 본문이 객체가 아님
    http_response(payload={"candidates": []}),  # 후보 없음 (차단 등)
    http_response(payload={"candidates": [{"content": {"parts": []}}]}),
    gemini_text("이건 JSON이 아니에요"),
    gemini_text('{"recommendedRouteId": "time", "headline": '),  # 잘린 JSON
    gemini_text('["time"]'),  # 객체가 아님
])
def test_rule_on_malformed_responses(fake):
    _, response = summarize_with(fake)
    assert_rule(response)


@pytest.mark.parametrize("output", [
    good_output(recommendedRouteId="distance"),  # 입력에 없는 id
    good_output(recommendedRouteId="unknown"),
    good_output(recommendedRouteId=None),
    {"headline": HEADLINE, "keywords": KEYWORDS},  # id 없음
    good_output(headline=None),
    good_output(headline="   "),
    good_output(headline="가" * 41),
    good_output(headline="줄바꿈이\n있어요"),
    good_output(headline="너비없는​문자"),
    good_output(headline="방향‮제어"),
    good_output(keywords="정체 회피"),  # 배열이 아님
    good_output(keywords=["하나", "둘", "셋", "넷"]),
    good_output(keywords=["가" * 13]),
    good_output(keywords=["탭\t문자"]),
    good_output(keywords=[""]),
    good_output(keywords=[3]),
])
def test_rule_on_schema_violations(output):
    _, response = summarize_with(gemini_json(output))
    assert_rule(response)


@pytest.mark.parametrize("output", [
    good_output(headline="8시 30분에 출발하면 여유 있어요"),  # headline 아라비아 숫자
    good_output(headline="통행료 1500원이 들어요"),
    good_output(keywords=["정체 회피", "여유 10분"]),  # keywords 아라비아 숫자
    good_output(headline="８시에 출발하세요"),  # 전각 숫자
    good_output(keywords=["여유 １０분"]),
    good_output(headline="정체 구간 ②곳을 피해요"),  # 원문자 숫자
])
def test_rule_when_text_contains_digits(output):
    _, response = summarize_with(gemini_json(output))
    assert_rule(response)


def test_text_without_digits_keeps_gemini():
    output = good_output(headline="정체가 적고 여유 있게 도착하는 길이에요", keywords=["정체 회피", "여유 확보", "무료 구간"])
    _, response = summarize_with(gemini_json(output))

    data = response.json()
    assert data["source"] == "gemini"
    assert (data["headline"], data["keywords"]) == (output["headline"], output["keywords"])


def test_prompt_forbids_numbers_and_time_expressions():
    env, _ = summarize_with(gemini_json(good_output()))
    system = env.session.post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"]
    assert "숫자" in system and "시각" in system and "시간 표현" in system


def test_limits_are_inclusive():
    output = good_output(headline="가" * 40, keywords=["가" * 12, "나", "다"])
    _, response = summarize_with(gemini_json(output))
    assert response.json()["source"] == "gemini"


def test_rule_without_recommend_card_uses_latest_departure():
    routes = [ROUTES[2], ROUTES[1]]  # free 08:02, time 08:15
    env = Env(client=None)
    assert_rule(env.post(body(routes=routes)), route_id="time")


def test_rule_route_tie_keeps_first_card():
    data = SummaryInput(kst(5, 9), 0, (
        SummaryRoute("free", kst(5, 8), kst(5, 8, 40), 40, 30.0, 0),
        SummaryRoute("time", kst(5, 8), kst(5, 8, 35), 35, 31.0, 1500),
    ))
    assert rule_route(data).id == "free"
    assert slack_min(data, data.routes[0]) == 20


# --- Gemini 요청 형식 ---


def test_request_uses_header_key_and_structured_output():
    env, _ = summarize_with(gemini_json(good_output()))

    call = env.session.post.call_args
    url = call.args[0]
    assert url == f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    assert "key=" not in url and API_KEY not in url and "params" not in call.kwargs
    assert call.kwargs["headers"]["x-goog-api-key"] == API_KEY
    assert call.kwargs["timeout"] == 6
    config = call.kwargs["json"]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    schema = config["responseSchema"]
    assert schema["properties"]["recommendedRouteId"]["enum"] == ["recommend", "time", "free"]
    assert set(schema["required"]) == {"recommendedRouteId", "headline", "keywords"}
    prompt = json.dumps(call.kwargs["json"], ensure_ascii=False)
    assert API_KEY not in prompt


def test_client_repr_hides_key():
    client = GeminiClient(API_KEY, MODEL, session=Mock(spec=requests.Session))
    assert API_KEY not in repr(client)
    assert API_KEY not in repr(Settings(gemini_api_key=API_KEY))


@pytest.mark.parametrize("model", ["", "  ", "../other", "models/x?key=1", "a b"])
def test_invalid_model_name_is_rejected(model):
    with pytest.raises(ValueError):
        GeminiClient(API_KEY, model)


def test_client_errors_do_not_chain_request_details():
    session = fake_session(requests.Timeout(f"timeout with {API_KEY}"))
    client = GeminiClient(API_KEY, MODEL, session=session)
    with pytest.raises(Exception) as caught:
        client.generate_json("system", "prompt", {})
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert API_KEY not in str(caught.value)


# --- 요청 검증 (400) ---


def past_routes():
    return [card("recommend", "2026-11-04T05:50:00+09:00", "2026-11-04T06:30:00+09:00", 40)]


@pytest.mark.parametrize("payload, code", [
    (body(routes=[]), "routes_count"),
    (body(routes=[card(key, "2026-11-05T08:00:00+09:00", "2026-11-05T08:40:00+09:00", 40)
                  for key in ("recommend", "time", "distance", "free", "recommend")]), "routes_count"),
    (body(routes=[card("walk", "2026-11-05T08:00:00+09:00", "2026-11-05T08:40:00+09:00", 40)]), "route_id"),
    (body(routes=[ROUTES[0], ROUTES[0]]), "route_duplicate"),
    (body(routes=[card("recommend", "2026-11-05T09:00:00+09:00", "2026-11-05T09:30:00+09:00", 30)]), "depart_range"),
    (body(routes=[card("recommend", "2026-11-04T08:59:00+09:00", "2026-11-04T09:30:00+09:00", 31)]), "depart_range"),
    (body(routes=[card("recommend", "2026-11-05T08:12:00+09:00", "2026-11-05T08:11:00+09:00", 0)]), "arrive_range"),
    (body(routes=[card("recommend", "2026-11-05T08:12:00+09:00", "2026-11-06T09:01:00+09:00", 1000)]), "arrive_range"),
    (body(arrive="2026-11-04T07:00:00+09:00", routes=past_routes()), "depart_passed"),
])
def test_rule_violations_return_400_with_code(payload, code):
    env = Env(fake_session(gemini_json(good_output())))
    response = env.post(payload)

    assert response.status_code == 400
    assert response.json()["code"] == code
    assert set(response.json()) == {"message", "code"}
    assert env.session.post.call_count == 0
    assert env.history.mock_calls == []


def test_past_departure_message():
    response = Env().post(body(arrive="2026-11-04T07:00:00+09:00", routes=past_routes()))
    assert response.json() == {"message": "출발시각이 이미 지난 경로가 있습니다. 경로를 다시 검색해 주세요.",
                               "code": "depart_passed"}


def replace_route(**changes):
    return body(routes=[{**ROUTES[0], **changes}])


@pytest.mark.parametrize("payload, message", [
    (body(buffer=7), "여유시간은 0, 5, 10, 15분 중 하나여야 합니다."),
    (body(buffer="10"), "여유시간은 0, 5, 10, 15분 중 하나여야 합니다."),
    (body(arrive="2026-11-05T09:00:00"), "도착 희망 시각은 ISO 8601 형식이어야 합니다 (예: 2026-11-06T09:00:00+09:00)."),
    (body(arrive=1762300800), "도착 희망 시각은 ISO 8601 형식이어야 합니다 (예: 2026-11-06T09:00:00+09:00)."),
    ({"buffer": 10, "routes": ROUTES}, "도착 희망 시각이 필요합니다."),
    ({"arrive": ARRIVE}, "routes는 경로 카드 객체의 배열이어야 합니다."),
    (body(routes="recommend"), "routes는 경로 카드 객체의 배열이어야 합니다."),
    (replace_route(departTime="2026-11-05T08:12:00"), "경로의 출발시각은 시간대가 있는 ISO 8601 형식이어야 합니다 (예: 2026-11-06T08:12:00+09:00)."),
    (replace_route(arriveTime="오늘"), "경로의 도착시각은 시간대가 있는 ISO 8601 형식이어야 합니다 (예: 2026-11-06T08:50:00+09:00)."),
    (replace_route(durationMin=-1), "경로의 소요시간은 0~1440 사이의 정수(분)여야 합니다."),
    (replace_route(durationMin=38.5), "경로의 소요시간은 0~1440 사이의 정수(분)여야 합니다."),
    (replace_route(distanceKm=-0.1), "경로의 거리는 0~2000 사이의 숫자(km)여야 합니다."),
    (replace_route(distanceKm=True), "경로의 거리는 0~2000 사이의 숫자(km)여야 합니다."),
    (replace_route(toll=-100), "경로의 통행료는 0 이상의 정수(원) 또는 null이어야 합니다."),
])
def test_format_errors_return_400(payload, message):
    env = Env(fake_session(gemini_json(good_output())))
    response = env.post(payload)

    assert response.status_code == 400
    assert response.json()["message"] == message
    assert env.session.post.call_count == 0


def test_non_object_body_returns_400():
    response = Env().client.post(URL, content="[1, 2]", headers={"Content-Type": "application/json"})
    assert response.status_code == 400


def test_toll_may_be_null():
    _, response = summarize_with(gemini_json(good_output(recommendedRouteId="recommend")),
                                 payload=replace_route(toll=None))
    assert response.status_code == 200
    assert response.json()["comparison"][0]["toll"] is None


def test_foreign_origin_is_rejected():
    response = Env().post(body(), headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


# --- 저장·로그 정책 ---


def test_no_history_or_store_access_and_login_not_required():
    env, response = summarize_with(gemini_json(good_output()))
    assert response.status_code == 200
    assert env.history.mock_calls == []
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("fake", [
    gemini_json(good_output()),
    gemini_json(good_output(headline="가" * 41)),
    http_response(500, payload={"error": {"message": "서버 내부 메시지"}}),
    requests.Timeout(f"timeout {API_KEY}"),
])
def test_logs_have_no_inputs_outputs_or_key(caplog, fake):
    caplog.set_level(logging.DEBUG)
    summarize_with(fake)

    text = caplog.text
    for secret in [API_KEY, HEADLINE, *KEYWORDS, "가" * 41, "서버 내부 메시지", "08:12", "08:50", "31.2", "1500", MODEL]:
        assert secret not in text
    summary_logs = [record for record in caplog.records if record.name == "app.ai_summary"]
    assert len(summary_logs) == 1
    assert summary_logs[0].getMessage().startswith(("AI 요약 생성:", "AI 요약 대체(rule):"))


# --- 설정 ---


def test_settings_from_env():
    settings = Settings.from_env({"GEMINI_API_KEY": f" {API_KEY} ", "GEMINI_MODEL": f" {MODEL} ", "AI_SUMMARY_TIMEOUT_SEC": "3.5"})
    assert (settings.gemini_api_key, settings.gemini_model, settings.ai_summary_timeout_sec) == (API_KEY, MODEL, 3.5)
    empty = Settings.from_env({})
    assert (empty.gemini_api_key, empty.gemini_model, empty.ai_summary_timeout_sec) == (None, None, 6)


@pytest.mark.parametrize("value", ["0", "-1", "abc", "inf"])
def test_invalid_timeout_is_rejected(value):
    with pytest.raises(ValueError, match="AI_SUMMARY_TIMEOUT_SEC"):
        Settings.from_env({"AI_SUMMARY_TIMEOUT_SEC": value})
