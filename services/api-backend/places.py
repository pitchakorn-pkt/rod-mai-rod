"""สถานที่ในไทย (CONTRACT หัวข้อ 6): ค้นจากชื่อผ่าน Photon และที่เที่ยวใกล้ตัวผ่าน Overpass

DEMO_MODE=true อ่านคำตอบที่บันทึกไว้ใน fixtures/ ไม่เรียกเน็ตเลย (บันทึกด้วย record_fixtures.py)
"""
import json
import math
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from time import monotonic
from typing import Optional

import httpx

from envelope import ApiError
from geo import THAILAND_BOUNDS, haversine_km, in_thailand

PHOTON_URL = "https://photon.komoot.io/api/"
PHOTON_TIMEOUT = 5  # วินาที ตาม CONTRACT หัวข้อ 3
USER_AGENT = "rod-mai-rod/1.0 (university course project)"
ASK = 8  # ขอเกินไว้ เพราะ bbox คลุมประเทศเพื่อนบ้านด้วย ต้องคัดทิ้ง
LIMIT = 5
MIN_CHARS = 2
CACHE_SECONDS = 600

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SEARCH_FIXTURE = FIXTURES / "places_search.json"
NEARBY_FIXTURE = FIXTURES / "places_nearby.json"
DEMO_MATCH_KM = 15  # เท่ากับของ routing-engine บนเวทีตำแหน่งไม่ตรงกับตอนบันทึก

_min_lat, _min_lng, _max_lat, _max_lng = THAILAND_BOUNDS
BBOX = f"{_min_lng},{_min_lat},{_max_lng},{_max_lat}"  # Photon ใช้ลำดับ lng,lat

# คำย่อที่คนไทยพิมพ์บ่อย แปลงทีละคำ (คั่นด้วยช่องว่าง) ไม่แทนกลางคำ
ABBREVIATIONS = {
    "กทม": "กรุงเทพมหานคร",
    "กรุงเทพ": "กรุงเทพมหานคร",
    "กรุงเทพฯ": "กรุงเทพมหานคร",
    "บางกอก": "กรุงเทพมหานคร",
    "โคราช": "นครราชสีมา",
    "อยุธยา": "พระนครศรีอยุธยา",
    "แปดริ้ว": "ฉะเชิงเทรา",
    "นครศรี": "นครศรีธรรมราช",
    "นครศรีฯ": "นครศรีธรรมราช",
    "สุราษฎร์": "สุราษฎร์ธานี",
    "สุราษฎร์ฯ": "สุราษฎร์ธานี",
    "อุบล": "อุบลราชธานี",
    "อุดร": "อุดรธานี",
    "ประจวบ": "ประจวบคีรีขันธ์",
    "สุพรรณ": "สุพรรณบุรี",
    "กาญ": "กาญจนบุรี",
    "ชม": "เชียงใหม่",
    "ชร": "เชียงราย",
    # "เขาใหญ่" เฉยๆ Photon ให้เขาใหญ่ที่สังขละบุรี/หัวหินก่อน คนส่วนใหญ่หมายถึงอุทยาน
    "เขาใหญ่": "อุทยานแห่งชาติเขาใหญ่",
    # มหาวิทยาลัยและโรงพยาบาล (Photon รู้จักแต่ชื่อเต็ม)
    "มทร": "มหาวิทยาลัยเทคโนโลยีราชมงคล",
    "ราชมงคล": "มหาวิทยาลัยเทคโนโลยีราชมงคล",
    "มก": "มหาวิทยาลัยเกษตรศาสตร์",
    "รพ": "โรงพยาบาล",
}
# คำที่มักพิมพ์ติดกับชื่อถัดไป เช่น "ราชมงคลธัญบุรี" (คำอื่นต้องมีจุดคั่น เช่น "มทร.ธัญบุรี")
PREFIX_WORDS = ("ราชมงคล",)

_cache: dict[str, tuple[float, list[dict]]] = {}


def demo_mode() -> bool:
    return os.getenv("DEMO_MODE", "false").lower() == "true"


def _fixture(path: Path, section: str) -> dict:
    """คำตอบที่บันทึกไว้ ไม่มีไฟล์ถือว่าว่าง"""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get(section, {})


