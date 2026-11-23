"""GA4 방문자와 저장된 검색 기록을 독립적으로 집계한다."""

from datetime import date, datetime, time, timedelta

from app.departure import KST


class GA4Reports:
    def __init__(self, property_id: str | None, start_date: str | None):
        self.property_id = property_id
        self.start_date = start_date

    def run(self, requests: list[dict]) -> list[dict]:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        if not self.property_id or not self.property_id.isascii() or not self.property_id.isdecimal():
            raise ValueError("GA4 property ID")
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/analytics.readonly"])
        with AuthorizedSession(credentials, refresh_timeout=5) as session:
            response = session.post(
                f"https://analyticsdata.googleapis.com/v1beta/properties/{self.property_id}:batchRunReports",
                json={"requests": requests},
                timeout=5,
                max_allowed_time=8,
            )
            response.raise_for_status()
            reports = response.json()["reports"]
            if len(reports) != len(requests):
                raise ValueError("GA4 report count")
            return reports


def change_pct(current: int | None, previous: int | None) -> float | None:
    if current is None or not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def report_rows(report: dict) -> list[dict]:
    metadata = report["metadata"]
    if metadata["timeZone"] != "Asia/Seoul":
        raise ValueError("GA4 reporting timezone")
    if any(metadata.get(flag) for flag in ("subjectToThresholding", "samplingMetadatas", "dataLossFromOtherRow")):
        return []
    rows = report.get("rows", [])
    if int(report.get("rowCount", 0)) != len(rows):
        raise ValueError("GA4 incomplete report")
    return rows


def user_count(row: dict) -> int:
    count = int(row["metricValues"][0]["value"])
    if count < 0:
        raise ValueError("GA4 negative totalUsers")
    return count


def visitor_stats(ga4: GA4Reports, today: date) -> dict:
    week_start = today - timedelta(days=6)
    dates = [week_start + timedelta(days=i) for i in range(7)]
    result = {
        "visitorStatus": "unavailable",
        "visitorPeriods": {},
        "todayVisitors": None,
        "totalVisitors": None,
        "monthVisitors": None,
        "weekVisitors": None,
        "dayChangePct": None,
        "weekChangePct": None,
        "dailyVisitors": [{"date": day.isoformat(), "count": None} for day in dates],
    }
    if not ga4.property_id or not ga4.start_date:
        return result
    try:
        first = date.fromisoformat(ga4.start_date)
        if first > today:
            return {**result, "visitorStatus": "empty"}
        periods = {
            "dailyVisitors": (max(first, week_start), today),
            "totalVisitors": (first, today),
            "monthVisitors": (max(first, today.replace(day=1)), today),
        }
        if first <= week_start:
            periods["weekVisitors"] = (week_start, today)
        prior_start = week_start - timedelta(days=7)
        if first <= prior_start:
            periods["previousWeekVisitors"] = (prior_start, week_start - timedelta(days=1))
        ranges = {name: {"startDate": start.isoformat(), "endDate": end.isoformat()}
                  for name, (start, end) in periods.items()}
        requests = [
            {"dateRanges": [period], "metrics": [{"name": "totalUsers"}],
             **({"dimensions": [{"name": "date"}]} if name == "dailyVisitors" else {})}
            for name, period in ranges.items()
        ]
        daily_rows, *totals = map(report_rows, ga4.run(requests))
        daily = {}
        for row in daily_rows:
            day = datetime.strptime(row["dimensionValues"][0]["value"], "%Y%m%d").date()
            if not max(first, week_start) <= day <= today or day in daily:
                raise ValueError("GA4 unexpected date")
            daily[day] = user_count(row)
        counts = {}
        for name, rows in zip(list(ranges)[1:], totals, strict=True):
            if len(rows) > 1:
                raise ValueError("GA4 unexpected total")
            counts[name] = user_count(rows[0]) if rows else None
    except Exception:
        # ADC 파일명, 인증 정보, 원격 응답 본문을 응답이나 로그에 남기지 않는다.
        return result

    daily_values = [daily.get(day, 0) if daily and day >= first else None for day in dates]
    previous_week = counts.pop("previousWeekVisitors", None)
    return {
        **result,
        **counts,
        "visitorStatus": "ok" if daily or any(value is not None for value in counts.values()) else "empty",
        "visitorPeriods": ranges,
        "dailyVisitors": [{"date": day.isoformat(), "count": value} for day, value in zip(dates, daily_values)],
        "todayVisitors": daily_values[-1],
        "dayChangePct": change_pct(daily_values[-1], daily_values[-2]),
        "weekChangePct": change_pct(counts.get("weekVisitors"), previous_week),
    }


def search_stats(store, start: datetime, end: datetime) -> dict:
    try:
        total, origins, destinations = store.site_search_stats(start, end)
    except Exception:
        return {"searchStatus": "unavailable", "totalSearches": None,
                "popularOrigins": [], "popularDestinations": []}
    return {"searchStatus": "ok", "totalSearches": total,
            "popularOrigins": origins, "popularDestinations": destinations}


def site_stats(ga4: GA4Reports, store, now: datetime) -> dict:
    now = now.astimezone(KST)
    today = now.date()
    start = today - timedelta(days=6)
    return {
        "timeZone": "Asia/Seoul",
        "from": start.isoformat(),
        "to": today.isoformat(),
        **search_stats(store, datetime.combine(start, time.min, KST), now),
        **visitor_stats(ga4, today),
    }
