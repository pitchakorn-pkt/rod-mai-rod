"""คำสั่งหลัก 3 แบบแบบกฎตายตัว (RUNBOOK หัวข้อ B) ใช้ได้แม้ LLM ล่ม

backend คือฟังก์ชัน backend(method, path, authorization, json=None) ใน app.py ส่งเข้ามาเพื่อให้เทสต์ mock ได้
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from envelope import ApiError

BANGKOK = ZoneInfo("Asia/Bangkok")
PERIOD_HOUR = {"เช้า": 8, "บ่าย": 13, "เย็น": 17}  # README ข้อ 4
TH_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
RISK_TH = {"LOW": "ต่ำ", "MEDIUM": "ปานกลาง", "HIGH": "สูง", None: "ไม่ทราบ"}
OUT_OF_RANGE_TH = "(วันเดินทางไกลเกินช่วงพยากรณ์อากาศ ลองถามใหม่เมื่อใกล้วันเดินทาง)"

TRIP_NO = re.compile(r"(?:trip|ทริป)\s*(?:ที่|no\.?|#)?\s*0*(\d+)", re.IGNORECASE)
NEXT_DAY = re.compile(r"วันถัดไป|พรุ่งนี้|อีก\s*1\s*วัน|อีกวัน")
# เลขอื่นนอกจากเลขทริป เช่น "อีก 2 วัน" "9 โมง" "13:30" กฎทำไม่ได้ ต้องให้ LLM ใช้ tools
# ถ้ากฎรับไปจะเลื่อนผิดเวลาโดยไม่บอกผู้ใช้
OTHER_NUMBER = re.compile(r"\d")
PERIOD = re.compile(r"(?:ช่วง|ตอน)?(เช้า|บ่าย|เย็น)")
MOVE = re.compile(r"เลื่อน|ย้าย|เปลี่ยนเวลา")
# ถามแบบสมมติ เช่น "ถ้าเลื่อน Trip 01 ไปบ่ายจะเสี่ยงน้อยลงไหม" ไม่ใช่คำสั่ง กฎห้ามเลื่อนจริง ส่งให้ LLM ตอบ
WHAT_IF = re.compile(r"ถ้า|หาก|สมมติ|ไหม|มั้ย|หรือเปล่า|หรือไม่|\?")
WEATHER = re.compile(r"อากาศ|ฝน|พยากรณ์")
# พูดถึงทริปโดยไม่บอกเลข = ทริปที่ยังไม่ถึงเวลาออกและออกเร็วที่สุด
NEAREST = re.compile(r"ใกล้(?:ที่)?สุด|ทริป(?:ถัดไป|ต่อไป|หน้า)")

Backend = Callable[..., object]


def thai_time(iso: str) -> str:
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(BANGKOK)
    return f"{t.day} {TH_MONTHS[t.month - 1]} {t:%H:%M} น."


def to_utc_iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def label(trip_no: int) -> str:
    return f"Trip {trip_no:02d}"


def reply(text: str, actions: Optional[list] = None) -> dict:
    return {"reply": text, "actions": actions or [], "warnings": []}


def parse(message: str) -> Optional[dict]:
    """แยกว่าเป็นคำสั่งแบบไหน คืน None ถ้าไม่เข้าแบบไหนเลย (ให้ LLM ตอบต่อ)"""
    m = TRIP_NO.search(message)
    trip_no = int(m.group(1)) if m else None
    nearest = trip_no is None and bool(NEAREST.search(message))
    rest = NEXT_DAY.sub(" ", TRIP_NO.sub(" ", message))
    if MOVE.search(message) and not OTHER_NUMBER.search(rest) and not WHAT_IF.search(message):
        p = PERIOD.search(message)
        hour = PERIOD_HOUR[p.group(1)] if p else None
        if NEXT_DAY.search(message):
            return {"kind": "next_day", "trip_no": trip_no, "hour": hour, "nearest": nearest}
        if hour is not None:
            return {"kind": "period", "trip_no": trip_no, "hour": hour, "nearest": nearest}
    if WEATHER.search(message) and (trip_no is not None or nearest):
        return {"kind": "weather", "trip_no": trip_no, "nearest": nearest}
    return None


def departs(t: dict) -> datetime:
    return datetime.fromisoformat(t["departure_time"].replace("Z", "+00:00"))


def nearest_trip(trips: list[dict], now: Optional[datetime] = None) -> Optional[dict]:
    upcoming = [t for t in trips if departs(t) > (now or datetime.now(timezone.utc))]
    return min(upcoming, key=departs) if upcoming else None


def find_trip(trip_no: Optional[int], backend: Backend, auth: str, nearest: bool = False,
              now: Optional[datetime] = None) -> tuple[Optional[dict], Optional[str]]:
    """คืน (ทริป, None) หรือ (None, ข้อความถามกลับ) ห้ามเดาว่าผู้ใช้หมายถึงทริปไหน
    nearest = ผู้ใช้บอกชัดว่า "ทริปที่ใกล้ที่สุด" ไม่นับเป็นการเดา"""
    trips = backend("GET", "/api/v1/trips", auth)
    if not trips:
        return None, "ยังไม่มีทริปเลย สร้างทริปในหน้า My Trip ก่อนนะครับ"
    if trip_no is None:
        if len(trips) == 1:
            return trips[0], None
        if nearest and nearest_trip(trips, now):
            return nearest_trip(trips, now), None
        names = ", ".join(label(t["trip_no"]) for t in trips)
        return None, f"หมายถึงทริปไหนครับ ตอนนี้มี {names}"
    for t in trips:
        if t["trip_no"] == trip_no:
            return t, None
    names = ", ".join(label(t["trip_no"]) for t in trips)
    return None, f"ไม่เจอ {label(trip_no)} ตอนนี้มี {names}"


def move_and_replan(trip: dict, new_departure: datetime, backend: Backend, auth: str) -> dict:
    tid, name = trip["trip_id"], label(trip["trip_no"])
    backend("PATCH", f"/api/v1/trips/{tid}", auth, json={"departure_time": to_utc_iso(new_departure)})
    action = [{"type": "TRIP_UPDATED", "trip_id": tid, "trip_no": trip["trip_no"]}]
    moved = f"เลื่อน {name} ไปออกเดินทาง {thai_time(to_utc_iso(new_departure))} แล้ว"
    try:
        plan = backend("POST", f"/api/v1/trips/{tid}/plan", auth)
    except ApiError:
        return reply(f"{moved} แต่คำนวณเส้นทางใหม่ไม่สำเร็จ กด Plan ในหน้า My Trip อีกครั้งนะครับ", action)
    risk = RISK_TH[plan.get("risk_level")]
    text = f"{moved} และวางแผนใหม่ให้แล้ว ความเสี่ยงระดับ{risk} {plan.get('summary_th', '')}".strip()
    if "FORECAST_OUT_OF_RANGE" in plan.get("warnings", []):
        text += "\n" + OUT_OF_RANGE_TH
    return reply(text, action)


def weather_reply(trip: dict, backend: Backend, auth: str) -> dict:
    name = label(trip["trip_no"])
    trip = backend("GET", f"/api/v1/trips/{trip['trip_id']}", auth)
    plan = trip.get("plan")
    if plan is None:
        return reply(f"{name} ยังไม่ได้วางแผนเส้นทาง กด Plan ในหน้า My Trip ก่อน แล้วถามใหม่ได้เลยครับ")
    lines = [f"{name} ความเสี่ยงระดับ{RISK_TH[plan.get('risk_level')]} {plan.get('summary_th', '')}".strip()]
    if trip.get("plan_status") == "STALE":
        lines.append("(ทริปถูกแก้หลังวางแผน ข้อมูลนี้อาจไม่ตรงแล้ว ควรกด Plan ใหม่)")
    for w in plan.get("waypoints", []):
        f = w.get("forecast")
        weather = f"{f['condition_th']} ฝน {f['rain_mm_per_h']} มม./ชม. ลม {f['wind_kmh']} กม./ชม." if f else "ยังไม่มีข้อมูลอากาศ"
        lines.append(f"- {w['name']} ถึงประมาณ {thai_time(w['eta'])}: {weather}")
    return reply("\n".join(lines))


def try_rules(message: str, auth: str, backend: Backend, now: Optional[datetime] = None) -> Optional[dict]:
    cmd = parse(message)
    if cmd is None:
        return None
    try:
        trip, ask = find_trip(cmd["trip_no"], backend, auth, cmd["nearest"], now)
        if ask:
            return reply(ask)
        if cmd["kind"] == "weather":
            return weather_reply(trip, backend, auth)
        depart = datetime.fromisoformat(trip["departure_time"].replace("Z", "+00:00")).astimezone(BANGKOK)
        new = depart + timedelta(days=1) if cmd["kind"] == "next_day" else depart
        if cmd["hour"] is not None:
            # วันตามเวลาไทย ไม่ใช่ตาม UTC (ตีหนึ่งไทยยังเป็นวันก่อนหน้าใน UTC)
            new = new.replace(hour=cmd["hour"], minute=0, second=0, microsecond=0)
        if new <= (now or datetime.now(timezone.utc)):
            return reply(f"เวลาใหม่ {thai_time(to_utc_iso(new))} ผ่านไปแล้ว ลองเลือกเวลาอื่นนะครับ")
        return move_and_replan(trip, new, backend, auth)
    except ApiError as e:
        return reply(f"ทำรายการไม่สำเร็จ: {e.message}")