def _expand_word(word: str) -> str:
    if word.rstrip(".") in ABBREVIATIONS:
        return ABBREVIATIONS[word.rstrip(".")]
    for short, full in ABBREVIATIONS.items():
        if word.startswith(short + ".") and len(word) > len(short) + 1:
            return full + word[len(short) + 1:]
    for short in PREFIX_WORDS:
        if word.startswith(short) and len(word) > len(short):
            return ABBREVIATIONS[short] + word[len(short):]
    return word


def expand(q: str) -> str:
    return " ".join(_expand_word(word) for word in q.split())


def _detail(p: dict) -> Optional[str]:
    """อำเภอ, จังหวัด เท่าที่มี"""
    parts = []
    for value in (p.get("county") or p.get("city"), p.get("state")):
        if value and value not in parts:
            parts.append(value)
    return ", ".join(parts) or None


def _to_place(feature: dict) -> Optional[dict]:
    p = feature.get("properties") or {}
    lng, lat = feature["geometry"]["coordinates"]  # GeoJSON ส่ง [lng, lat] ต้องสลับ (CONTRACT หัวข้อ 4)
    if p.get("countrycode") != "TH" or not p.get("name") or not in_thailand(lat, lng):
        return None
    return {"name": p["name"], "detail": _detail(p), "lat": lat, "lng": lng}


def fetch_search(query: str) -> list[dict]:
    """ยิง Photon จริง คืนไม่เกิน LIMIT ตัวที่อยู่ในไทย"""
    try:
        res = httpx.get(PHOTON_URL, params={"q": query, "limit": ASK, "bbox": BBOX},
                        headers={"User-Agent": USER_AGENT}, timeout=PHOTON_TIMEOUT)
        res.raise_for_status()
        features = res.json().get("features", [])
    except httpx.TimeoutException:
        raise ApiError("UPSTREAM_TIMEOUT", "ค้นหาสถานที่ไม่ทันเวลา ลองใหม่หรือปักหมุดบนแผนที่แทน")
    except (httpx.HTTPError, ValueError):
        raise ApiError("UPSTREAM_ERROR", "ค้นหาสถานที่ไม่ได้ตอนนี้ ลองใหม่หรือปักหมุดบนแผนที่แทน")

    found, seen = [], set()
    for feature in features:
        place = _to_place(feature)
        # Photon มักส่งที่เดียวกันซ้ำ (จุดกับขอบเขต) ตัดด้วยชื่อ + รายละเอียด
        if place and (place["name"], place["detail"]) not in seen:
            seen.add((place["name"], place["detail"]))
            found.append(place)
        if len(found) == LIMIT:
            break
    return found


def search(q: str) -> list[dict]:
    q = q.strip()
    if len(q) < MIN_CHARS:
        raise ApiError("VALIDATION_ERROR", f"พิมพ์ชื่อสถานที่อย่างน้อย {MIN_CHARS} ตัวอักษร")
    query = expand(q)
    key = query.lower()
    if demo_mode():
        # คำที่ไม่ได้บันทึกไว้ตอบว่างเหมือนค้นไม่เจอ ไม่ใช่ error
        return _fixture(SEARCH_FIXTURE, "queries").get(key, [])
    hit = _cache.get(key)
    if hit and hit[0] > monotonic():
        return hit[1]
    found = fetch_search(query)
    if len(_cache) > 1000:
        _cache.clear()
    _cache[key] = (monotonic() + CACHE_SECONDS, found)
    return found


# ---------- สถานที่เที่ยวใกล้ตัว (GET /places/nearby) ----------

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT = 8  # วินาทีที่คำขอรอ ตาม CONTRACT หัวข้อ 3
OVERPASS_DOWNLOAD_TIMEOUT = 30  # ไม่ทัน OVERPASS_TIMEOUT ยังโหลดต่อเบื้องหลังจนเสร็จแล้วเก็บลง cache
NEARBY_RADIUS_KM = 5
NEARBY_LIMIT = 8
NEARBY_CACHE_SECONDS = 24 * 60 * 60

