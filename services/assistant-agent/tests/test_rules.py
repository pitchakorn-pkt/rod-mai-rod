from datetime import datetime, timezone

import pytest

import rules
from envelope import ApiError

AUTH = "Bearer user-a"
NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


class FakeBackend:
    """แทน api-backend จดทุกคำขอไว้ให้เทสต์ตรวจ"""

    def __init__(self, trips, plan_fails=False, plan_warnings=None):
        self.trips = {t["trip_id"]: t for t in trips}
        self.calls = []
        self.plan_fails = plan_fails
        self.plan_warnings = plan_warnings or []

    def __call__(self, method, path, auth, json=None):
        assert auth == AUTH  # ต้องใช้ token ของผู้ใช้เสมอ
        self.calls.append((method, path, json))
        if method == "GET" and path == "/api/v1/trips":
            return list(self.trips.values())
        tid = path.split("/")[4]
        if method == "GET":
            return self.trips[tid]
        if method == "PATCH":
            self.trips[tid] = {**self.trips[tid], **json, "plan_status": "STALE"}
            return self.trips[tid]
        if method == "POST" and path.endswith("/plan"):
            if self.plan_fails:
                raise ApiError("UPSTREAM_TIMEOUT", "ระบบ routing-engine ตอบไม่ทันเวลา")
            return {"risk_level": "LOW", "summary_th": "สภาพอากาศตลอดเส้นทางปกติ", "warnings": self.plan_warnings}
        raise AssertionError(path)

    def patched(self):
        return [c[2] for c in self.calls if c[0] == "PATCH"]


def trip(no, departure, plan=None):
    return {"trip_id": f"id-{no}", "trip_no": no, "departure_time": departure,
            "plan_status": "FRESH" if plan else "NONE", "plan": plan}


def run(message, backend):
    return rules.try_rules(message, AUTH, backend, now=NOW)


@pytest.mark.parametrize("text", ["เลื่อน Trip 01 ไปวันถัดไป", "เลื่อนทริป 1 ไปพรุ่งนี้", "ช่วยเลื่อน trip1 ไปอีกวันหน่อย"])
def test_next_day_patches_then_replans(text):
    be = FakeBackend([trip(1, "2030-01-05T01:00:00Z")])
    out = run(text, be)
    assert be.patched() == [{"departure_time": "2030-01-06T01:00:00Z"}]
    assert ("POST", "/api/v1/trips/id-1/plan", None) in be.calls
    assert out["actions"] == [{"type": "TRIP_UPDATED", "trip_id": "id-1", "trip_no": 1}]
    assert "Trip 01" in out["reply"] and "ต่ำ" in out["reply"]


def test_afternoon_uses_thai_date_not_utc_date():
    # 18:30Z วันที่ 5 = ตีหนึ่งครึ่งวันที่ 6 เวลาไทย บ่ายโมงต้องเป็นวันที่ 6 ตามเวลาไทย = 06:00Z วันที่ 6
    be = FakeBackend([trip(1, "2030-01-05T18:30:00Z")])
    run("เลื่อน Trip 01 เป็นช่วงบ่าย", be)
    assert be.patched() == [{"departure_time": "2030-01-06T06:00:00Z"}]


@pytest.mark.parametrize("word, utc_hour", [("เช้า", "01"), ("บ่าย", "06"), ("เย็น", "10")])
def test_periods(word, utc_hour):
    be = FakeBackend([trip(2, "2030-01-05T03:00:00Z")])
    run(f"เลื่อน Trip 02 เป็นตอน{word}", be)
    assert be.patched() == [{"departure_time": f"2030-01-05T{utc_hour}:00:00Z"}]


def test_next_morning_combines_day_and_period():
    be = FakeBackend([trip(1, "2030-01-05T10:00:00Z")])  # 17:00 วันที่ 5 เวลาไทย
    run("เลื่อน Trip 01 ไปพรุ่งนี้เช้า", be)
    assert be.patched() == [{"departure_time": "2030-01-06T01:00:00Z"}]


def test_weather_summarises_plan_waypoints():
    plan = {"risk_level": "MEDIUM", "summary_th": "ฝนปานกลางช่วงนครสวรรค์", "waypoints": [
        {"name": "กรุงเทพ", "eta": "2030-01-05T01:00:00Z",
         "forecast": {"condition_th": "มีเมฆ", "rain_mm_per_h": 0.2, "wind_kmh": 9}},
        {"name": "นครสวรรค์", "eta": "2030-01-05T04:00:00Z", "forecast": None},
    ]}
    be = FakeBackend([trip(1, "2030-01-05T01:00:00Z", plan)])
    out = run("Trip 01 อากาศเป็นยังไง", be)
    assert "ปานกลาง" in out["reply"] and "5 ม.ค. 08:00 น." in out["reply"]
    assert "ยังไม่มีข้อมูลอากาศ" in out["reply"]
    assert out["actions"] == [] and be.patched() == []


def test_weather_without_plan_asks_to_plan_first():
    out = run("Trip 01 อากาศเป็นยังไง", FakeBackend([trip(1, "2030-01-05T01:00:00Z")]))
    assert "ยังไม่ได้วางแผน" in out["reply"]


