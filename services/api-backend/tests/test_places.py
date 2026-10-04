import httpx
import pytest

import places
from envelope import ApiError


def feature(name, lng, lat, country="TH", **props):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": {"name": name, "countrycode": country, **props}}


@pytest.fixture(autouse=True)
def empty_cache(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    places._cache.clear()


@pytest.fixture
def photon(monkeypatch):
    """แทน Photon จริง เทสต์ไม่ยิงเน็ต คืน list ของคำขอที่ถูกส่งไปให้ตรวจ"""
    sent = []

    def use(features=(), error=None):
        def fake_get(url, params=None, headers=None, timeout=None):
            sent.append({"params": params, "headers": headers, "timeout": timeout})
            if error is not None:
                raise error
            return httpx.Response(200, json={"features": list(features)}, request=httpx.Request("GET", url))

        monkeypatch.setattr("places.httpx.get", fake_get)
        return sent

    return use


def test_keeps_at_most_5_results_inside_thailand(photon):
    sent = photon([feature("เวียงจันทน์", 102.6, 17.97, country="LA")]
                  + [feature(f"ที่ {i}", 100.5, 13.7 + i / 100) for i in range(7)])
    found = places.search("ที่")
    assert len(found) == 5
    assert all(p["name"].startswith("ที่ ") for p in found)
    assert sent[0]["params"]["limit"] == 8
    assert sent[0]["params"]["bbox"] == "97.3,5.6,105.7,20.5"
    assert sent[0]["timeout"] == 5
    assert "rod-mai-rod" in sent[0]["headers"]["User-Agent"]


def test_expands_thai_abbreviations(photon):
    sent = photon()
    for q, expected in (("กทม", "กรุงเทพมหานคร"), ("กทม.", "กรุงเทพมหานคร"), ("กรุงเทพฯ", "กรุงเทพมหานคร"),
                        ("โคราช", "นครราชสีมา"), ("อยุธยา", "พระนครศรีอยุธยา"),
                        ("สยาม กทม", "สยาม กรุงเทพมหานคร"), ("เซ็นทรัลโคราช", "เซ็นทรัลโคราช"),
                        ("ชม.", "เชียงใหม่"), ("เขาใหญ่", "อุทยานแห่งชาติเขาใหญ่"), ("น้ำตกเขาใหญ่", "น้ำตกเขาใหญ่"),
                        ("มทร", "มหาวิทยาลัยเทคโนโลยีราชมงคล"),
                        ("มทร.ธัญบุรี", "มหาวิทยาลัยเทคโนโลยีราชมงคลธัญบุรี"),
                        ("มทร ธัญบุรี", "มหาวิทยาลัยเทคโนโลยีราชมงคล ธัญบุรี"),
                        ("ราชมงคลธัญบุรี", "มหาวิทยาลัยเทคโนโลยีราชมงคลธัญบุรี"),
                        ("มก.", "มหาวิทยาลัยเกษตรศาสตร์"), ("รพ.ศิริราช", "โรงพยาบาลศิริราช"),
                        ("มกราคม", "มกราคม")):
        places._cache.clear()
        places.search(q)
        assert sent[-1]["params"]["q"] == expected


def test_place_shape_and_detail(photon):
    photon([feature("ดอยสุเทพ", 98.89, 18.80, county="อำเภอเมืองเชียงใหม่", state="เชียงใหม่"),
            feature("ที่ไม่มีอำเภอ", 100.5, 13.7)])
    found = places.search("ดอย")
    assert list(found[0]) == ["name", "detail", "lat", "lng"]
    assert found[0] == {"name": "ดอยสุเทพ", "detail": "อำเภอเมืองเชียงใหม่, เชียงใหม่", "lat": 18.80, "lng": 98.89}
    assert found[1]["detail"] is None


def test_same_query_is_cached_for_10_minutes(photon, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("places.monotonic", lambda: now[0])
    sent = photon([feature("เชียงใหม่", 98.98, 18.79)])
    places.search("เชียงใหม่")
    places.search("เชียงใหม่")
    assert len(sent) == 1
    now[0] += 601
    places.search("เชียงใหม่")
    assert len(sent) == 2


def test_short_query_is_validation_error_without_calling_photon(photon):
    sent = photon()
    with pytest.raises(ApiError) as e:
        places.search(" ก ")
    assert e.value.code == "VALIDATION_ERROR"
    assert sent == []


def test_photon_down_is_upstream_error(photon):
    photon(error=httpx.ConnectError("down"))
    with pytest.raises(ApiError) as e:
        places.search("เชียงใหม่")
    assert e.value.code == "UPSTREAM_ERROR"


def test_photon_slow_is_upstream_timeout(photon):
    photon(error=httpx.ReadTimeout("slow"))
    with pytest.raises(ApiError) as e:
        places.search("เชียงใหม่")
    assert e.value.code == "UPSTREAM_TIMEOUT"


def test_endpoint_needs_login_and_wraps_result(client, auth_header, photon):
    photon([feature("เชียงใหม่", 98.98, 18.79, state="เชียงใหม่")])
    url = "/api/v1/places/search"
    assert client.get(url, params={"q": "เชียงใหม่"}).status_code == 401
    res = client.get(url, params={"q": "เชียงใหม่"}, headers=auth_header)
    assert res.status_code == 200
    assert res.json() == {"data": {"places": [{"name": "เชียงใหม่", "detail": "เชียงใหม่", "lat": 18.79, "lng": 98.98}]},
                          "error": None}
    assert client.get(url, params={"q": "ก"}, headers=auth_header).status_code == 400