NEARBY_MAX_RADIUS_KM = 20
NEARBY_LIMIT_WIDE = 20  # ขอหมวดอื่นหรือรัศมีกว้าง (แชทแนะนำที่เที่ยวตามแนว)
NEARBY_RINGS = 4  # รัศมีกว้าง: เลือกกระจายจากวงใกล้ถึงวงไกล ไม่เอาแต่ที่กระจุกใกล้สุด

# หมวดสถานที่ที่ขอได้ ค่าเริ่มต้น attraction = ที่เที่ยวตาม CONTRACT หัวข้อ 6 (เหมือนเดิม)
# nwr = node / way / relation (ห้าง ตลาด สวน มักวาดเป็นพื้นที่) ใช้ out center ได้จุดกลาง
KIND_QUERY = {
    "attraction": ['node{a}["name"]["tourism"~"^(attraction|viewpoint|museum|zoo|theme_park)$"]',
                   'node{a}["name"]["historic"~"^(monument|temple|ruins)$"]'],
    "cafe": ['node{a}["name"]["amenity"="cafe"]'],
    "market": ['nwr{a}["name"]["amenity"="marketplace"]'],
    "park": ['nwr{a}["name"]["leisure"="park"]'],
    "mall": ['nwr{a}["name"]["shop"~"^(mall|department_store)$"]'],
    "nightlife": ['node{a}["name"]["amenity"~"^(bar|pub|nightclub)$"]'],
    "waterfall": ['nwr{a}["name"]["waterway"="waterfall"]', 'nwr{a}["name"]["natural"="waterfall"]'],
}
DEFAULT_KINDS = ("attraction",)

KIND_TH = {
    "attraction": "สถานที่ท่องเที่ยว",
    "viewpoint": "จุดชมวิว",
    "museum": "พิพิธภัณฑ์",
    "zoo": "สวนสัตว์",
    "theme_park": "สวนสนุก",
    "monument": "อนุสาวรีย์",
    "temple": "วัด",
    "ruins": "โบราณสถาน",
    "cafe": "คาเฟ่",
    "marketplace": "ตลาด",
    "park": "สวนสาธารณะ",
    "mall": "ห้างสรรพสินค้า",
    "department_store": "ห้างสรรพสินค้า",
    "bar": "บาร์",
    "pub": "ผับ",
    "nightclub": "ผับ",
    "waterfall": "น้ำตก",
}

_nearby_cache: dict[tuple[float, float], tuple[float, list[dict]]] = {}
# ช่องที่กำลังโหลดอยู่ คำขอช่องเดียวกันรองานเดิม ไม่ยิงซ้ำ (แบบ _pending ของ routing-engine)
_nearby_pending: dict[tuple[float, float], Future] = {}
_pending_lock = threading.Lock()  # ถือแค่ตอนเช็คและสั่งโหลด ไม่ได้ถือตลอดการโหลด
_nearby_pool = ThreadPoolExecutor(max_workers=2)  # Overpass ให้แต่ละ IP ยิงพร้อมกันได้ไม่กี่คำขอ


def _addr_detail(tags: dict) -> Optional[str]:
    """อำเภอ, จังหวัด จากแท็ก addr:* เท่าที่มี"""
    parts = []
    for value in (tags.get("addr:district") or tags.get("addr:city"), tags.get("addr:province")):
        if value and value not in parts:
            parts.append(value)
    return ", ".join(parts) or None


def _to_nearby(element: dict) -> Optional[dict]:
    tags = element.get("tags") or {}
    name = tags.get("name:th") or tags.get("name")
    kind = next((KIND_TH[tags[k]] for k in ("tourism", "historic", "amenity", "leisure", "shop", "waterway", "natural") if tags.get(k) in KIND_TH), None)
    point = element if "lat" in element else element.get("center")  # way/relation ได้จุดกลางจาก out center
    if not name or not kind or not point:
        return None
    # Overpass ใช้ชื่อ lon ของเราใช้ lng (CONTRACT หัวข้อ 4)
    return {"name": name, "detail": _addr_detail(tags), "lat": point["lat"], "lng": point["lon"], "kind_th": kind}