def test_ambiguous_trip_asks_back_and_changes_nothing():
    be = FakeBackend([trip(1, "2030-01-05T01:00:00Z"), trip(2, "2030-01-07T01:00:00Z")])
    out = run("เลื่อนไปพรุ่งนี้", be)
    assert "Trip 01" in out["reply"] and "Trip 02" in out["reply"]
    assert be.patched() == []


def test_single_trip_is_used_without_number():
    be = FakeBackend([trip(3, "2030-01-05T01:00:00Z")])
    run("เลื่อนไปวันถัดไป", be)
    assert be.patched() == [{"departure_time": "2030-01-06T01:00:00Z"}]


def test_unknown_trip_number():
    be = FakeBackend([trip(1, "2030-01-05T01:00:00Z")])
    out = run("เลื่อน Trip 09 ไปวันถัดไป", be)
    assert "ไม่เจอ Trip 09" in out["reply"] and be.patched() == []


def test_new_time_in_the_past_is_refused():
    be = FakeBackend([trip(1, "2029-12-31T18:30:00Z")])  # ตีหนึ่งครึ่ง 1 ม.ค. เวลาไทย เช้า 08:00 = 01:00Z ยังไม่ผ่าน
    run("เลื่อน Trip 01 เป็นช่วงเช้า", be)
    assert be.patched() == [{"departure_time": "2030-01-01T01:00:00Z"}]
    be = FakeBackend([trip(1, "2029-12-30T01:00:00Z")])
    out = run("เลื่อน Trip 01 เป็นช่วงบ่าย", be)
    assert "ผ่านไปแล้ว" in out["reply"] and be.patched() == []


def test_move_beyond_forecast_range_says_why_risk_is_unknown():
    be = FakeBackend([trip(1, "2030-01-05T01:00:00Z")], plan_warnings=["FORECAST_OUT_OF_RANGE"])
    out = run("เลื่อน Trip 01 ไปวันถัดไป", be)
    assert "ไกลเกินช่วงพยากรณ์" in out["reply"]
    assert "ไกลเกิน" not in run("เลื่อน Trip 01 ไปวันถัดไป", FakeBackend([trip(1, "2030-01-05T01:00:00Z")]))["reply"]


def test_plan_failure_still_reports_the_move_honestly():
    be = FakeBackend([trip(1, "2030-01-05T01:00:00Z")], plan_fails=True)
    out = run("เลื่อน Trip 01 ไปวันถัดไป", be)
    assert out["actions"][0]["type"] == "TRIP_UPDATED"
    assert "ไม่สำเร็จ" in out["reply"]


def test_backend_error_is_not_reported_as_success():
    def down(*a, **k):
        raise ApiError("UNAUTHORIZED", "กรุณาเข้าสู่ระบบก่อน")
    out = rules.try_rules("เลื่อน Trip 01 ไปวันถัดไป", AUTH, down, now=NOW)
    assert "ไม่สำเร็จ" in out["reply"] and out["actions"] == []


@pytest.mark.parametrize("text", ["เชียงใหม่น่าเที่ยวไหม", "น้ำท่วมต้องทำยังไง", "อากาศวันนี้เป็นไง"])
def test_other_messages_go_to_llm(text):
    assert rules.parse(text) is None


@pytest.mark.parametrize("text", [
    "ช่วยเลื่อนทริปที่ 1 ออกไปอีก 2 วัน ออกตอน 9 โมงเช้า",
    "เลื่อน Trip 01 เป็นช่วงเช้า 7 โมง",
    "เลื่อน Trip 01 ไป 13:30",
])
def test_specific_day_or_time_goes_to_llm_not_a_wrong_rule(text):
    # กฎรู้แค่ "วันถัดไป" กับช่วงเช้า/บ่าย/เย็น ถ้ารับไปจะเลื่อนผิดเวลาโดยไม่บอกผู้ใช้
    assert rules.parse(text) is None


@pytest.mark.parametrize("text, kind, trip_no", [
    ("เลื่อนทริปที่ 2 ไปวันถัดไป", "next_day", 2),
    ("เลื่อน Trip 01 ไปอีก 1 วัน", "next_day", 1),
    ("ทริปที่ 1 อากาศเป็นยังไง", "weather", 1),
])
def test_trip_number_written_the_thai_way(text, kind, trip_no):
    cmd = rules.parse(text)
    assert cmd["kind"] == kind and cmd["trip_no"] == trip_no


@pytest.mark.parametrize("text", [
    "ถ้าเลื่อน Trip 01 ไปออกบ่ายแล้วจะเสี่ยงน้อยลงไหม",
    "หากเลื่อนทริปไปวันถัดไปจะดีกว่าไหม",
    "เลื่อน Trip 01 เป็นช่วงเย็นดีมั้ย",
    "เลื่อนทริปไปพรุ่งนี้ได้หรือเปล่า?",
])
def test_what_if_questions_never_move_a_trip(text):
    # ถามแบบสมมติ ไม่ใช่คำสั่ง กฎต้องไม่เลื่อนทริปจริง (ให้ LLM ตอบ)
    assert rules.parse(text) is None
