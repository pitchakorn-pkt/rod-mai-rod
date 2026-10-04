"""Disaster pins from GDACS (floods, storms) and USGS (earthquakes)."""
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from geo import THAILAND_BOUNDS, to_iso
import doh
import gistda
import landslide
import weather_pins
from weather import demo_mode

logger = logging.getLogger("weather-disaster")

# ";" must stay literal, so the query is part of the URL
GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH?eventlist=FL;TC"
USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
TIMEOUT_S = 8
EQ_MIN_MAG = 4.0
EQ_MARGIN_DEG = 2.0  # quakes just across the border are still felt in Thailand
EQ_DAYS = 7
FIXTURES = Path(__file__).resolve().parent / "fixtures"
CACHE_TTL_S = 10 * 60

GDACS_TYPES = {"FL": ("FLOOD", "น้ำท่วม"), "TC": ("STORM", "พายุหมุนเขตร้อน")}
GDACS_SEVERITY = {"Green": "LOW", "Orange": "MEDIUM", "Red": "HIGH"}
LEVEL_TH = {"LOW": "เฝ้าติดตาม", "MEDIUM": "เฝ้าระวัง", "HIGH": "รุนแรง"}

Box = tuple[float, float, float, float]  # min_lat, min_lng, max_lat, max_lng


def in_box(lat: float, lng: float, box: Box) -> bool:
    return box[0] <= lat <= box[2] and box[1] <= lng <= box[3]


def widen(box: Box, deg: float) -> Box:
    return (box[0] - deg, box[1] - deg, box[2] + deg, box[3] + deg)


def gdacs_time(value) -> str | None:
    """GDACS times have no zone but are UTC."""
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return to_iso(dt)


def ms_time(value) -> str | None:
    if value is None:
        return None
    return to_iso(datetime.fromtimestamp(value / 1000, tz=timezone.utc))


def quake_severity(mag: float) -> str:
    if mag >= 6.0:
        return "HIGH"
    if mag >= 5.0:
        return "MEDIUM"
    return "LOW"


def parse_gdacs(feature: dict, box: Box) -> dict | None:
    p = feature.get("properties") or {}
    geom = feature.get("geometry") or {}
    kind = GDACS_TYPES.get(p.get("eventtype"))
    severity = GDACS_SEVERITY.get(p.get("alertlevel"))
    if not kind or not severity or geom.get("type") != "Point":
        return None
    if str(p.get("iscurrent")).lower() != "true":
        return None
    lng, lat = float(geom["coordinates"][0]), float(geom["coordinates"][1])
    if not (in_box(lat, lng, THAILAND_BOUNDS) and in_box(lat, lng, box)):
        return None
    hazard_type, name_th = kind
    return {
        "hazard_id": f"gdacs-{p.get('eventtype')}-{p.get('eventid')}",
        "hazard_type": hazard_type,
        "severity": severity,
        "lat": lat,
        "lng": lng,
        "province": None,
        "title_th": f"{name_th} ระดับ{LEVEL_TH[severity]}",
        "source": "GDACS",
        "updated_at": gdacs_time(p.get("datemodified") or p.get("fromdate")),
    }


def parse_usgs(feature: dict, box: Box) -> dict | None:
    p = feature.get("properties") or {}
    mag = p.get("mag")
    if mag is None or mag < EQ_MIN_MAG:
        return None
    lng, lat = float(feature["geometry"]["coordinates"][0]), float(feature["geometry"]["coordinates"][1])
    if not in_box(lat, lng, box):
        return None
    return {
        "hazard_id": f"usgs-{feature.get('id')}",
        "hazard_type": "EARTHQUAKE",
        "severity": quake_severity(mag),
        "lat": lat,
        "lng": lng,
        "province": None,
        "title_th": f"แผ่นดินไหวขนาด {mag:.1f}",
        "source": "USGS",
        "updated_at": ms_time(p.get("updated") or p.get("time")),
    }


def parse_all(features, box: Box, parser) -> list[dict]:
    """A single malformed feature is skipped, not the whole feed."""
    out, seen = [], set()
    for f in features or []:
        try:
            h = parser(f, box)
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if h and h["hazard_id"] not in seen:
            seen.add(h["hazard_id"])
            out.append(h)
    return out