def fetch_nearby(lat: float, lng: float, timeout: float = OVERPASS_DOWNLOAD_TIMEOUT,
                 radius_km: float = NEARBY_RADIUS_KM, kinds: tuple = DEFAULT_KINDS) -> list[dict]:
    """ยิง Overpass จริง คืนสถานที่ทุกตัวในรัศมี ยังไม่เรียงและไม่ตัดจำนวน"""
    # ใช้กรอบสี่เหลี่ยมแทนวงกลม (around) Overpass ตอบใน ~1 วิ ส่วน around ตอนเซิร์ฟเวอร์ยุ่งหมดเวลา 40 วิ
    # ตัดตามรัศมีจริงทีหลังใน nearby()
    d_lat = radius_km / 111
    d_lng = radius_km / (111 * max(0.2, math.cos(math.radians(lat))))
    area, head = "", f"[bbox:{lat - d_lat:.4f},{lng - d_lng:.4f},{lat + d_lat:.4f},{lng + d_lng:.4f}]"
    parts = "".join(q.format(a=area) + ";" for k in kinds for q in KIND_QUERY[k])
    query = f"[out:json][timeout:{timeout}]{head};({parts});out center 400;"
    try:
        res = httpx.post(OVERPASS_URL, data={"data": query},
                         headers={"User-Agent": USER_AGENT}, timeout=timeout)
        res.raise_for_status()
        body = res.json()
        # Overpass หมดเวลาฝั่งเขายังตอบ 200 แต่ elements ว่าง + remark ห้ามเก็บลง cache ว่าไม่มีที่เที่ยว
        if "error" in str(body.get("remark", "")).lower() or "timed out" in str(body.get("remark", "")):
            raise httpx.ReadTimeout(body["remark"])
        elements = body.get("elements", [])
    except httpx.TimeoutException:
        raise ApiError("UPSTREAM_TIMEOUT", "ดึงสถานที่เที่ยวใกล้ๆ ไม่ทันเวลา ลองใหม่อีกครั้ง")
    except (httpx.HTTPError, ValueError):
        raise ApiError("UPSTREAM_ERROR", "ดึงสถานที่เที่ยวใกล้ๆ ไม่ได้ตอนนี้ ลองใหม่อีกครั้ง")
    return [p for p in map(_to_nearby, elements) if p]


# Overpass สาธารณะล่มบ่อย (504) ใช้ Photon ค้นตามหมวดแทน ข้อมูล OSM ชุดเดียวกันแต่ได้น้อยกว่า
# Photon ต้องมีคำค้น เลยค้นหลายคำต่อหมวด แล้วกรองด้วย osm_tag ให้ได้เฉพาะประเภทนั้น
PHOTON_KIND_QUERY = {
    "attraction": [("วัด", "amenity:place_of_worship"), ("wat", "amenity:place_of_worship"), ("museum", "tourism:museum"),
                   ("พิพิธภัณฑ์", "tourism:museum"), ("viewpoint", "tourism:viewpoint"), ("จุดชมวิว", "tourism:viewpoint")],
    "cafe": [("coffee", "amenity:cafe"), ("กาแฟ", "amenity:cafe"), ("cafe", "amenity:cafe")],
    "market": [("ตลาด", "amenity:marketplace"), ("market", "amenity:marketplace")],
    "park": [("สวน", "leisure:park"), ("park", "leisure:park")],
    "mall": [("mall", "shop:mall"), ("plaza", "shop:mall"), ("central", "shop:mall")],
    "nightlife": [("bar", "amenity:bar"), ("pub", "amenity:pub"), ("ผับ", "amenity:nightclub")],
    "waterfall": [("น้ำตก", "waterway:waterfall"), ("waterfall", "waterway:waterfall"), ("น้ำตก", "natural:waterfall")],
}
PHOTON_KIND_TH = {**KIND_TH, "place_of_worship": "วัด"}
PHOTON_NEARBY_TIMEOUT = 8
OVERPASS_DOWN_SECONDS = 5 * 60  # Overpass พังแล้วข้ามไปใช้ Photon เลยช่วงนี้ ไม่ต้องรอ 504 ทุกคำขอ
NEARBY_FALLBACK_CACHE_SECONDS = 60 * 60  # ผลจาก Photon เก็บสั้นกว่า Overpass กลับมาจะได้ข้อมูลเต็ม
_overpass_down_until = 0.0


