"""8.8: ทริปที่ใกล้ที่สุด + สร้างทริป / แก้ต้นทาง ปลายทาง จุดแวะ / แนะนำที่เที่ยว จากแชท"""
from datetime import datetime, timezone

import rules
import tools
from envelope import ApiError
from test_rules import AUTH, FakeBackend, trip

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
PLACES = {
    "กรุงเทพ": {"name": "กรุงเทพมหานคร", "lat": 13.75, "lng": 100.5},
    "เชียงใหม่": {"name": "เชียงใหม่", "lat": 18.79, "lng": 98.98},
    "นครสวรรค์": {"name": "นครสวรรค์", "lat": 15.7, "lng": 100.14},
    "ลำปาง": {"name": "ลำปาง", "lat": 18.29, "lng": 99.49},
}
BKK, CNX = PLACES["กรุงเทพ"], PLACES["เชียงใหม่"]


def full(no, departure, **extra):
    return {**trip(no, departure), "origin": BKK, "destination": CNX, "waypoints": [], **extra}


class PlacesBackend(FakeBackend):
    """FakeBackend + ค้นสถานที่ ที่เที่ยวใกล้ตัว และสร้างทริป"""

    def __call__(self, method, path, auth, json=None, params=None):
        if path == "/api/v1/places/search":
            self.calls.append((method, path, params))
            hit = PLACES.get(params["q"])
            return {"places": [hit] if hit else []}
        if path == "/api/v1/places/nearby":
            self.calls.append((method, path, params))
            return {"places": [{"name": "ประตูท่าแพ", "kind_th": "สถานที่ท่องเที่ยว", "lat": 18.78, "lng": 98.99}]}
        if method == "POST" and path == "/api/v1/trips":
            self.calls.append((method, path, json))
            new = {**json, "trip_id": "id-9", "trip_no": 9, "plan_status": "NONE", "plan": None}
            self.trips["id-9"] = new
            return new
        return super().__call__(method, path, auth, json)


def run(name, args, be):
    return tools.run(name, args, be, AUTH)


# ---------- ทริปที่ใกล้ที่สุด ----------

def test_rules_move_nearest_trip_picks_next_upcoming_one():
    # Trip 1 ออกไปแล้ว, Trip 3 ออกทีหลัง Trip 2 > "ทริปที่ใกล้ที่สุด" = Trip 2
    be = FakeBackend([full(1, "2029-12-30T01:00:00Z"), full(2, "2030-01-03T01:00:00Z"), full(3, "2030-01-09T01:00:00Z")])
    out = rules.try_rules("เลื่อนทริปที่ใกล้ที่สุดไปพรุ่งนี้", AUTH, be, now=NOW)
    assert ("PATCH", "/api/v1/trips/id-2", {"departure_time": "2030-01-04T01:00:00Z"}) in be.calls
    assert out["actions"][0]["trip_no"] == 2


def test_without_nearest_word_still_asks_which_trip():
    be = FakeBackend([full(1, "2030-01-03T01:00:00Z"), full(2, "2030-01-09T01:00:00Z")])
    out = rules.try_rules("เลื่อนทริปไปพรุ่งนี้", AUTH, be, now=NOW)
    assert "หมายถึงทริปไหน" in out["reply"] and not be.patched()


def test_context_marks_nearest_trip_and_thai_time():
    text = tools.context_text([full(1, "2029-12-30T01:00:00Z"), full(2, "2030-01-03T01:00:00Z")], now=NOW)
    assert "2030-01-01 07:00" in text  # เวลาไทย
    assert "Trip 02 (ทริปที่ใกล้ที่สุด): กรุงเทพมหานคร > เชียงใหม่ ออก 3 ม.ค. 08:00 น." in text
    assert "Trip 01 (ทริปที่ใกล้ที่สุด)" not in text


# ---------- สร้างทริป ----------

def test_create_trip_resolves_names_then_plans():
    be = PlacesBackend([])
    out, actions = run("create_trip", {"origin": "กรุงเทพ", "destination": "เชียงใหม่", "date": "2099-01-05",
                                       "time": "12:00", "stops": ["นครสวรรค์"]}, be)
    body = next(c[2] for c in be.calls if c[:2] == ("POST", "/api/v1/trips"))
    assert body == {"origin": BKK, "destination": CNX, "departure_time": "2099-01-05T05:00:00Z",
                    "waypoints": [PLACES["นครสวรรค์"]]}
    assert ("POST", "/api/v1/trips/id-9/plan", None) in be.calls
    assert out["created"] and out["route_th"] == "กรุงเทพมหานคร > นครสวรรค์ > เชียงใหม่"
    assert out["plan"]["risk_th"] == "ต่ำ"
    assert actions == [{"type": "TRIP_CREATED", "trip_id": "id-9", "trip_no": 9}]


