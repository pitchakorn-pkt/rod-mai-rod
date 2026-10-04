"""น้ำท่วมนับเฉพาะถนนที่ท่วมจริงบนเส้นทาง (road_cells จาก GISTDA) แทนรัศมีรอบกลางตำบล"""
from fastapi.testclient import TestClient

import app as appmod

T = "2026-09-24T00:00:00Z"
# ถนนตรงแนวเหนือใต้ที่ลองจิจูด 100.0 ยาว ~44 กม. จุดตรวจ 3 จุด
LINE = [{"lat": 14.0 + i * 0.01, "lng": 100.0} for i in range(41)]
POINTS = [{"lat": 14.0, "lng": 100.0, "eta": T}, {"lat": 14.2, "lng": 100.0, "eta": T}, {"lat": 14.4, "lng": 100.0, "eta": T}]


def flood(hid, lat, lng, road_cells, severity="HIGH"):
    return {"hazard_id": hid, "hazard_type": "FLOOD", "severity": severity, "lat": lat, "lng": lng,
            "province": None, "title_th": f"น้ำท่วม {hid}", "source": "GISTDA", "updated_at": T, "road_cells": road_cells}


def test_hit_only_when_a_flooded_road_cell_touches_the_route():
    on_road = flood("on", 14.3, 100.05, [[14.201, 100.003]])  # ช่องถนนท่วมห่างถนนเรา ~0.3 กม.
    off_road = flood("off", 14.2, 100.0, [[14.2, 100.03]])  # กลางตำบลทับถนน แต่ถนนที่ท่วมห่าง ~3 กม.
    fields = flood("fields", 14.2, 100.0, [])  # ท่วมแต่นา ไม่มีถนนท่วม
    hits = appmod.road_flood_hits(LINE, [on_road, off_road, fields])
    assert [h["hazard_id"] for h, _ in hits] == ["on"]


def _evaluate(monkeypatch, hazards, geometry):
    def fake_call(url_env, method, path, *, timeout, json=None, params=None, headers=None):
        if path == "/api/v1/forecast/points":
            return {"points": [{"forecast": {"rain_mm_per_h": 0, "wind_kmh": 5}} for _ in json["points"]], "warnings": []}
        if path == "/api/v1/hazards":
            return {"hazards": hazards}
        raise AssertionError(path)
    monkeypatch.setattr(appmod, "call", fake_call)
    route = {"route_id": "r1", "duration_min": 40, "points": POINTS}
    if geometry:
        route["geometry"] = geometry
    return TestClient(appmod.app).post("/api/v1/risk/evaluate", json={"routes": [route]}).json()["data"]


def test_flooded_fields_near_route_no_longer_make_the_trip_high(monkeypatch):
    fields = flood("fields", 14.2, 100.02, [])
    assert _evaluate(monkeypatch, [fields], LINE)["routes"][0]["risk_level"] == "LOW"
    # ไม่ส่งเส้นทางมา (routing-engine เดิม) ยังใช้รัศมีแบบเดิม
    assert _evaluate(monkeypatch, [fields], None)["routes"][0]["risk_level"] == "HIGH"


def test_flooded_road_on_route_is_high_at_the_nearest_check_point(monkeypatch):
    data = _evaluate(monkeypatch, [flood("on", 14.5, 100.2, [[14.39, 100.001]])], LINE)
    assert data["routes"][0]["risk_level"] == "HIGH"
    assert "น้ำท่วม on" in data["summary_th"]


def doh_closure(hid, lat, lng, severity="HIGH", hazard_type="FLOOD"):
    """รูปแบบเดียวกับที่ weather-disaster/doh.py ส่งมา: จุดเหตุบนทางหลวง = road_cells จุดเดียว"""
    return {"hazard_id": hid, "hazard_type": hazard_type, "severity": severity, "lat": lat, "lng": lng,
            "province": None, "title_th": f"ปิดถนน {hid}", "source": "DOH", "updated_at": T,
            "road_cells": [[round(lat, 4), round(lng, 4)]]}


def test_highway_closure_on_route_makes_it_high(monkeypatch):
    data = _evaluate(monkeypatch, [doh_closure("doh-1", 14.25, 100.0)], LINE)
    assert data["routes"][0]["risk_level"] == "HIGH"
    assert "ปิดถนน doh-1" in data["summary_th"]


def test_highway_closure_on_another_road_is_ignored(monkeypatch):
    # ทางหลวงอีกสายห่างไป ~3 กม. ไม่ใช่ถนนที่เราวิ่ง (รัศมี 10 กม. แบบเดิมจะนับผิด)
    data = _evaluate(monkeypatch, [doh_closure("doh-2", 14.25, 100.03)], LINE)
    assert data["routes"][0]["risk_level"] == "LOW"


def test_passable_highway_flood_does_not_raise_risk(monkeypatch):
    data = _evaluate(monkeypatch, [doh_closure("doh-3", 14.25, 100.0, severity="LOW")], LINE)
    assert data["routes"][0]["risk_level"] == "LOW"


def test_landslide_on_route_counts_through_road_point(monkeypatch):
    data = _evaluate(monkeypatch, [doh_closure("doh-4", 14.25, 100.0, severity="MEDIUM", hazard_type="LANDSLIDE_RISK")], LINE)
    assert data["routes"][0]["risk_level"] == "MEDIUM"
