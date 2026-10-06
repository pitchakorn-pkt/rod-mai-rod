"""tools ที่ LLM เรียกได้ ทุกตัวทำงานผ่าน backend() ด้วย token ของผู้ใช้

LLM ส่งแค่ trip_no และเวลาแบบคน (เลื่อนกี่วัน / กี่ชั่วโมง / กี่โมงตามเวลาไทย) การคิดวันที่และแปลง UTC ทำในโค้ดนี้
ตัวเลขอากาศและระดับความเสี่ยงที่คืนให้ LLM มาจากระบบทั้งหมด
"""
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from envelope import ApiError
from rules import BANGKOK, RISK_TH, Backend, departs, find_trip, label, nearest_trip, thai_time, to_utc_iso

EMERGENCY_TYPES = {"RAIN", "HEAVY_RAIN", "STRONG_WIND", "FLOOD", "LANDSLIDE_RISK", "STORM", "EARTHQUAKE"}  # CONTRACT หัวข้อ 4
ZERO_WIDTH = re.compile(r"[​-‍﻿]")  # ชื่อใน OSM บางชื่อมีอักขระล่องหน ทำให้โมเดลพิมพ์เพี้ยน
HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
YMD = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
MAX_SHIFT_DAYS = 14

SCHEMAS = [
    {"type": "function", "function": {
        "name": "list_trips",
        "description": "รายการทริปทั้งหมดของผู้ใช้ พร้อมเลขทริป ต้นทาง ปลายทาง เวลาออก (เวลาไทย) และสถานะแผน",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "update_trip_time",
        "description": "เปลี่ยนเวลาออกเดินทางของทริปแล้ววางแผนเส้นทางใหม่ให้อัตโนมัติ "
                       "ใช้เมื่อผู้ใช้สั่งเลื่อนทริปชัดเจนเท่านั้น ถ้าไม่รู้ว่าทริปไหนให้ถามก่อน",
        "parameters": {"type": "object", "properties": {
            "trip_no": {"type": "integer", "description": "เลขทริป เช่น Trip 01 คือ 1"},
            "shift_days": {"type": "integer", "description": "เลื่อนจากวันเดิมกี่วัน เช่น วันถัดไป = 1 ไม่เลื่อนวัน = 0"},
            "time": {"type": "string", "description": "เวลาออกใหม่ตามเวลาไทย HH:MM เช่น 13:00 ไม่ส่ง = เวลาเดิม"},
            "date": {"type": "string",
                     "description": "วันออกใหม่ตามเวลาไทย YYYY-MM-DD ใช้เมื่อผู้ใช้บอกวันที่ตรงๆ เช่น 29 ก.ย. ไม่ส่ง = วันเดิม"},
            "shift_hours": {"type": "integer",
                            "description": "เลื่อนจากเวลาเดิมกี่ชั่วโมง เช่น ออกไป 3 ชม. = 3 เร็วขึ้น 2 ชม. = -2 "
                                           "ไม่ต้องรู้เวลาเดิม ระบบคิดให้"},
        }, "required": ["trip_no"]},
    }},
    {"type": "function", "function": {
        "name": "plan_trip",
        "description": "คำนวณเส้นทางและความเสี่ยงของทริปใหม่ ใช้เมื่อทริปยังไม่มีแผนหรือแผนเก่า (STALE)",
        "parameters": {"type": "object", "properties": {
            "trip_no": {"type": "integer"},
        }, "required": ["trip_no"]},
    }},
    {"type": "function", "function": {
        "name": "get_trip_weather",
        "description": "พยากรณ์อากาศและความเสี่ยงของแต่ละจุดในทริป ณ เวลาที่คาดว่าจะไปถึง จากแผนล่าสุด",
        "parameters": {"type": "object", "properties": {
            "trip_no": {"type": "integer"},
        }, "required": ["trip_no"]},
    }},
    {"type": "function", "function": {
        "name": "nearby_places",
        "description": "สถานที่จริงรอบสถานที่หนึ่ง (OpenStreetMap) ใช้ตอนผู้ใช้ขอให้แนะนำที่เที่ยว แนะนำจากผลนี้ "
                       "เลือก kinds ตามแนวที่ผู้ใช้อยากได้",
        "parameters": {"type": "object", "properties": {
            "place": {"type": "string", "description": "ชื่อสถานที่หรือเมือง เช่น เชียงใหม่"},
            "kinds": {"type": "array", "items": {"type": "string", "enum": ["attraction", "cafe", "market", "park", "mall", "nightlife", "waterfall"]},
                      "description": "attraction = วัด พิพิธภัณฑ์ อนุสาวรีย์ จุดชมวิว (ค่าเริ่มต้น), cafe = คาเฟ่, market = ตลาด ถนนคนเดิน, "
                                     "park = สวนสาธารณะ, mall = ห้าง, nightlife = บาร์ ผับ, waterfall = น้ำตก เช่น แนววัยรุ่น = cafe, market, mall, nightlife แนวธรรมชาติ = park, waterfall"},
            "radius_km": {"type": "integer", "description": "รัศมี 1-20 กม. ทั้งเมืองใช้ 15 ไม่ส่ง = 5"},
        }, "required": ["place"]},
    }},
    {"type": "function", "function": {
        "name": "place_conditions",
        "description": "อากาศตอนนี้ ฝน และภัย (น้ำท่วม พายุ แผ่นดินไหว) รอบสถานที่หรือจังหวัดที่ไม่ใช่ทริป "
                       "ใช้ตอนผู้ใช้ถาม เช่น สระบุรีฝนตกไหม น้ำท่วมไหม ถ้าถามถึงทริปใช้ get_trip_weather",
        "parameters": {"type": "object", "properties": {
            "place": {"type": "string", "description": "ชื่อสถานที่หรือจังหวัด เช่น สระบุรี"},
        }, "required": ["place"]},
    }},
    {"type": "function", "function": {
        "name": "hazards_now",
        "description": "ภัยที่เกิดอยู่ตอนนี้ทั่วประเทศ หรือในจังหวัดที่ระบุ: น้ำท่วมจากดาวเทียม (รวมถนนที่น้ำท่วม) "
                       "ดินถล่ม แผ่นดินไหว ใช้ตอนผู้ใช้ถาม เช่น ช่วงนี้ที่ไหนน้ำท่วม ถนนไหนน้ำท่วม "
                       "โดยไม่ได้ถามรอบสถานที่เดียว (ถามรอบสถานที่ใช้ place_conditions)",
        "parameters": {"type": "object", "properties": {
            "province": {"type": "string", "description": "ชื่อจังหวัด เช่น นครสวรรค์ ไม่ระบุ = ทั้งประเทศ"},
            "hazard_type": {"type": "string", "enum": ["FLOOD", "LANDSLIDE_RISK", "STORM", "EARTHQUAKE"],
                            "description": "ชนิดภัยที่ถาม ไม่ระบุ = ทุกชนิด"},
        }},
    }},
    {"type": "function", "function": {
        "name": "create_trip",
        "description": "สร้างทริปใหม่แล้ววางแผนเส้นทางให้ทันที ต้องรู้ต้นทาง ปลายทาง วันและเวลาออก ขาดข้อไหนให้ถามก่อน",
        "parameters": {"type": "object", "properties": {
            "origin": {"type": "string", "description": "ชื่อต้นทาง เช่น กรุงเทพ หรือ ตำแหน่งปัจจุบัน (ใช้ GPS ของผู้ใช้)"},
            "destination": {"type": "string", "description": "ชื่อปลายทาง"},
            "date": {"type": "string", "description": "วันออกตามเวลาไทย YYYY-MM-DD"},
            "time": {"type": "string", "description": "เวลาออกตามเวลาไทย HH:MM"},
            "stops": {"type": "array", "items": {"type": "string"}, "description": "จุดแวะตามลำดับ ไม่เกิน 5 จุด"},
            "return_date": {"type": "string",
                            "description": "วันกลับตามเวลาไทย YYYY-MM-DD ถ้าผู้ใช้บอก ระบบสร้างทริปขากลับ (สลับต้นทางกับปลายทาง) ให้เอง"},
            "return_time": {"type": "string", "description": "เวลาออกขากลับ HH:MM ไม่บอกใช้เวลาเดียวกับขาไป"},
        }, "required": ["origin", "destination", "date", "time"]},
    }},
    {"type": "function", "function": {
        "name": "emergency_info",
        "description": "เบอร์โทรฉุกเฉินและขั้นตอนรับมือภัยจากระบบ ใช้ทุกครั้งที่ผู้ใช้ถามเบอร์ฉุกเฉินหรือต้องบอกเบอร์โทร",
        "parameters": {"type": "object", "properties": {
            "hazard_type": {"type": "string", "enum": sorted(EMERGENCY_TYPES),
                            "description": "ชนิดภัยที่ถาม ไม่รู้หรือถามแค่เบอร์ ไม่ต้องส่ง"},
        }},
    }},
    {"type": "function", "function": {
        "name": "update_trip_places",
        "description": "แก้ต้นทาง ปลายทาง หรือจุดแวะของทริป แล้ววางแผนใหม่ให้ ส่งเฉพาะช่องที่เปลี่ยน",
        "parameters": {"type": "object", "properties": {
            "trip_no": {"type": "integer"},
            "origin": {"type": "string", "description": "ต้นทางใหม่"},
            "destination": {"type": "string", "description": "ปลายทางใหม่"},
            "stops": {"type": "array", "items": {"type": "string"},
                      "description": "จุดแวะชุดใหม่ทั้งหมดตามลำดับ (แทนของเดิม) [] = ไม่แวะ"},
        }, "required": ["trip_no"]},
    }},
]

