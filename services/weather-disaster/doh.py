"""Highway flood / landslide incidents from the Department of Highways (กรมทางหลวง) as hazards.

HDMS (hdms.doh.go.th, ศูนย์บริหารงานอุบัติภัย) lists incidents on highways with position, road km,
water depth and whether cars can pass. We fetch the public list in the background every 15 minutes
and keep the incidents that are still open. Requests never wait for HDMS.

Each hazard carries road_cells (the incident point) so risk-decision counts it only when the route
really drives through it, same as GISTDA flooded roads.

The endpoint is the HDMS web page's own API, not official open data: any failure keeps the last result.
"""
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx

from geo import in_thailand

logger = logging.getLogger("weather-disaster")

HDMS_URL = "https://hdms.doh.go.th/internal-api/public/dashboard"
USER_AGENT = "rod-mai-rod/1.0 (university course project)"
LOOKBACK_DAYS = 60  # เหตุที่ยังไม่จบอาจเริ่มนานแล้ว (ตอนนี้เก่าสุด 18 ก.ย.)
TIMEOUT_S = 30  # background only, never in a user request
REFRESH_S = 15 * 60

# เกณฑ์เดียวกับหน้าเว็บ HDMS: น้ำต่ำกว่า 15 ซม. ผ่านได้ · 15-34 ผ่านได้แต่ไม่สะดวก · 35 ขึ้นไปผ่านไม่ได้
PASS_HARD_CM = 15
NO_PASS_CM = 35
INCIDENT_TYPE = {1: "FLOOD", 2: "LANDSLIDE_RISK"}  # อื่นๆ (อุบัติเหตุ ไฟป่า ฯลฯ) ไม่ใช้

_latest: list[dict] = []
_lock = threading.Lock()


def enabled() -> bool:
    # ปิดเป็นค่าเริ่มต้น: HDMS ตอบเฉพาะ IP ในไทย เซิร์ฟเวอร์จริงอยู่ต่างประเทศดึงไม่ได้
    # เปิดด้วย DOH_HDMS=true เมื่อเซิร์ฟเวอร์อยู่ในไทย
    return os.getenv("DOH_HDMS", "false").lower() == "true"


def depth_cm(text) -> int:
    """ระดับน้ำเป็นข้อความ เช่น "10", "10-15", "10-30 เป็นช่วงๆ" ใช้ค่ามากสุด ไม่มีตัวเลข = 0"""
    return max((int(n) for n in re.findall(r"\d+", str(text or ""))), default=0)


def severity(t: dict) -> str:
    # lane_closure: true = ผ่านได้, false = ผ่านไม่ได้ (ปิดถนน)
    if t.get("lane_closure") is False:
        return "HIGH"
    cm = depth_cm(t.get("flood_level"))
    if cm >= NO_PASS_CM:
        return "HIGH"
    if cm >= PASS_HARD_CM or INCIDENT_TYPE.get(t.get("incident_type_id")) == "LANDSLIDE_RISK":
        return "MEDIUM"
    return "LOW"


def to_hazard(t: dict) -> dict | None:
    kind = INCIDENT_TYPE.get(t.get("incident_type_id"))
    if not kind or t.get("end_date"):
        return None  # ชนิดที่ไม่ใช้ หรือจบแล้ว
    try:
        lat, lng = float(t["latitude"]), float(t["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if not in_thailand(lat, lng):
        return None
    level = severity(t)
    road = str(t.get("road_code") or "").lstrip("0")
    title = (t.get("case_name") or ("น้ำท่วมทาง" if kind == "FLOOD" else "ดินโคลนถล่ม")).strip()
    where = f"ทล.{road} กม.{t['km_start']}" if road and t.get("km_start") else (f"ทล.{road}" if road else "")
    if t.get("lane_closure") is False:
        status = "ปิดถนน " + (t.get("road_closure_text") or "").strip()
    elif kind == "FLOOD":
        cm = depth_cm(t.get("flood_level"))
        status = (f"น้ำสูง {cm} ซม. " if cm else "") + ("ผ่านได้แต่ไม่สะดวก" if level == "MEDIUM" else "ผ่านได้")
    else:
        status = "ผ่านได้ ระวัง"
    bypass = (t.get("bypass_desc") or "").strip()
    text = " · ".join(x for x in (title, where, status.strip()) if x)
    if bypass and bypass not in ("ไม่มี", "-"):
        text += f" · ทางเลี่ยง: {bypass}"
    updated = t.get("updated_date") or t.get("start_date") or ""
    return {
        "hazard_id": f"doh-{t.get('gid') or t.get('case_id')}",
        "hazard_type": kind,
        "severity": level,
        "lat": round(lat, 5),
        "lng": round(lng, 5),
        "province": (t.get("province") or "").replace("จ.", "").strip() or None,
        "title_th": text[:200],
        "source": "DOH",
        "updated_at": (updated[:19] + "Z") if updated else None,
        # จุดเกิดเหตุอยู่บนถนนพอดี risk-decision นับเฉพาะเส้นทางที่วิ่งผ่านจุดนี้
        "road_cells": [[round(lat, 4), round(lng, 4)]],
    }


def to_hazards(tickets: list) -> list[dict]:
    return [h for h in map(to_hazard, tickets if isinstance(tickets, list) else []) if h]


def fetch() -> list[dict]:
    today = datetime.now(timezone.utc).date()
    params = {"start": (today - timedelta(days=LOOKBACK_DAYS)).isoformat(), "end": (today + timedelta(days=1)).isoformat()}
    res = httpx.get(HDMS_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S)
    res.raise_for_status()
    return to_hazards(res.json())


def latest() -> list[dict]:
    with _lock:
        return list(_latest)


def refresh_once() -> None:
    global _latest
    started = time.monotonic()
    try:
        result = fetch()
        with _lock:
            _latest = result
        logger.info("doh hdms: %d open highway incidents in %.1f s", len(result), time.monotonic() - started)
    except Exception:
        # keep the previous result; slightly old road closures are better than none
        logger.warning("doh hdms refresh failed", exc_info=True)


def keep_fresh() -> None:
    while True:
        refresh_once()
        time.sleep(REFRESH_S)