def test_create_trip_unknown_place_asks_instead_of_creating():
    be = PlacesBackend([])
    out, actions = run("create_trip", {"origin": "กรุงเทพ", "destination": "เมืองลับแล", "date": "2099-01-05", "time": "12:00"}, be)
    assert "ไม่เจอ" in out["error"] and actions == []
    assert not any(c[:2] == ("POST", "/api/v1/trips") for c in be.calls)


def test_create_trip_needs_date_and_time_and_future():
    be = PlacesBackend([])
    out, _ = run("create_trip", {"origin": "กรุงเทพ", "destination": "เชียงใหม่", "date": "2099-01-05"}, be)
    assert "เวลาออก" in out["error"]
    out, _ = run("create_trip", {"origin": "กรุงเทพ", "destination": "เชียงใหม่", "date": "2000-01-05", "time": "09:00"}, be)
    assert "ผ่านไปแล้ว" in out["error"]


# ---------- แก้ต้นทาง ปลายทาง จุดแวะ ----------

def test_update_places_changes_only_given_fields_then_plans():
    be = PlacesBackend([full(1, "2099-01-05T01:00:00Z", waypoints=[PLACES["นครสวรรค์"]])])
    out, actions = run("update_trip_places", {"trip_no": 1, "destination": "ลำปาง", "stops": []}, be)
    assert be.patched() == [{"destination": PLACES["ลำปาง"], "waypoints": []}]
    assert out["route_th"] == "กรุงเทพมหานคร > ลำปาง"
    assert ("POST", "/api/v1/trips/id-1/plan", None) in be.calls
    assert actions == [{"type": "TRIP_UPDATED", "trip_id": "id-1", "trip_no": 1}]


def test_update_places_rejects_more_than_five_stops():
    be = PlacesBackend([full(1, "2099-01-05T01:00:00Z")])
    out, actions = run("update_trip_places", {"trip_no": 1, "stops": ["ลำปาง"] * 6}, be)
    assert "ไม่เกิน 5" in out["error"] and actions == [] and not be.patched()


# ---------- แนะนำที่เที่ยว ----------

def test_nearby_places_returns_real_places_around_named_city():
    out, actions = run("nearby_places", {"place": "เชียงใหม่"}, PlacesBackend([]))
    assert out == {"around": "เชียงใหม่", "places": [{"name": "ประตูท่าแพ", "kind_th": "สถานที่ท่องเที่ยว"}]}
    assert actions == []


def test_nearby_places_asks_again_once_after_first_timeout():
    class SlowOnce(PlacesBackend):
        slow = True

        def __call__(self, method, path, auth, json=None, params=None):
            if path == "/api/v1/places/nearby" and self.slow:
                self.slow = False
                raise ApiError("UPSTREAM_TIMEOUT", "ยังโหลดไม่เสร็จ")
            return super().__call__(method, path, auth, json, params)

    out, _ = run("nearby_places", {"place": "เชียงใหม่"}, SlowOnce([]))
    assert out["places"][0]["name"] == "ประตูท่าแพ"


def test_nearby_places_passes_style_kinds_and_radius():
    be = PlacesBackend([])
    run("nearby_places", {"place": "เชียงใหม่", "kinds": ["cafe", "mall"], "radius_km": 50}, be)
    params = next(c[2] for c in be.calls if c[1] == "/api/v1/places/nearby")
    assert params["kinds"] == "cafe,mall" and params["radius_km"] == 20


# ---------- อากาศและภัยรอบสถานที่ (ไม่ใช่ทริป) ----------

class ConditionsBackend(PlacesBackend):
    def __init__(self, cells, hazards, warnings=()):
        super().__init__([])
        self.cells, self.hazards, self.warnings = cells, hazards, list(warnings)

    def __call__(self, method, path, auth, json=None, params=None):
        if path == "/api/v1/weather/area":
            return {"center": params, "cells": self.cells, "warnings": self.warnings}
        if path == "/api/v1/hazards":
            self.calls.append((method, path, params))
            return {"hazards": self.hazards, "warnings": []}
        return super().__call__(method, path, auth, json, params)


def cell(lat, lng, rain):
    return {"lat": lat, "lng": lng, "forecast": {"time": "2030-01-01T05:00:00Z", "rain_mm_per_h": rain, "wind_kmh": 6,
                                                  "temp_c": 30, "condition_th": "ฝนตก" if rain else "ท้องฟ้าโปร่ง"}}