# tools ที่แก้ข้อมูล ถ้าเรียกสำเร็จไปแล้วห้ามสลับไปผู้ให้บริการตัวสำรองแล้วเริ่มใหม่ (จะเลื่อนซ้ำ)
MUTATING = {"update_trip_time", "plan_trip", "create_trip", "update_trip_places"}
MAX_STOPS = 5  # CONTRACT หัวข้อ 4


def place_name(p: dict) -> str:
    return p.get("name") or f"{p['lat']:.3f}, {p['lng']:.3f}"


PLAN_STATUS_TH = {"FRESH": "วางแผนแล้ว", "STALE": "แผนเก่า ต้องกด Plan ใหม่", "NONE": "ยังไม่ได้วางแผน"}


# ส่งคำไทยให้ LLM ใช้ตอบ ไม่อย่างนั้นจะพิมพ์รหัสอย่าง LOW / FRESH ให้ผู้ใช้เห็น
def plan_summary(plan: dict) -> dict:
    return {"risk_th": RISK_TH.get(plan.get("risk_level"), "ไม่ทราบ"), "recommendation": plan.get("recommendation"),
            "summary_th": plan.get("summary_th"), "warnings": plan.get("warnings", [])}


def context_text(trips: list[dict], now: Optional[datetime] = None) -> str:
    """เวลาตอนนี้ + ทริปของผู้ใช้ ให้ LLM รู้ว่า "ทริปที่ใกล้ที่สุด" หรือ "ทริปไปเชียงใหม่" คือเลขอะไร (ไม่เกิน 10 ทริป)"""
    now = now or datetime.now(timezone.utc)
    lines = [f"ข้อมูลบริบท: ตอนนี้ {now.astimezone(BANGKOK):%Y-%m-%d %H:%M} น. เวลาไทย"]
    near = nearest_trip(trips, now)
    for t in sorted(trips, key=departs)[:10]:
        mark = " (ทริปที่ใกล้ที่สุด)" if near and t["trip_no"] == near["trip_no"] else ""
        lines.append(f"- {label(t['trip_no'])}{mark}: {route_th(t)} ออก {thai_time(t['departure_time'])}")
    if not trips:
        lines.append("ผู้ใช้ยังไม่มีทริป")
    return "\n".join(lines)


