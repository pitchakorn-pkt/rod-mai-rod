import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

import places
from envelope import ApiError
from geo import haversine_km

CNX = (18.79, 98.98)


def node(name, lat, lng, **tags):
    return {"type": "node", "lat": lat, "lon": lng, "tags": {"name": name, **tags}}


@pytest.fixture(autouse=True)
def empty_cache(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    places._nearby_cache.clear()
    places._nearby_pending.clear()
    monkeypatch.setattr("places._overpass_down_until", 0.0)
    # ตัวสำรอง Photon ห้ามยิงเน็ตจริงในเทสต์ ค่าเริ่มต้นให้ล่มด้วย เทสต์ error เดิมจะได้ error ของ Overpass ตามเดิม
    monkeypatch.setattr("places.httpx.get", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("offline")))


@pytest.fixture
def overpass(monkeypatch):
    """แทน Overpass จริง เทสต์ไม่ยิงเน็ต คืน list ของคำขอที่ถูกส่งไปให้ตรวจ"""
    sent = []

    def use(elements=(), error=None, body=None, delay=0):
        def fake_post(url, data=None, headers=None, timeout=None):
            sent.append({"data": data, "headers": headers, "timeout": timeout})
            time.sleep(delay)
            if error is not None:
                raise error
            request = httpx.Request("POST", url)
            if body is not None:
                return httpx.Response(200, content=body, request=request)
            return httpx.Response(200, json={"elements": list(elements)}, request=request)

        monkeypatch.setattr("places.httpx.post", fake_post)
        return sent

    return use


def test_one_request_with_radius_timeout_and_user_agent(overpass):
    sent = overpass()
    places.nearby(*CNX)
    assert len(sent) == 1
    query = sent[0]["data"]["data"]
    assert "[bbox:18.7450,98.9324,18.8350,99.0276]" in query  # กรอบ 5 กม. รอบ 18.79, 98.98
    assert "attraction|viewpoint|museum|zoo|theme_park" in query
    assert "monument|temple|ruins" in query
    # ตัวดาวน์โหลดรอ 30 วิ และบอก Overpass ให้ทำได้นานเท่ากัน ส่วนคำขอรอแค่ 8 วิ
    assert sent[0]["timeout"] == 30
    assert "[timeout:30]" in query
    assert "rod-mai-rod" in sent[0]["headers"]["User-Agent"]


def test_nearest_first_and_at_most_8(overpass):
    # วัด 10 แห่งห่างออกไปทางเหนือทีละประมาณ 200 ม. ส่งมาแบบกลับลำดับ
    overpass([node(f"วัด {i}", 18.79 + i * 0.002, 98.98, historic="temple") for i in reversed(range(10))])
    found = places.nearby(*CNX)
    assert [p["name"] for p in found] == [f"วัด {i}" for i in range(8)]


def test_name_th_is_preferred_and_detail_comes_from_addr(overpass):
    overpass([
        node("Tha Phae Gate", 18.7877, 98.9933, **{"name:th": "ประตูท่าแพ", "tourism": "attraction"}),
        node("Old City View", 18.80, 98.97, tourism="viewpoint",
             **{"addr:district": "อำเภอเมืองเชียงใหม่", "addr:province": "เชียงใหม่"}),
    ])
    found = places.nearby(*CNX)
    gate = next(p for p in found if p["name"] == "ประตูท่าแพ")
    assert list(gate) == ["name", "detail", "lat", "lng", "kind_th"]
    assert gate == {"name": "ประตูท่าแพ", "detail": None, "lat": 18.7877, "lng": 98.9933, "kind_th": "สถานที่ท่องเที่ยว"}
    view = next(p for p in found if p["kind_th"] == "จุดชมวิว")
    assert view["detail"] == "อำเภอเมืองเชียงใหม่, เชียงใหม่"


def test_every_kind_has_thai_label(overpass):
    tags = [("tourism", "attraction", "สถานที่ท่องเที่ยว"), ("tourism", "viewpoint", "จุดชมวิว"),
            ("tourism", "museum", "พิพิธภัณฑ์"), ("tourism", "zoo", "สวนสัตว์"),
            ("tourism", "theme_park", "สวนสนุก"), ("historic", "monument", "อนุสาวรีย์"),
            ("historic", "temple", "วัด"), ("historic", "ruins", "โบราณสถาน")]
    overpass([node(f"ที่ {i}", 18.79 + i * 0.001, 98.98, **{key: value}) for i, (key, value, _) in enumerate(tags)])
    found = places.nearby(*CNX)
    assert [p["kind_th"] for p in found] == [label for _, _, label in tags]