def fetch_nearby_photon(lat: float, lng: float, radius_km: float = NEARBY_RADIUS_KM, kinds: tuple = DEFAULT_KINDS) -> list[dict]:
    d_lat = radius_km / 111
    d_lng = radius_km / (111 * max(0.2, math.cos(math.radians(lat))))
    bbox = f"{lng - d_lng:.4f},{lat - d_lat:.4f},{lng + d_lng:.4f},{lat + d_lat:.4f}"

    def one(q_tag):
        q, tag = q_tag
        res = httpx.get(PHOTON_URL, params={"q": q, "osm_tag": tag, "bbox": bbox, "limit": 15, "lat": lat, "lon": lng},
                        headers={"User-Agent": USER_AGENT}, timeout=PHOTON_NEARBY_TIMEOUT)
        res.raise_for_status()
        return res.json().get("features", [])

    jobs = [qt for k in kinds for qt in PHOTON_KIND_QUERY[k]]
    found, seen, failed = [], set(), 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for job in [pool.submit(one, qt) for qt in jobs]:
            try:
                features = job.result()
            except (httpx.HTTPError, ValueError):
                failed += 1
                continue
            for f in features:
                prop = f.get("properties") or {}
                name, kind = prop.get("name"), PHOTON_KIND_TH.get(prop.get("osm_value"))
                if not name or not kind or name in seen:
                    continue
                seen.add(name)
                lng_, lat_ = f["geometry"]["coordinates"]
                detail = ", ".join(v for v in (prop.get("district") or prop.get("city"), prop.get("state")) if v) or None
                found.append({"name": name, "detail": detail, "lat": lat_, "lng": lng_, "kind_th": kind})
    if failed == len(jobs):
        raise ApiError("UPSTREAM_ERROR", "ดึงสถานที่เที่ยวใกล้ๆ ไม่ได้ตอนนี้ ลองใหม่อีกครั้ง")
    return found


def _download(cell: tuple) -> list[dict]:
    """รันเบื้องหลัง เก็บลง cache เฉพาะที่สำเร็จ แล้วเอาช่องออกจากรายการที่กำลังโหลด
    cell = (lat, lng) แบบเดิม หรือ (lat, lng, radius_km, kinds) ตอนขอหมวดอื่น"""
    global _overpass_down_until
    radius, kinds = (NEARBY_RADIUS_KM, DEFAULT_KINDS) if len(cell) == 2 else cell[2:]
    try:
        ttl = NEARBY_CACHE_SECONDS
        try:
            if monotonic() < _overpass_down_until:
                raise ApiError("UPSTREAM_ERROR", "Overpass ล่มเมื่อสักครู่ ใช้ Photon ไปก่อน")
            candidates = fetch_nearby(*cell[:2]) if len(cell) == 2 else fetch_nearby(cell[0], cell[1], radius_km=radius, kinds=kinds)
        except ApiError as overpass_error:
            if overpass_error.code == "UPSTREAM_ERROR":  # ตอบ error จริง (504/429) ถ้าแค่ช้าคราวหน้ายังลอง Overpass
                _overpass_down_until = max(_overpass_down_until, monotonic() + OVERPASS_DOWN_SECONDS)
            try:
                candidates, ttl = fetch_nearby_photon(cell[0], cell[1], radius, kinds), NEARBY_FALLBACK_CACHE_SECONDS
            except ApiError:
                raise overpass_error
        if len(_nearby_cache) > 1000:
            _nearby_cache.clear()
        _nearby_cache[cell] = (monotonic() + ttl, candidates)
        return candidates
    finally:
        with _pending_lock:
            _nearby_pending.pop(cell, None)