def trip_no(args: dict) -> Optional[int]:
    return int(args["trip_no"]) if args.get("trip_no") is not None else None


def list_trips(args: dict, backend: Backend, auth: str) -> tuple[dict, list]:
    trips = backend("GET", "/api/v1/trips", auth)
    return {"trips": [{
        "trip_no": t["trip_no"], "name": label(t["trip_no"]),
        "origin": place_name(t["origin"]), "destination": place_name(t["destination"]),
        "departure_th": thai_time(t["departure_time"]),
        "plan_th": PLAN_STATUS_TH.get(t.get("plan_status"), "ไม่ทราบ"),
    } for t in trips]}, []


def update_trip_time(args: dict, backend: Backend, auth: str, now: Optional[datetime] = None) -> tuple[dict, list]:
    trip, ask = find_trip(trip_no(args), backend, auth)
    if ask:
        return {"error": ask}, []
    shift = int(args.get("shift_days") or 0)
    if not 0 <= shift <= MAX_SHIFT_DAYS:
        return {"error": f"เลื่อนได้ 0-{MAX_SHIFT_DAYS} วัน"}, []
    shift_hours = int(args.get("shift_hours") or 0)
    if abs(shift_hours) > MAX_SHIFT_DAYS * 24:
        return {"error": f"เลื่อนได้ไม่เกิน {MAX_SHIFT_DAYS * 24} ชั่วโมง"}, []
    new = datetime.fromisoformat(trip["departure_time"].replace("Z", "+00:00")).astimezone(BANGKOK)
    new += timedelta(days=shift)
    if args.get("date"):
        d = YMD.match(str(args["date"]).strip())
        if not d:
            return {"error": "วันที่ต้องเป็นรูปแบบ YYYY-MM-DD"}, []
        new = new.replace(year=int(d.group(1)), month=int(d.group(2)), day=int(d.group(3)))
    if args.get("time"):
        m = HHMM.match(str(args["time"]).strip())
        if not m:
            return {"error": "เวลาต้องเป็นรูปแบบ HH:MM"}, []
        # วันตามเวลาไทย แล้วค่อยแปลงเป็น UTC
        new = new.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    new += timedelta(hours=shift_hours)
    if new.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M") == trip["departure_time"][:16]:
        return {"error": "เวลาใหม่ตรงกับเวลาเดิม ไม่ได้เปลี่ยนอะไร"}, []
    if new <= (now or datetime.now(timezone.utc)):
        return {"error": f"เวลาใหม่ {thai_time(to_utc_iso(new))} ผ่านไปแล้ว"}, []

    tid = trip["trip_id"]
    backend("PATCH", f"/api/v1/trips/{tid}", auth, json={"departure_time": to_utc_iso(new)})
    actions = [{"type": "TRIP_UPDATED", "trip_id": tid, "trip_no": trip["trip_no"]}]
    result = {"updated": True, "name": label(trip["trip_no"]), "departure_th": thai_time(to_utc_iso(new))}
    try:
        result["plan"] = plan_summary(backend("POST", f"/api/v1/trips/{tid}/plan", auth))
    except ApiError as e:
        result["plan_error"] = f"เลื่อนแล้วแต่วางแผนใหม่ไม่สำเร็จ ({e.message}) ให้ผู้ใช้กด Plan ในหน้า My Trip"
    return result, actions