def test_same_cell_is_cached_for_24_hours(overpass, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("places.monotonic", lambda: now[0])
    sent = overpass([node("ประตูท่าแพ", 18.7877, 98.9933, tourism="attraction")])
    places.nearby(18.791, 98.981)
    places.nearby(18.788, 98.979)  # ปัดแล้วเป็น 18.79, 98.98 ช่องเดียวกัน
    assert len(sent) == 1
    places.nearby(18.83, 98.98)  # คนละช่อง
    assert len(sent) == 2
    now[0] += 24 * 60 * 60 + 1
    places.nearby(18.791, 98.981)
    assert len(sent) == 3


def test_outside_thailand_is_rejected_without_calling_overpass(overpass):
    sent = overpass()
    with pytest.raises(ApiError) as e:
        places.nearby(35.68, 139.76)
    assert e.value.code == "OUT_OF_THAILAND"
    assert sent == []


@pytest.mark.parametrize("broken", [{"error": httpx.ConnectError("down")}, {"body": b"<html>busy</html>"}])
def test_overpass_down_or_bad_json_is_upstream_error(overpass, broken):
    overpass(**broken)
    with pytest.raises(ApiError) as e:
        places.nearby(*CNX)
    assert e.value.code == "UPSTREAM_ERROR"


def test_overpass_slow_is_upstream_timeout_and_not_cached(overpass):
    overpass(error=httpx.ReadTimeout("slow"))
    with pytest.raises(ApiError) as e:
        places.nearby(*CNX)
    assert e.value.code == "UPSTREAM_TIMEOUT"
    sent = overpass([node("ประตูท่าแพ", 18.7877, 98.9933, tourism="attraction")])
    assert len(places.nearby(*CNX)) == 1
    # ครั้งที่ timeout ไม่ถูก cache จึงยิงใหม่เป็นครั้งที่ 2 (sent ใช้ list เดียวกันทั้งเทสต์)
    assert len(sent) == 2


def test_endpoint_needs_login(client, auth_header, overpass):
    overpass([node("ประตูท่าแพ", 18.7877, 98.9933, tourism="attraction")])
    url = "/api/v1/places/nearby"
    params = {"lat": 18.79, "lng": 98.98}
    assert client.get(url, params=params).status_code == 401
    res = client.get(url, params=params, headers=auth_header)
    assert res.status_code == 200
    assert res.json()["data"]["places"][0]["name"] == "ประตูท่าแพ"
    assert client.get(url, params={"lat": 35.68, "lng": 139.76}, headers=auth_header).status_code == 422


def test_concurrent_requests_in_same_cell_call_overpass_once(overpass):
    # จำลองสิ่งที่เจอใน log: หน้าเว็บยิงช่องเดียวกัน 2 คำขอพร้อมกันตอน Overpass ยังตอบไม่เสร็จ
    sent = overpass([node("ประตูท่าแพ", 18.7877, 98.9933, tourism="attraction")], delay=0.3)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda p: places.nearby(*p), [(18.791, 98.981), (18.788, 98.979)]))
    assert len(sent) == 1
    assert results[0] == results[1]


def test_slow_overpass_keeps_downloading_and_next_call_hits_cache(overpass, monkeypatch):
    # ย่อเวลา: คำขอรอ 0.1 วิ แต่ Overpass ตอบใน 0.3 วิ
    monkeypatch.setattr("places.OVERPASS_TIMEOUT", 0.1)
    sent = overpass([node("ประตูท่าแพ", 18.7877, 98.9933, tourism="attraction")], delay=0.3)
    with pytest.raises(ApiError) as e:
        places.nearby(*CNX)
    assert e.value.code == "UPSTREAM_TIMEOUT"
    time.sleep(0.5)  # เหมือนหน้าเว็บรอแล้วลองใหม่ ระหว่างนี้ดาวน์โหลดเบื้องหลังเสร็จ
    assert places.nearby(*CNX)[0]["name"] == "ประตูท่าแพ"
    assert len(sent) == 1


# ---------- หมวดสถานที่ + รัศมี (แชทแนะนำที่เที่ยวตามแนว) ----------