def fetch_gdacs(box: Box) -> list[dict]:
    res = httpx.get(GDACS_URL, timeout=TIMEOUT_S)
    res.raise_for_status()
    return parse_all(res.json().get("features"), box, parse_gdacs)


def usgs_params() -> dict:
    area = widen(THAILAND_BOUNDS, EQ_MARGIN_DEG)
    start = datetime.now(timezone.utc) - timedelta(days=EQ_DAYS)
    return {
        "format": "geojson",
        "minmagnitude": EQ_MIN_MAG,
        "minlatitude": area[0],
        "minlongitude": area[1],
        "maxlatitude": area[2],
        "maxlongitude": area[3],
        "starttime": start.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def fetch_usgs(box: Box) -> list[dict]:
    res = httpx.get(USGS_URL, params=usgs_params(), timeout=TIMEOUT_S)
    res.raise_for_status()
    return parse_all(res.json().get("features"), box, parse_usgs)


def read_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def demo_gdacs(box: Box) -> list[dict]:
    return parse_all(read_fixture("gdacs.json").get("features"), box, parse_gdacs)


def demo_usgs(box: Box) -> list[dict]:
    return parse_all(read_fixture("usgs.json").get("features"), box, parse_usgs)


def derived_landslide(box: Box) -> list[dict]:
    return landslide.landslide_hazards(box)


def current_weather(box: Box) -> list[dict]:
    return weather_pins.weather_hazards(box)


# every source is fetched once for the whole area, then filtered per request,
# so moving the map does not refetch; each source is cached on its own
ALL_BOX = widen(THAILAND_BOUNDS, EQ_MARGIN_DEG)
_cache: dict[tuple, tuple[float, list]] = {}
_lock = threading.Lock()
_now = time.monotonic


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _cached(key, now: float) -> list | None:
    with _lock:
        item = _cache.get(key)
    if item and now - item[0] < CACHE_TTL_S:
        return item[1]
    return None


def get_hazards(box: Box, refresh: bool = False) -> tuple[list[dict], list[str]]:
    """All sources in parallel. A failed source becomes a warning, is not cached, the rest still return."""
    demo = demo_mode()
    if demo:
        sources = (("gdacs", demo_gdacs), ("usgs", demo_usgs),
                   ("landslide", derived_landslide), ("weather", current_weather))
    else:
        sources = (("gdacs", fetch_gdacs), ("usgs", fetch_usgs),
                   ("landslide", derived_landslide), ("weather", current_weather))
    now = _now()
    found: dict[str, list] = {}
    todo = []
    for name, fn in sources:
        hit = None if refresh else _cached((demo, name), now)
        if hit is None:
            todo.append((name, fn))
        else:
            found[name] = hit

    warnings: list[str] = []
    if todo:
        with ThreadPoolExecutor(max_workers=len(todo)) as pool:
            futures = [(name, pool.submit(fn, ALL_BOX)) for name, fn in todo]
            for name, fut in futures:
                try:
                    result = fut.result()
                except Exception:
                    logger.warning("hazard source failed: %s", name, exc_info=True)
                    if "HAZARD_FEED_UNAVAILABLE" not in warnings:
                        warnings.append("HAZARD_FEED_UNAVAILABLE")
                    continue
                with _lock:
                    _cache[(demo, name)] = (now, result)
                found[name] = result

    hazards = [h for name, _ in sources for h in found.get(name, []) if in_box(h["lat"], h["lng"], box)]
    # GISTDA flood extent, refreshed only in the background, never fetched here
    if not demo and gistda.enabled():
        hazards += [h for h in gistda.latest() if in_box(h["lat"], h["lng"], box)]
    # น้ำท่วม/ปิดถนนบนทางหลวง (กรมทางหลวง) โหลดเบื้องหลังเหมือนกัน
    if not demo and doh.enabled():
        hazards += [h for h in doh.latest() if in_box(h["lat"], h["lng"], box)]
    return hazards, warnings


REFRESH_EVERY_S = CACHE_TTL_S - 60  # renew before expiry so real requests always hit the cache


def keep_warm() -> None:
    """Runs in a background thread from startup. The first GDACS/USGS fetch from Thailand can take
    longer than the 10 s risk-decision waits, so fetch every source before anyone asks."""
    while True:
        try:
            get_hazards(ALL_BOX, refresh=True)
        except Exception:
            logger.warning("hazard warm-up failed", exc_info=True)
        time.sleep(REFRESH_EVERY_S)