def plan_trip(args: dict, backend: Backend, auth: str) -> tuple[dict, list]:
    trip, ask = find_trip(trip_no(args), backend, auth)
    if ask:
        return {"error": ask}, []
    plan = backend("POST", f"/api/v1/trips/{trip['trip_id']}/plan", auth)
    actions = [{"type": "TRIP_UPDATED", "trip_id": trip["trip_id"], "trip_no": trip["trip_no"]}]
    return {"planned": True, "name": label(trip["trip_no"]), **plan_summary(plan)}, actions


def get_trip_weather(args: dict, backend: Backend, auth: str) -> tuple[dict, list]:
    trip, ask = find_trip(trip_no(args), backend, auth)
    if ask:
        return {"error": ask}, []
    trip = backend("GET", f"/api/v1/trips/{trip['trip_id']}", auth)
    plan = trip.get("plan")
    if plan is None:
        return {"error": f"{label(trip['trip_no'])} ยังไม่ได้วางแผน เรียก plan_trip ก่อน"}, []
    return {
        "name": label(trip["trip_no"]), "plan_th": PLAN_STATUS_TH.get(trip.get("plan_status"), "ไม่ทราบ"),
        **plan_summary(plan),
        "waypoints": [{"name": w.get("name"), "eta_th": thai_time(w["eta"]), "forecast": w.get("forecast"),
                       "risk_th": RISK_TH.get(w.get("risk_level"), "ไม่ทราบ")} for w in plan.get("waypoints", [])],
    }, []


# คำที่หมายถึงตำแหน่ง GPS ของผู้ใช้ run() แทนเป็นพิกัดจริงก่อนถึง resolve_place
HERE_WORDS = {"ตำแหน่งปัจจุบัน", "ตำแหน่งของฉัน", "ตำแหน่งฉัน", "ที่นี่", "ตรงนี้", "current location", "my location", "here"}
HERE_NAME = "ตำแหน่งปัจจุบัน"


def is_here(value) -> bool:
    return isinstance(value, str) and value.strip().lower() in HERE_WORDS


def with_here(args: dict, here: Optional[dict]) -> dict:
    """แทน "ตำแหน่งปัจจุบัน" ในต้นทาง ปลายทาง จุดแวะ ด้วยพิกัด GPS ที่หน้าเว็บส่งมา"""
    if not here:
        return args
    spot = {"lat": here["lat"], "lng": here["lng"], "name": HERE_NAME}
    out = {k: (spot if k in ("origin", "destination") and is_here(v) else v) for k, v in args.items()}
    if isinstance(out.get("stops"), list):
        out["stops"] = [spot if is_here(n) else n for n in out["stops"]]
    return out