def test_kinds_and_radius_change_the_query_and_limit(overpass):
    cafes = [node(f"คาเฟ่ {i}", 18.79 + i * 0.001, 98.98, amenity="cafe") for i in range(25)]
    sent = overpass(cafes)
    found = places.nearby(*CNX, radius_km=15, kinds=("cafe",))
    query = sent[0]["data"]["data"]
    assert "[bbox:18.6549," in query and '["amenity"="cafe"]' in query
    assert "tourism" not in query
    assert len(found) == 20 and found[0]["kind_th"] == "คาเฟ่"


def test_way_uses_center_point(overpass):
    mall = {"type": "way", "center": {"lat": 18.79, "lon": 98.99}, "tags": {"name": "เซ็นทรัล", "shop": "mall"}}
    overpass([mall])
    found = places.nearby(*CNX, radius_km=10, kinds=("mall",))
    assert found == [{"name": "เซ็นทรัล", "detail": None, "lat": 18.79, "lng": 98.99, "kind_th": "ห้างสรรพสินค้า"}]


def test_unknown_kind_or_radius_is_validation_error():
    for kwargs in ({"kinds": ("casino",)}, {"radius_km": 50}):
        with pytest.raises(ApiError) as e:
            places.nearby(*CNX, **kwargs)
        assert e.value.code == "VALIDATION_ERROR"


def test_overpass_timeout_remark_is_not_cached_as_empty(monkeypatch):
    class Res:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"elements": [], "remark": 'runtime error: Query timed out in "query" at line 1 after 40 seconds.'}
    monkeypatch.setattr("places.httpx.post", lambda *a, **k: Res())
    with pytest.raises(ApiError) as e:
        places.fetch_nearby(*CNX)
    assert e.value.code == "UPSTREAM_TIMEOUT"


# ---------- Overpass ล่ม ใช้ Photon ค้นตามหมวดแทน ----------

def photon_feature(name, value, lat=18.791, lng=98.981):
    return {"geometry": {"coordinates": [lng, lat]},
            "properties": {"name": name, "osm_value": value, "city": "เมืองเชียงใหม่", "state": "จังหวัดเชียงใหม่"}}


def test_overpass_down_falls_back_to_photon_and_skips_overpass_for_a_while(overpass, monkeypatch):
    sent = overpass(error=httpx.ConnectError("504"))
    asked = []

    def fake_get(url, params=None, headers=None, timeout=None):
        asked.append(params["q"])
        hits = {"coffee": [photon_feature("Ristr8to", "cafe")], "กาแฟ": [photon_feature("Ristr8to", "cafe"), photon_feature("กาแฟดอย", "cafe")]}
        return httpx.Response(200, json={"features": hits.get(params["q"], [])}, request=httpx.Request("GET", url))

    monkeypatch.setattr("places.httpx.get", fake_get)
    found = places.nearby(*CNX, radius_km=10, kinds=("cafe",))
    assert [p["name"] for p in found] == ["Ristr8to", "กาแฟดอย"]  # ชื่อซ้ำจากหลายคำค้นเหลืออันเดียว
    assert found[0]["kind_th"] == "คาเฟ่" and found[0]["detail"] == "เมืองเชียงใหม่, จังหวัดเชียงใหม่"
    assert sorted(asked) == sorted(q for q, _ in places.PHOTON_KIND_QUERY["cafe"])
    places._nearby_cache.clear()
    places.nearby(*CNX, radius_km=10, kinds=("market",))
    assert len(sent) == 1  # Overpass เพิ่งล่ม คำขอถัดไปไม่ยิงซ้ำ ไปใช้ Photon เลย


def test_both_down_keeps_the_overpass_error(overpass):
    overpass(error=httpx.ConnectError("504"))
    with pytest.raises(ApiError) as e:
        places.nearby(*CNX)
    assert e.value.code == "UPSTREAM_ERROR"


def test_wide_radius_spreads_out_instead_of_only_the_nearest(overpass):
    # 30 ที่กองอยู่ใกล้ตัวไม่เกิน 2 กม. + 5 ที่อยู่ไกล 10-18 กม. ต้องได้ที่ไกลมาด้วย
    near = [node(f"ใกล้ {i}", 18.79 + i * 0.0005, 98.98, tourism="museum") for i in range(30)]
    far = [node(f"ไกล {i}", 18.79 + 0.09 + i * 0.015, 98.98, tourism="viewpoint") for i in range(5)]
    overpass(near + far)
    found = places.nearby(*CNX, radius_km=20)
    assert len(found) == 20
    assert sum(p["name"].startswith("ไกล") for p in found) == 5
    dist = [haversine_km({"lat": CNX[0], "lng": CNX[1]}, p) for p in found]
    assert dist == sorted(dist)
