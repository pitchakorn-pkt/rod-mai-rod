import json
from pathlib import Path

import httpx

import doh
import hazard_feeds

# ตัวอย่างจริงจาก HDMS 4 ต.ค. 2569: ปิดถนน, น้ำ 35 ซม., น้ำ 25 ซม., น้ำ 2 ซม., ดินสไลด์, เหตุที่จบแล้ว
SAMPLE = json.loads((Path(__file__).parent / "hdms_sample.json").read_text(encoding="utf-8"))
CLOSED, DEEP, HARD, SHALLOW, LANDSLIDE, ENDED = SAMPLE


def test_depth_takes_the_largest_number():
    assert doh.depth_cm("10-30 เป็นช่วงๆ") == 30
    assert doh.depth_cm("35") == 35
    assert doh.depth_cm("") == 0
    assert doh.depth_cm(None) == 0


def test_severity_follows_hdms_passage_rules():
    assert doh.to_hazard(CLOSED)["severity"] == "HIGH"  # ผ่านไม่ได้ แม้น้ำแค่ 13 ซม.
    assert doh.to_hazard(DEEP)["severity"] == "HIGH"  # 35 ซม. ขึ้นไป ผ่านไม่ได้
    assert doh.to_hazard(HARD)["severity"] == "MEDIUM"  # 15-34 ผ่านได้แต่ไม่สะดวก
    assert doh.to_hazard(SHALLOW)["severity"] == "LOW"
    assert doh.to_hazard(LANDSLIDE)["severity"] == "MEDIUM"


def test_hazard_shape_and_road_point():
    h = doh.to_hazard(CLOSED)
    assert h["hazard_type"] == "FLOOD" and h["source"] == "DOH"
    assert h["hazard_id"] == f"doh-{CLOSED['gid']}"
    assert h["road_cells"] == [[round(float(CLOSED["latitude"]), 4), round(float(CLOSED["longitude"]), 4)]]
    assert "ปิดถนน" in h["title_th"] and "ทางเลี่ยง" in h["title_th"]
    assert f"ทล.{CLOSED['road_code'].lstrip('0')} กม.{CLOSED['km_start']}" in h["title_th"]
    assert doh.to_hazard(LANDSLIDE)["hazard_type"] == "LANDSLIDE_RISK"


def test_ended_and_bad_rows_are_dropped():
    assert doh.to_hazard(ENDED) is None
    assert doh.to_hazard({**HARD, "latitude": None}) is None
    assert doh.to_hazard({**HARD, "incident_type_id": 99}) is None  # อุบัติเหตุ ฯลฯ ไม่ใช่ภัยธรรมชาติ
    assert doh.to_hazard({**HARD, "latitude": "35.0", "longitude": "139.0"}) is None  # นอกไทย
    assert len(doh.to_hazards(SAMPLE)) == 5
    assert doh.to_hazards({"error": "x"}) == []


def test_fetch_asks_open_window_and_maps(monkeypatch):
    asked = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        asked.update(url=url, params=params, timeout=timeout)
        return httpx.Response(200, json=SAMPLE, request=httpx.Request("GET", url))

    monkeypatch.setattr(doh.httpx, "get", fake_get)
    found = doh.fetch()
    assert asked["url"] == doh.HDMS_URL and {"start", "end"} <= set(asked["params"])
    assert asked["timeout"] == doh.TIMEOUT_S
    assert len(found) == 5


def test_failed_refresh_keeps_previous_result(monkeypatch):
    monkeypatch.setattr(doh, "_latest", [doh.to_hazard(CLOSED)])

    def boom(*a, **k):
        raise httpx.ConnectError("hdms down")

    monkeypatch.setattr(doh.httpx, "get", boom)
    doh.refresh_once()
    assert [h["hazard_id"] for h in doh.latest()] == [f"doh-{CLOSED['gid']}"]


def test_get_hazards_adds_doh_in_box_only_when_live(monkeypatch):
    for name in ("fetch_gdacs", "fetch_usgs", "derived_landslide", "current_weather",
                 "demo_gdacs", "demo_usgs"):
        monkeypatch.setattr(hazard_feeds, name, lambda box: [])
    monkeypatch.setattr(hazard_feeds, "_cache", {})
    monkeypatch.setattr(doh, "_latest", doh.to_hazards(SAMPLE))
    h = doh.to_hazard(CLOSED)
    box = (h["lat"] - 0.01, h["lng"] - 0.01, h["lat"] + 0.01, h["lng"] + 0.01)

    monkeypatch.setenv("DEMO_MODE", "false")
    found, _ = hazard_feeds.get_hazards(box, refresh=True)
    assert h["hazard_id"] in [x["hazard_id"] for x in found]

    monkeypatch.setenv("DOH_HDMS", "false")
    found, _ = hazard_feeds.get_hazards(box, refresh=True)
    assert h["hazard_id"] not in [x["hazard_id"] for x in found]

    monkeypatch.setenv("DOH_HDMS", "true")
    monkeypatch.setenv("DEMO_MODE", "true")  # โหมดสาธิตไม่ใช้ข้อมูลสด
    found, _ = hazard_feeds.get_hazards(box, refresh=True)
    assert h["hazard_id"] not in [x["hazard_id"] for x in found]