def resolve_place(query, backend: Backend, auth: str) -> tuple[Optional[dict], Optional[str]]:
    """ชื่อที่ผู้ใช้พิมพ์ > ผลแรกของ /places/search คืน (สถานที่, None) หรือ (None, เหตุผลให้ถามผู้ใช้)
    query เป็นพิกัดอยู่แล้ว (ตำแหน่งปัจจุบันจาก with_here) ใช้ได้เลย"""
    if isinstance(query, dict):
        return query, None
    if is_here(query):
        return None, "ยังไม่รู้ตำแหน่งปัจจุบันของผู้ใช้ (เบราว์เซอร์ไม่ได้ส่งมา) ให้ถามต้นทางเป็นชื่อสถานที่"
    q = str(query or "").strip()
    found = backend("GET", "/api/v1/places/search", auth, params={"q": q})["places"] if len(q) >= 2 else []
    if not found:
        return None, f"หาสถานที่ \"{q}\" ไม่เจอ ให้ถามผู้ใช้ชื่อที่ชัดขึ้น เช่น ใส่อำเภอหรือจังหวัด"
    return {"lat": found[0]["lat"], "lng": found[0]["lng"], "name": found[0]["name"]}, None


def resolve_stops(names: list, backend: Backend, auth: str) -> tuple[list[dict], Optional[str]]:
    if len(names) > MAX_STOPS:
        return [], f"จุดแวะได้ไม่เกิน {MAX_STOPS} จุด"
    stops = []
    for n in names:
        place, err = resolve_place(n, backend, auth)
        if err:
            return [], err
        stops.append(place)
    return stops, None


def route_th(trip: dict) -> str:
    return " > ".join(place_name(p) for p in [trip["origin"], *(trip.get("waypoints") or []), trip["destination"]])


def saved_and_planned(trip: dict, backend: Backend, auth: str, result: dict) -> dict:
    """บันทึกแล้ววางแผนต่อ แผนพังก็ยังบอกผู้ใช้ได้ว่าบันทึกแล้ว"""
    result.update({"name": label(trip["trip_no"]), "route_th": route_th(trip), "departure_th": thai_time(trip["departure_time"])})
    try:
        result["plan"] = plan_summary(backend("POST", f"/api/v1/trips/{trip['trip_id']}/plan", auth))
    except ApiError as e:
        result["plan_error"] = f"บันทึกแล้วแต่วางแผนเส้นทางไม่สำเร็จ ({e.message}) ให้ผู้ใช้กด Plan ในหน้า My Trip"
    return result


def nearby_places(args: dict, backend: Backend, auth: str) -> tuple[dict, list]:
    place, err = resolve_place(args.get("place"), backend, auth)
    if err:
        return {"error": err}, []
    params = {"lat": place["lat"], "lng": place["lng"]}
    if args.get("kinds"):
        params["kinds"] = ",".join(args["kinds"])
    if args.get("radius_km"):
        params["radius_km"] = max(1, min(20, int(args["radius_km"])))
    try:
        found = backend("GET", "/api/v1/places/nearby", auth, params=params)["places"]
    except ApiError as e:
        if e.code != "UPSTREAM_TIMEOUT":
            raise
        # ครั้งแรกของพื้นที่ใหม่ api-backend ตอบไม่ทันแต่โหลดต่อเบื้องหลัง ถามซ้ำอีกครั้งมักได้แล้ว
        found = backend("GET", "/api/v1/places/nearby", auth, params=params)["places"]
    return {"around": place["name"], "places": [{"name": ZERO_WIDTH.sub("", p["name"]).strip(), "kind_th": p.get("kind_th")}
                                                for p in found]}, []


def emergency_info(args: dict, backend: Backend, auth: str) -> tuple[dict, list]:
    """เบอร์จากระบบเท่านั้น โมเดลเคยแต่งเบอร์เอง (1669 = สุขภาพจิต) ซึ่งอันตราย"""
    hazard = args.get("hazard_type") if args.get("hazard_type") in EMERGENCY_TYPES else None
    data = backend("GET", "/api/v1/safety/emergency", auth, params={"hazard_type": hazard or "FLOOD"})
    out = {"contacts": data.get("contacts", []), "note": "บอกเฉพาะเบอร์ในรายการนี้ ห้ามเพิ่มเบอร์อื่น"}
    if hazard:
        out["steps_th"] = data.get("steps_th", [])
    return out, []