def hazard(hid, lat, lng, **extra):
    return {"hazard_id": hid, "hazard_type": "FLOOD", "severity": "HIGH", "lat": lat, "lng": lng,
            "title_th": f"น้ำท่วม {hid}", "source": "GISTDA", **extra}


def test_place_conditions_reports_weather_rain_and_nearby_hazards_only():
    be = ConditionsBackend(
        [cell(15.7, 100.14, 0), cell(15.9, 100.3, 12.5), cell(15.5, 100.0, 0)],
        [hazard("road", 15.75, 100.2, road_cells=[[15.71, 100.15]]),
         hazard("fields", 15.72, 100.1, road_cells=[]),
         hazard("far", 17.0, 101.0),
         {**hazard("now", 15.7, 100.14), "hazard_type": "RAIN", "source": "OPEN_METEO"}])
    out, actions = run("place_conditions", {"place": "นครสวรรค์"}, be)
    assert actions == [] and out["place"] == "นครสวรรค์"
    assert out["weather_now"]["condition_th"] == "ท้องฟ้าโปร่ง" and out["weather_now"]["time_th"] == "1 ม.ค. 12:00 น."
    assert out["rain_around_th"].startswith("ฝนตก 1 จาก 3 จุด") and "12.5 มม./ชม." in out["rain_around_th"]
    assert [h["title_th"] for h in out["hazards"]] == ["น้ำท่วม fields", "น้ำท่วม road"]  # เรียงใกล้ไปไกล ตัดที่ไกลและฝนตอนนี้
    assert out["hazards"][0]["flooded_road_th"] == "ท่วมพื้นที่เกษตร ไม่มีถนนท่วม"
    assert out["hazards"][1]["flooded_road_th"].startswith("ถนนที่ท่วมใกล้สุดห่าง 1.")
    assert out["hazards"][1]["severity_th"] == "สูง" and out["hazards_th"] == "มีภัย 2 จุดในรัศมี 30 กม."


def test_place_conditions_says_so_when_weather_is_unavailable():
    out, _ = run("place_conditions", {"place": "นครสวรรค์"}, ConditionsBackend([], [], ["WEATHER_UNAVAILABLE"]))
    assert out["weather_now"] == "ดึงข้อมูลอากาศไม่ได้ตอนนี้" and out["warnings"] == ["WEATHER_UNAVAILABLE"]
    assert out["hazards"] == [] and out["hazards_th"] == "ไม่มีภัยในรัศมี 30 กม."


def test_place_conditions_asks_again_for_unknown_place():
    out, _ = run("place_conditions", {"place": "ไม่มีที่นี่"}, ConditionsBackend([], []))
    assert "ไม่เจอ" in out["error"]


# ---------- ภัยตอนนี้ทั้งประเทศ / รายจังหวัด ----------

def test_hazards_now_country_wide_puts_closed_highways_first():
    be = ConditionsBackend([], [
        hazard("sat", 15.7, 100.1, province="นครสวรรค์"),
        {**hazard("doh-closed", 15.71, 100.08, province="นครสวรรค์"), "source": "DOH", "title_th": "ทล.1 กม.345+700 · ปิดถนน"},
        {**hazard("doh-low", 14.0, 100.6, province="ปทุมธานี"), "source": "DOH", "severity": "LOW"},
        {**hazard("slide", 18.5, 98.9, province="เชียงใหม่"), "hazard_type": "LANDSLIDE_RISK", "severity": "MEDIUM", "source": "DOH"},
        {**hazard("now", 13.7, 100.5), "hazard_type": "RAIN", "source": "OPEN_METEO"},
    ])
    out, actions = run("hazards_now", {}, be)
    assert actions == []
    assert be.calls[-1][2] == tools.THAILAND_BOX
    assert [h["title_th"] for h in out["hazards"]][:2] == ["ทล.1 กม.345+700 · ปิดถนน", "น้ำท่วม sat"]  # สูงก่อน ถนนปิดก่อน
    assert "น้ำท่วม now" not in [h["title_th"] for h in out["hazards"]]  # ฝนชั่วโมงนี้ไม่นับ
    assert out["summary_th"].startswith("ทั่วประเทศ มีภัย 4 จุด ระดับสูง 2 จุด") and "35 ซม. 1 จุด" in out["summary_th"]
    assert out["hazards"][0]["source_th"] == "กรมทางหลวง"
    assert [h["type_th"] for h in out["hazards"] if h["title_th"] == "น้ำท่วม slide"] == ["ดินถล่ม"]