def _cached_candidates(cell: tuple) -> list[dict]:
    """รอไม่เกิน OVERPASS_TIMEOUT ไม่ทันตอบ UPSTREAM_TIMEOUT แต่ให้โหลดต่อ คำขอถัดไปจะได้จาก cache"""
    with _pending_lock:
        hit = _nearby_cache.get(cell)
        if hit and hit[0] > monotonic():
            return hit[1]
        job = _nearby_pending.get(cell)
        if job is None:
            job = _nearby_pending[cell] = _nearby_pool.submit(_download, cell)
    try:
        return job.result(timeout=OVERPASS_TIMEOUT)
    except FutureTimeout:
        raise ApiError("UPSTREAM_TIMEOUT", "สถานที่เที่ยวใกล้ๆ ยังโหลดไม่เสร็จ กำลังโหลดต่อให้ ลองใหม่ในอีกสักครู่")


def _demo_cell(lat: float, lng: float) -> tuple[dict, list[dict]]:
    """ช่องที่บันทึกไว้ที่ใกล้ที่สุดไม่เกิน DEMO_MATCH_KM คืน (จุดกลางช่อง, ที่เที่ยว) ไม่มีเลยคืน (จุดที่ขอ, [])"""
    here = {"lat": lat, "lng": lng}
    best_center, best_places, best_km = here, [], None
    for key, candidates in _fixture(NEARBY_FIXTURE, "cells").items():
        c_lat, c_lng = map(float, key.split("_"))
        center = {"lat": c_lat, "lng": c_lng}
        km = haversine_km(here, center)
        if km <= DEMO_MATCH_KM and (best_km is None or km < best_km):
            best_center, best_places, best_km = center, candidates, km
    return best_center, best_places


def nearby(lat: float, lng: float, radius_km: float = NEARBY_RADIUS_KM, kinds: tuple = DEFAULT_KINDS) -> list[dict]:
    if not in_thailand(lat, lng):
        raise ApiError("OUT_OF_THAILAND", "ตอนนี้รองรับเฉพาะสถานที่ในประเทศไทย")
    unknown = [k for k in kinds if k not in KIND_QUERY]
    if unknown or not kinds or not 1 <= radius_km <= NEARBY_MAX_RADIUS_KM:
        raise ApiError("VALIDATION_ERROR", f"หมวดใช้ได้ {', '.join(KIND_QUERY)} รัศมี 1-{NEARBY_MAX_RADIUS_KM} กม.")
    kinds = tuple(sorted(kinds))
    default = radius_km == NEARBY_RADIUS_KM and kinds == DEFAULT_KINDS
    limit = NEARBY_LIMIT if default else NEARBY_LIMIT_WIDE
    here = {"lat": lat, "lng": lng}
    if demo_mode():
        # บนเวทีอยู่คนละที่กับตอนบันทึก ใช้จุดกลางช่องที่บันทึกไว้ ไม่งั้นรัศมี 5 กม. ตัดทิ้งหมด
        here, candidates = _demo_cell(lat, lng)
    else:
        # ปัดทศนิยม 2 ตำแหน่ง (~1 กม.) คนที่อยู่ช่องเดียวกันใช้ข้อมูลชุดเดียว ประหยัดโควตา Overpass
        cell = (round(lat, 2), round(lng, 2))
        candidates = _cached_candidates(cell if default else (*cell, radius_km, kinds))

    # OpenStreetMap มักมีที่เดียวกันหลายจุด เก็บจุดที่ใกล้สุด
    inside, seen = [], set()
    for place in sorted(candidates, key=lambda p: haversine_km(here, p)):
        if haversine_km(here, place) > radius_km:
            break
        if place["name"] not in seen:
            seen.add(place["name"])
            inside.append(place)
    if default or len(inside) <= limit:
        return inside[:limit]
    # รัศมีกว้าง: แบ่งเป็นวงตามระยะ หยิบวงละที่ (ใกล้สุดของวงก่อน) วนจนครบ แล้วเรียงใกล้ไปไกลเหมือนเดิม
    rings = [[] for _ in range(NEARBY_RINGS)]
    for place in inside:
        rings[min(int(haversine_km(here, place) / radius_km * NEARBY_RINGS), NEARBY_RINGS - 1)].append(place)
    found = []
    while len(found) < limit:
        for ring in rings:
            if ring and len(found) < limit:
                found.append(ring.pop(0))
    found.sort(key=lambda p: haversine_km(here, p))
    return found