HAZARD_KM = 30  # ภัยที่นับว่า "รอบสถานที่"
HAZARD_TYPE_TH = {"FLOOD": "น้ำท่วม", "STORM": "พายุ", "EARTHQUAKE": "แผ่นดินไหว", "LANDSLIDE_RISK": "ดินถล่ม",
                  "HEAVY_RAIN": "ฝนหนัก", "RAIN": "ฝน", "STRONG_WIND": "ลมแรง"}


def km(a: dict, b: dict) -> float:
    dlat, dlng = math.radians(b["lat"] - a["lat"]), math.radians(b["lng"] - a["lng"])
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a["lat"])) * math.cos(math.radians(b["lat"])) * math.sin(dlng / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def place_conditions(args: dict, backend: Backend, auth: str) -> tuple[dict, list]:
    """อากาศตอนนี้ของจุดใกล้สุด + ฝนในตาราง ~25 กม. (/weather/area) + ภัยไม่เกิน HAZARD_KM (/hazards)"""
    place, err = resolve_place(args.get("place"), backend, auth)
    if err:
        return {"error": err}, []
    out: dict = {"place": place["name"], "note": "เป็นข้อมูลตอนนี้ ไม่ใช่พยากรณ์ล่วงหน้า"}
    area = backend("GET", "/api/v1/weather/area", auth, params={"lat": place["lat"], "lng": place["lng"]})
    cells = [c for c in area.get("cells", []) if c.get("forecast")]
    if cells:
        here = min(cells, key=lambda c: km(place, c))["forecast"]
        raining = [c["forecast"]["rain_mm_per_h"] for c in cells if c["forecast"]["rain_mm_per_h"] > 0]
        out["weather_now"] = {"time_th": thai_time(here["time"]), "condition_th": here["condition_th"],
                              "temp_c": here["temp_c"], "rain_mm_per_h": here["rain_mm_per_h"], "wind_kmh": here["wind_kmh"]}
        out["rain_around_th"] = (f"ฝนตก {len(raining)} จาก {len(cells)} จุดรอบๆ (รัศมีราว 25 กม.) หนักสุด {max(raining)} มม./ชม."
                                 if raining else f"ไม่มีฝนทั้ง {len(cells)} จุดรอบๆ (รัศมีราว 25 กม.)")
    else:
        out["weather_now"] = "ดึงข้อมูลอากาศไม่ได้ตอนนี้"
    d = HAZARD_KM / 111 + 0.05
    feed = backend("GET", "/api/v1/hazards", auth, params={"min_lat": place["lat"] - d, "min_lng": place["lng"] - d,
                                                           "max_lat": place["lat"] + d, "max_lng": place["lng"] + d})
    found = []
    for h in feed.get("hazards", []):
        if h.get("source") == "OPEN_METEO":  # ฝน/ลมตอนนี้ นับจาก weather_now แล้ว
            continue
        dist = km(place, h)
        if dist > HAZARD_KM:
            continue
        item = {"title_th": h.get("title_th"), "type_th": HAZARD_TYPE_TH.get(h.get("hazard_type"), h.get("hazard_type")),
                "severity_th": RISK_TH.get(h.get("severity"), "ไม่ทราบ"), "distance_km": round(dist, 1)}
        roads = h.get("road_cells")
        if roads is not None:
            item["flooded_road_th"] = (f"ถนนที่ท่วมใกล้สุดห่าง {min(km(place, {'lat': r[0], 'lng': r[1]}) for r in roads):.1f} กม."
                                       if roads else "ท่วมพื้นที่เกษตร ไม่มีถนนท่วม")
        found.append(item)
    found.sort(key=lambda x: x["distance_km"])
    out["hazards"] = found[:6]
    out["hazards_th"] = f"มีภัย {len(found)} จุดในรัศมี {HAZARD_KM} กม." if found else f"ไม่มีภัยในรัศมี {HAZARD_KM} กม."
    warnings = [*area.get("warnings", []), *feed.get("warnings", [])]
    if warnings:
        out["warnings"] = warnings
    return out, []


THAILAND_BOX = {"min_lat": 5.6, "min_lng": 97.3, "max_lat": 20.5, "max_lng": 105.7}
SOURCE_TH = {"DOH": "กรมทางหลวง", "GISTDA": "ดาวเทียม GISTDA", "GDACS": "GDACS", "USGS": "USGS", "DERIVED": "ประเมินจากฝนสะสม"}
SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
HAZARDS_NOW_LIMIT = 8


def hazards_now(args: dict, backend: Backend, auth: str) -> tuple[dict, list]:
    """ภัยตอนนี้ทั้งประเทศหรือรายจังหวัด รุนแรงก่อน ถนนปิดของกรมทางหลวงก่อนในระดับเดียวกัน"""
    feed = backend("GET", "/api/v1/hazards", auth, params=THAILAND_BOX)
    province = (args.get("province") or "").replace("จังหวัด", "").replace("จ.", "").strip()
    wanted = args.get("hazard_type")
    found = []
    for h in feed.get("hazards", []):
        if h.get("source") == "OPEN_METEO":  # ฝน/ลมชั่วโมงนี้ ไม่ใช่เหตุที่เกิดค้างอยู่
            continue
        if wanted and h.get("hazard_type") != wanted:
            continue
        if province and province not in (h.get("province") or "") and province not in (h.get("title_th") or ""):
            continue
        found.append(h)
    found.sort(key=lambda h: (SEVERITY_ORDER.get(h.get("severity"), 3), h.get("source") != "DOH"))
    high = sum(h.get("severity") == "HIGH" for h in found)
    closed = sum(h.get("source") == "DOH" and h.get("severity") == "HIGH" for h in found)
    where = f"จังหวัด{province}" if province else "ทั่วประเทศ"
    summary = f"{where} มีภัย {len(found)} จุด ระดับสูง {high} จุด" if found else f"{where} ไม่มีรายงานภัยตอนนี้"
    # นับถนนปิดเฉพาะตอนเปิดข้อมูลกรมทางหลวง (มีหมุด DOH) ไม่งั้น "0 จุด" ทำให้แชทตอบว่าไม่มีถนนปิดทั้งที่ไม่ได้เช็ค
    if found and any(h.get("source") == "DOH" for h in feed.get("hazards", [])):
        summary += f" (ทางหลวงที่ผ่านไม่ได้หรือน้ำลึกเกิน 35 ซม. {closed} จุด)"
    out: dict = {
        "note": "เป็นข้อมูลตอนนี้ ไม่ใช่พยากรณ์ล่วงหน้า",
        "summary_th": summary,
        "hazards": [{"title_th": h.get("title_th"), "province": h.get("province"),
                     "type_th": HAZARD_TYPE_TH.get(h.get("hazard_type"), h.get("hazard_type")),
                     "severity_th": RISK_TH.get(h.get("severity"), "ไม่ทราบ"),
                     "source_th": SOURCE_TH.get(h.get("source"), h.get("source"))} for h in found[:HAZARDS_NOW_LIMIT]],
    }
    if feed.get("warnings"):
        out["warnings"] = feed["warnings"]
    return out, []


def same_trip(trips: list[dict], origin: dict, destination: dict, when: datetime) -> Optional[dict]:
    """ทริปที่ต้นทาง ปลายทาง (ห่างไม่เกินราว 100 ม.) และเวลาออกตรงกัน = ทริปซ้ำ"""
    def near(a: dict, b: dict) -> bool:
        return abs(a["lat"] - b["lat"]) < 0.001 and abs(a["lng"] - b["lng"]) < 0.001
    return next((t for t in trips if departs(t) == when and near(t["origin"], origin)
                 and near(t["destination"], destination)), None)


def thai_datetime(date, time) -> Optional[datetime]:
    d = YMD.match(str(date or "").strip())
    t = HHMM.match(str(time or "").strip())
    if not d or not t:
        return None
    return datetime(int(d.group(1)), int(d.group(2)), int(d.group(3)), int(t.group(1)), int(t.group(2)), tzinfo=BANGKOK)


def create_trip(args: dict, backend: Backend, auth: str, now: Optional[datetime] = None) -> tuple[dict, list]:
    when = thai_datetime(args.get("date"), args.get("time"))
    if when is None:
        return {"error": "ต้องรู้วันและเวลาออก ให้ถามผู้ใช้"}, []
    if when <= (now or datetime.now(timezone.utc)):
        return {"error": f"เวลาออก {thai_time(to_utc_iso(when))} ผ่านไปแล้ว"}, []
    # ขากลับ: เช็กก่อนสร้างอะไร ผิดจะได้ไม่เหลือขาไปค้างครึ่งเดียว
    back_when = None
    if args.get("return_date"):
        back_when = thai_datetime(args["return_date"], args.get("return_time") or args.get("time"))
        if back_when is None or back_when <= when:
            return {"error": "วันเวลากลับต้องหลังเวลาออกขาไป ให้ถามผู้ใช้อีกครั้ง"}, []
    origin, err = resolve_place(args.get("origin"), backend, auth)
    if err:
        return {"error": err}, []
    destination, err = resolve_place(args.get("destination"), backend, auth)
    if err:
        return {"error": err}, []
    stops, err = resolve_stops(args.get("stops") or [], backend, auth)
    if err:
        return {"error": err}, []
    same = same_trip(backend("GET", "/api/v1/trips", auth), origin, destination, when)
    if same:
        # ผู้ใช้พิมพ์ "สร้างเลย" ซ้ำหลังสร้างไปแล้ว โมเดลเคยสร้างทริปเดิมซ้ำอีกอัน
        return {"error": f"มี {label(same['trip_no'])} เส้นทางและเวลาออกนี้อยู่แล้ว ไม่ได้สร้างซ้ำ บอกผู้ใช้ว่าสร้างไว้แล้ว"}, []
    trip = backend("POST", "/api/v1/trips", auth, json={
        "origin": origin, "destination": destination, "departure_time": to_utc_iso(when), "waypoints": stops})
    actions = [{"type": "TRIP_CREATED", "trip_id": trip["trip_id"], "trip_no": trip["trip_no"]}]
    result = saved_and_planned(trip, backend, auth, {"created": True})
    if back_when and not same_trip(backend("GET", "/api/v1/trips", auth), destination, origin, back_when):
        # สลับสถานที่ที่หาไว้แล้วตรงๆ ขากลับจึงจบที่ต้นทางเดิมเป๊ะ (เช่น ตำแหน่งปัจจุบัน) ไม่ให้โมเดลพิมพ์ชื่อเอง
        back = backend("POST", "/api/v1/trips", auth, json={
            "origin": destination, "destination": origin, "departure_time": to_utc_iso(back_when),
            "waypoints": stops[::-1]})
        actions.append({"type": "TRIP_CREATED", "trip_id": back["trip_id"], "trip_no": back["trip_no"]})
        result["return_trip"] = saved_and_planned(back, backend, auth, {"created": True})
    return result, actions


def update_trip_places(args: dict, backend: Backend, auth: str) -> tuple[dict, list]:
    trip, ask = find_trip(trip_no(args), backend, auth)
    if ask:
        return {"error": ask}, []
    patch: dict = {}
    for key in ("origin", "destination"):
        if args.get(key):
            patch[key], err = resolve_place(args[key], backend, auth)
            if err:
                return {"error": err}, []
    if args.get("stops") is not None:
        patch["waypoints"], err = resolve_stops(args["stops"], backend, auth)
        if err:
            return {"error": err}, []
    if not patch:
        return {"error": "ไม่ได้บอกว่าจะเปลี่ยนต้นทาง ปลายทาง หรือจุดแวะ"}, []
    saved = backend("PATCH", f"/api/v1/trips/{trip['trip_id']}", auth, json=patch)
    actions = [{"type": "TRIP_UPDATED", "trip_id": trip["trip_id"], "trip_no": trip["trip_no"]}]
    return saved_and_planned(saved, backend, auth, {"updated": True}), actions


HANDLERS = {"list_trips": list_trips, "update_trip_time": update_trip_time,
            "plan_trip": plan_trip, "get_trip_weather": get_trip_weather,
            "nearby_places": nearby_places, "place_conditions": place_conditions, "hazards_now": hazards_now, "emergency_info": emergency_info, "create_trip": create_trip, "update_trip_places": update_trip_places}


def run(name: str, args: dict, backend: Backend, auth: str, here: Optional[dict] = None) -> tuple[dict, list]:
    """คืน (ผลที่ส่งกลับให้ LLM, actions) actions มีเฉพาะเมื่อ api-backend ตอบสำเร็จแล้ว
    here = ตำแหน่ง GPS ของผู้ใช้ (ถ้ามี) ใช้แทนคำว่า "ตำแหน่งปัจจุบัน" """
    handler = HANDLERS.get(name)
    if handler is None:
        return {"error": f"ไม่มี tool ชื่อ {name}"}, []
    if not isinstance(args, dict):
        return {"error": "arguments ต้องเป็น object"}, []
    try:
        return handler(with_here(args, here), backend, auth)
    except ApiError as e:
        return {"error": e.message, "code": e.code}, []
    except (TypeError, ValueError):
        return {"error": "arguments ไม่ถูกต้อง"}, []