def test_hazards_now_filters_by_province_and_type():
    be = ConditionsBackend([], [
        hazard("a", 15.7, 100.1, province="นครสวรรค์"),
        {**hazard("b", 18.5, 98.9, province="เชียงใหม่"), "hazard_type": "LANDSLIDE_RISK"},
    ])
    out, _ = run("hazards_now", {"province": "จังหวัดนครสวรรค์"}, be)
    assert [h["title_th"] for h in out["hazards"]] == ["น้ำท่วม a"] and out["summary_th"].startswith("จังหวัดนครสวรรค์ มีภัย 1 จุด")
    out, _ = run("hazards_now", {"hazard_type": "LANDSLIDE_RISK"}, be)
    assert [h["title_th"] for h in out["hazards"]] == ["น้ำท่วม b"]
    out, _ = run("hazards_now", {"province": "ภูเก็ต"}, be)
    assert out["hazards"] == [] and out["summary_th"] == "จังหวัดภูเก็ต ไม่มีรายงานภัยตอนนี้"


# ---------- เบอร์ฉุกเฉินจากระบบเท่านั้น ----------

class SafetyBackend(PlacesBackend):
    def __call__(self, method, path, auth, json=None, params=None):
        if path == "/api/v1/safety/emergency":
            self.calls.append((method, path, params))
            return {"hazard_type": params["hazard_type"], "steps_th": ["ห้ามขับผ่านน้ำสูง"],
                    "contacts": [{"name_th": "เจ็บป่วยฉุกเฉิน", "phone": "1669"}]}
        return super().__call__(method, path, auth, json, params)


def test_emergency_info_gives_only_system_numbers():
    be = SafetyBackend([])
    out, actions = run("emergency_info", {}, be)
    assert out["contacts"] == [{"name_th": "เจ็บป่วยฉุกเฉิน", "phone": "1669"}] and "steps_th" not in out and actions == []
    out, _ = run("emergency_info", {"hazard_type": "FLOOD"}, be)
    assert out["steps_th"] == ["ห้ามขับผ่านน้ำสูง"]
    run("emergency_info", {"hazard_type": "ZOMBIE"}, be)  # ชนิดแปลกไม่ส่งต่อ ใช้แค่เบอร์
    assert be.calls[-1][2] == {"hazard_type": "FLOOD"}


# ---------- ต้นทาง = ตำแหน่งปัจจุบันจาก GPS ----------

HERE = {"lat": 14.0357, "lng": 100.727}


def test_create_trip_from_current_location_uses_gps_without_search():
    be = PlacesBackend([])
    out, acts = tools.run("create_trip", {"origin": "ตำแหน่งปัจจุบัน", "destination": "เชียงใหม่",
                                          "date": "2099-01-05", "time": "13:00"}, be, AUTH, HERE)
    created = next(c[2] for c in be.calls if c[:2] == ("POST", "/api/v1/trips"))
    assert created["origin"] == {**HERE, "name": "ตำแหน่งปัจจุบัน"} and created["destination"] == CNX
    assert not any(c[1] == "/api/v1/places/search" and c[2]["q"] == "ตำแหน่งปัจจุบัน" for c in be.calls)
    assert acts and acts[0]["type"] == "TRIP_CREATED"


def test_return_trip_can_end_at_current_location():
    be = PlacesBackend([])
    tools.run("create_trip", {"origin": "เชียงใหม่", "destination": "current location",
                              "date": "2099-01-07", "time": "13:00"}, be, AUTH, HERE)
    created = next(c[2] for c in be.calls if c[:2] == ("POST", "/api/v1/trips"))
    assert created["destination"]["lat"] == HERE["lat"]


def test_current_location_unknown_asks_for_origin():
    be = PlacesBackend([])
    out, acts = tools.run("create_trip", {"origin": "ตำแหน่งปัจจุบัน", "destination": "เชียงใหม่",
                                          "date": "2099-01-05", "time": "13:00"}, be, AUTH)
    assert "ยังไม่รู้ตำแหน่งปัจจุบัน" in out["error"] and acts == []


def test_same_route_and_time_is_not_created_twice():
    be = PlacesBackend([])
    args = {"origin": "ตำแหน่งปัจจุบัน", "destination": "เชียงใหม่", "date": "2099-01-05", "time": "13:00"}
    _, first = tools.run("create_trip", args, be, AUTH, HERE)
    out, second = tools.run("create_trip", args, be, AUTH, HERE)
    assert first and second == [] and "อยู่แล้ว" in out["error"]
    assert sum(c[:2] == ("POST", "/api/v1/trips") for c in be.calls) == 1
    # ขากลับ (สลับทาง) หรือคนละเวลา ยังสร้างได้
    _, back = tools.run("create_trip", {**args, "origin": "เชียงใหม่", "destination": "ตำแหน่งปัจจุบัน"}, be, AUTH, HERE)
    assert back
