"""api-backend

ผู้ใช้และทริปเก็บใน Postgres, login ด้วย bcrypt + JWT
การส่งต่อไป routing-engine / weather-disaster / assistant-agent / safety-knowledge ต่อไว้จริงแล้ว
ห้ามลบ endpoint ไหนออกก่อนมีของจริงมาแทน และรูปแบบข้อมูลต้องตรงกับ docs/CONTRACT.md หัวข้อ 6
"""
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, Header, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

import auth
import db
import places
from envelope import ApiError, call, ok, setup
from geo import haversine_km, in_thailand


DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo1234"
MAX_WAYPOINTS = 5
PAST_GRACE = timedelta(hours=1)
SAME_PLACE_KM = 0.5
LOGIN_LIMIT = (10, 60)  # 10 ครั้งต่อนาทีต่อ IP กันเดารหัสผ่าน
DISPLAY_NAME_MAX = 40
CHAT_LIMIT = (10, 60)  # 10 ข้อความต่อนาทีต่อผู้ใช้ กันโควตา LLM ฟรีหมด
DEPARTURE_OFFSETS_H = (3, 6)  # หน้าทริป "ออกเวลาไหนดี" เทียบกับเวลาเดิม
ROUTE_FORECAST_STEP_KM = 15

_hits: dict[str, list[float]] = {}
_hits_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    # scripts/smoke.sh login ด้วยคู่นี้ ถ้ามีอยู่แล้ว create_user ไม่ทำอะไร
    db.create_user(DEMO_EMAIL, auth.hash_password(DEMO_PASSWORD))
    yield
    db.close_db()


app = FastAPI(title="api-backend", lifespan=lifespan)
setup(app, "api-backend", health_check=db.ping)

# timeout (วินาที) ตาม CONTRACT หัวข้อ 3
ROUTING_TIMEOUT = 45
WEATHER_TIMEOUT = 10
ASSISTANT_TIMEOUT = 100
SAFETY_TIMEOUT = 10


class Place(BaseModel):
    lat: float
    lng: float
    name: Optional[str] = None


class Credentials(BaseModel):
    email: str
    password: str = Field(min_length=6)


class ProfileIn(BaseModel):
    display_name: Optional[str] = None


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6)


class LoginIn(BaseModel):
    # ล็อกอินไม่เช็กความยาว รหัสผิดแบบไหนก็ตอบ "อีเมลหรือรหัสผ่านไม่ถูกต้อง" เหมือนกัน
    email: str
    password: str


class RouteForecastIn(BaseModel):
    geometry: list[Place] = Field(min_length=2)
    departure_time: datetime
    duration_min: float = Field(gt=0)


class TripCreate(BaseModel):
    origin: Place
    destination: Place
    departure_time: datetime
    waypoints: list[Place] = []


class TripPatch(BaseModel):
    origin: Optional[Place] = None
    destination: Optional[Place] = None
    departure_time: Optional[datetime] = None
    waypoints: Optional[list[Place]] = None


class ChatIn(BaseModel):
    message: str
    history: list[dict] = []


def current_user(authorization: Optional[str]) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError("UNAUTHORIZED", "กรุณาเข้าสู่ระบบก่อน")
    user = db.find_user(auth.read_token(authorization.removeprefix("Bearer ")))
    if user is None:
        # token ถูกต้องแต่ผู้ใช้ไม่อยู่แล้ว เช่น หลัง make reset
        raise ApiError("UNAUTHORIZED", "กรุณาเข้าสู่ระบบก่อน")
    return user


def check_places(places: list[Place]) -> None:
    for p in places:
        if not in_thailand(p.lat, p.lng):
            raise ApiError("OUT_OF_THAILAND", "ตอนนี้รองรับเฉพาะสถานที่ในประเทศไทย")


def check_time(dt: datetime) -> None:
    if dt.tzinfo is None:
        raise ApiError("VALIDATION_ERROR", "departure_time ต้องมี timezone เช่น 2026-09-28T01:00:00Z")
    # ทริปย้อนหลังวางแผนไม่ได้ (ไม่มีพยากรณ์) เผื่อ 1 ชม. ให้ทริปที่เพิ่งออก
    if dt < datetime.now(timezone.utc) - PAST_GRACE:
        raise ApiError("VALIDATION_ERROR", "เวลาออกเดินทางผ่านไปแล้ว เลือกเวลาในอนาคต")


def check_not_same_place(origin: Place, destination: Place, waypoints: list[Place]) -> None:
    if not waypoints and haversine_km(origin.model_dump(), destination.model_dump()) < SAME_PLACE_KM:
        raise ApiError("VALIDATION_ERROR", "ต้นทางกับปลายทางเป็นที่เดียวกัน")


def rate_limit(key: str, limit: int, window_s: int) -> None:
    """จำกัดจำนวนครั้งต่อช่วงเวลา (นับในหน่วยความจำของ process นี้) เกินแล้วตอบ 429"""
    now = time.monotonic()
    with _hits_lock:
        hits = [t for t in _hits.get(key, []) if now - t < window_s]
        if len(hits) >= limit:
            raise ApiError("RATE_LIMITED", "ส่งคำขอถี่เกินไป รอสักครู่แล้วลองใหม่")
        hits.append(now)
        _hits[key] = hits
        if len(_hits) > 10000:
            _hits.clear()


def client_ip(request: Request) -> str:
    # Render และ proxy ส่ง IP จริงมาใน X-Forwarded-For
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "?")


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if "@" not in email:
        raise ApiError("VALIDATION_ERROR", "รูปแบบอีเมลไม่ถูกต้อง")
    return email


def get_owned_trip(trip_id: str, user: dict) -> dict:
    try:
        uuid.UUID(trip_id)
    except ValueError:
        # id ผิดรูปแบบส่งเข้า Postgres จะ error ถือว่าไม่เจอ
        raise ApiError("NOT_FOUND", "ไม่พบทริปนี้")
    trip = db.get_trip(trip_id)
    if trip is None:
        raise ApiError("NOT_FOUND", "ไม่พบทริปนี้")
    if trip["user_id"] != user["user_id"]:
        raise ApiError("FORBIDDEN", "ทริปนี้ไม่ใช่ของคุณ")
    return trip


# ---------- auth ----------

@app.post("/api/v1/auth/register")
def register(body: Credentials):
    email = normalize_email(body.email)
    # bcrypt อ่านแค่ 72 ไบต์แรก ภาษาไทยตัวละ 3 ไบต์
    if len(body.password.encode()) > 72:
        raise ApiError("VALIDATION_ERROR", "รหัสผ่านยาวเกินไป")
    user = db.create_user(email, auth.hash_password(body.password))
    if user is None:
        raise ApiError("VALIDATION_ERROR", "อีเมลนี้ถูกใช้สมัครแล้ว")
    return ok(user)


@app.post("/api/v1/auth/login")
def login(body: LoginIn, request: Request):
    rate_limit(f"login:{client_ip(request)}", *LOGIN_LIMIT)
    user = db.find_user_by_email(normalize_email(body.email))
    if user is None or not auth.check_password(body.password, user["password_hash"]):
        raise ApiError("UNAUTHORIZED", "อีเมลหรือรหัสผ่านไม่ถูกต้อง")
    if auth.needs_rehash(user["password_hash"]):
        db.set_password_hash(user["user_id"], auth.hash_password(body.password))
    # เลือก field เอง ห้ามส่ง password_hash ออกไป
    return ok({"token": auth.make_token(user["user_id"]),
               "user": {"user_id": user["user_id"], "email": user["email"], "display_name": user["display_name"]}})


@app.get("/api/v1/me")
def me(authorization: Optional[str] = Header(None)):
    return ok(current_user(authorization))


@app.patch("/api/v1/me")
def update_me(body: ProfileIn, authorization: Optional[str] = Header(None)):
    user = current_user(authorization)
    name = (body.display_name or "").strip() or None
    if name and len(name) > DISPLAY_NAME_MAX:
        raise ApiError("VALIDATION_ERROR", f"ชื่อยาวได้ไม่เกิน {DISPLAY_NAME_MAX} ตัวอักษร")
    return ok(db.set_display_name(user["user_id"], name))


@app.post("/api/v1/me/password")
def change_password(body: PasswordIn, authorization: Optional[str] = Header(None)):
    user = current_user(authorization)
    # จำกัดเหมือน login กันเดารหัสเดิม
    rate_limit(f"password:{user['user_id']}", *LOGIN_LIMIT)
    if not auth.check_password(body.current_password, db.get_password_hash(user["user_id"])):
        raise ApiError("VALIDATION_ERROR", "รหัสผ่านเดิมไม่ถูกต้อง")
    if len(body.new_password.encode()) > 72:
        raise ApiError("VALIDATION_ERROR", "รหัสผ่านยาวเกินไป")
    db.set_password_hash(user["user_id"], auth.hash_password(body.new_password))
    return ok({"changed": True})


# ---------- trips ----------

@app.get("/api/v1/trips")
def list_trips(authorization: Optional[str] = Header(None)):
    return ok(db.list_trips(current_user(authorization)["user_id"]))


@app.get("/api/v1/trips/upcoming")
def upcoming_trip(authorization: Optional[str] = Header(None)):
    return ok(db.upcoming_trip(current_user(authorization)["user_id"]))


@app.post("/api/v1/trips")
def create_trip(body: TripCreate, authorization: Optional[str] = Header(None)):
    user = current_user(authorization)
    check_time(body.departure_time)
    if len(body.waypoints) > MAX_WAYPOINTS:
        raise ApiError("VALIDATION_ERROR", f"หมุดระหว่างทางได้ไม่เกิน {MAX_WAYPOINTS} จุด")
    check_places([body.origin, body.destination, *body.waypoints])
    check_not_same_place(body.origin, body.destination, body.waypoints)
    return ok(db.create_trip(user["user_id"], body.origin.model_dump(), body.destination.model_dump(),
                             body.departure_time, [w.model_dump() for w in body.waypoints]))


@app.get("/api/v1/trips/{trip_id}")
def get_trip(trip_id: str, authorization: Optional[str] = Header(None)):
    return ok(get_owned_trip(trip_id, current_user(authorization)))


@app.patch("/api/v1/trips/{trip_id}")
def patch_trip(trip_id: str, body: TripPatch, authorization: Optional[str] = Header(None)):
    trip = get_owned_trip(trip_id, current_user(authorization))
    if body.departure_time is not None:
        check_time(body.departure_time)
    if body.waypoints is not None and len(body.waypoints) > MAX_WAYPOINTS:
        raise ApiError("VALIDATION_ERROR", f"หมุดระหว่างทางได้ไม่เกิน {MAX_WAYPOINTS} จุด")
    check_places([p for p in (body.origin, body.destination) if p] + (body.waypoints or []))
    check_not_same_place(body.origin or Place(**trip["origin"]), body.destination or Place(**trip["destination"]),
                         body.waypoints if body.waypoints is not None else [Place(**w) for w in trip["waypoints"]])
    return ok(db.update_trip(
        trip_id,
        origin=body.origin.model_dump() if body.origin else None,
        destination=body.destination.model_dump() if body.destination else None,
        departure_time=body.departure_time,
        waypoints=[w.model_dump() for w in body.waypoints] if body.waypoints is not None else None,
    ))


@app.delete("/api/v1/trips/{trip_id}")
def delete_trip(trip_id: str, authorization: Optional[str] = Header(None)):
    get_owned_trip(trip_id, current_user(authorization))
    db.delete_trip(trip_id)
    return ok({"trip_id": trip_id, "deleted": True})


@app.post("/api/v1/trips/{trip_id}/plan")
def plan_trip(trip_id: str, authorization: Optional[str] = Header(None)):
    trip = get_owned_trip(trip_id, current_user(authorization))
    routes = call("ROUTING_ENGINE_URL", "POST", "/api/v1/routes/plan", timeout=ROUTING_TIMEOUT, json={
        "origin": trip["origin"],
        "destination": trip["destination"],
        "waypoints": trip["waypoints"],
        "departure_time": trip["departure_time"],
    })
    plan = {"trip_id": trip["trip_id"], "trip_no": trip["trip_no"], **routes}
    db.save_plan(trip_id, plan)
    return ok(plan)


@app.get("/api/v1/trips/{trip_id}/departures")
def trip_departures(trip_id: str, authorization: Optional[str] = Header(None)):
    """ถ้าเลื่อนเวลาออกไป +3 / +6 ชม. ความเสี่ยงเป็นเท่าไร (การ์ด "ออกเวลาไหนดี" ในหน้าทริป)
    ไม่บันทึกอะไร เส้นที่ถามไม่ได้ก็ข้ามไป"""
    trip = get_owned_trip(trip_id, current_user(authorization))
    start = datetime.fromisoformat(trip["departure_time"].replace("Z", "+00:00"))

    def ask(hours: int) -> Optional[dict]:
        at = (start + timedelta(hours=hours)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            d = call("ROUTING_ENGINE_URL", "POST", "/api/v1/routes/plan", timeout=ROUTING_TIMEOUT, json={
                "origin": trip["origin"], "destination": trip["destination"],
                "waypoints": trip["waypoints"], "departure_time": at})
        except ApiError:
            return None
        return {"offset_h": hours, "risk_level": d.get("risk_level"), "risk_score": d.get("risk_score"),
                "recommendation": d.get("recommendation")}

    with ThreadPoolExecutor(max_workers=len(DEPARTURE_OFFSETS_H)) as pool:
        found = list(pool.map(ask, DEPARTURE_OFFSETS_H))
    return ok({"departures": [d for d in found if d]})


# ---------- weather / hazards ----------

@app.get("/api/v1/weather/area")
def weather_area(lat: float, lng: float, authorization: Optional[str] = Header(None)):
    current_user(authorization)
    # เช็คก่อนเรียก ไม่งั้น except ApiError ข้างล่างจะกลืน OUT_OF_THAILAND เป็น WEATHER_UNAVAILABLE
    if not in_thailand(lat, lng):
        raise ApiError("OUT_OF_THAILAND", "ตอนนี้รองรับเฉพาะสถานที่ในประเทศไทย")
    try:
        return ok(call("WEATHER_DISASTER_URL", "GET", "/api/v1/area", timeout=WEATHER_TIMEOUT,
                       params={"lat": lat, "lng": lng}))
    except ApiError:
        # ข้อมูลไม่ครบไม่ใช่ error หน้าเว็บยังแสดงแผนที่ได้ (CONTRACT หัวข้อ 3)
        return ok({"center": {"lat": lat, "lng": lng}, "cells": [], "updated_at": None,
                   "warnings": ["WEATHER_UNAVAILABLE"]})


@app.post("/api/v1/forecast/route")
def route_forecast(body: RouteForecastIn, authorization: Optional[str] = Header(None)):
    """ฝนตามเส้นทาง ณ เวลาที่รถผ่าน: เก็บจุดทุก ROUTE_FORECAST_STEP_KM ตามเส้น
    เวลาที่ผ่าน = เวลาออก + เวลาเดินทาง x สัดส่วนระยะ (ปัดลงเป็นต้นชั่วโมงเพราะพยากรณ์รายชั่วโมง)"""
    current_user(authorization)
    # ทริปที่กำลังเดินทางอยู่ก็ดูฝนตามเส้นทางได้ เช็กแค่ timezone (ไม่ใช้ check_time ที่ห้ามเวลาในอดีต)
    if body.departure_time.tzinfo is None:
        raise ApiError("VALIDATION_ERROR", "departure_time ต้องมี timezone เช่น 2026-09-28T01:00:00Z")
    pts = [p.model_dump() for p in body.geometry]
    acc = [0.0]
    for a, b in zip(pts, pts[1:]):
        acc.append(acc[-1] + haversine_km(a, b))
    total = acc[-1] or 1.0
    start = body.departure_time.astimezone(timezone.utc)
    samples, i, d = [], 0, 0.0
    while d <= total:
        while i < len(acc) - 1 and acc[i + 1] < d:
            i += 1
        at = (start + timedelta(minutes=body.duration_min * d / total)).replace(minute=0, second=0, microsecond=0)
        samples.append({"lat": pts[i]["lat"], "lng": pts[i]["lng"], "time": at.strftime("%Y-%m-%dT%H:%M:%SZ")})
        d += ROUTE_FORECAST_STEP_KM
    return ok(call("WEATHER_DISASTER_URL", "POST", "/api/v1/forecast/points", timeout=WEATHER_TIMEOUT * 2,
                   json={"points": samples}))


@app.get("/api/v1/hazards")
def hazards(min_lat: float, min_lng: float, max_lat: float, max_lng: float, authorization: Optional[str] = Header(None)):
    current_user(authorization)
    # เช็คก่อนเรียก ไม่งั้น except ข้างล่างจะกลืน VALIDATION_ERROR เป็น HAZARD_FEED_UNAVAILABLE
    if min_lat > max_lat or min_lng > max_lng:
        raise ApiError("VALIDATION_ERROR", "กรอบพิกัดไม่ถูกต้อง ค่า min ต้องไม่มากกว่า max")
    try:
        return ok(call("WEATHER_DISASTER_URL", "GET", "/api/v1/hazards", timeout=WEATHER_TIMEOUT,
                       params={"min_lat": min_lat, "min_lng": min_lng, "max_lat": max_lat, "max_lng": max_lng}))
    except ApiError:
        return ok({"hazards": [], "warnings": ["HAZARD_FEED_UNAVAILABLE"]})


# ---------- safety ----------

@app.get("/api/v1/safety/emergency")
def safety_emergency(hazard_type: str, authorization: Optional[str] = Header(None)):
    current_user(authorization)
    return ok(call("SAFETY_KNOWLEDGE_URL", "GET", "/api/v1/safety/emergency", timeout=SAFETY_TIMEOUT,
                   params={"hazard_type": hazard_type}))


# ---------- assistant ----------

@app.post("/api/v1/assistant/chat")
def assistant_chat(body: ChatIn, authorization: Optional[str] = Header(None)):
    user = current_user(authorization)
    rate_limit(f"chat:{user['user_id']}", *CHAT_LIMIT)
    # ส่ง token ของผู้ใช้ไปด้วย assistant-agent ต้องใช้เรียกกลับมาแก้ทริป (CONTRACT หัวข้อ 5)
    # ส่งชื่อที่ผู้ใช้ตั้งไว้ไปด้วย น้องกิเลนจะได้เรียกชื่อถูก
    return ok(call("ASSISTANT_AGENT_URL", "POST", "/api/v1/chat", timeout=ASSISTANT_TIMEOUT,
                   json={**body.model_dump(), "user_name": user["display_name"]}, headers={"Authorization": authorization}))


# ---------- places ----------

@app.get("/api/v1/places/search")
def places_search(q: str = "", authorization: Optional[str] = Header(None)):
    current_user(authorization)
    return ok({"places": places.search(q)})


@app.get("/api/v1/places/nearby")
def places_nearby(lat: float, lng: float, radius_km: float = places.NEARBY_RADIUS_KM, kinds: str = "attraction",
                  authorization: Optional[str] = Header(None)):
    current_user(authorization)
    # kinds=cafe,market,... radius_km ไม่เกิน 20 ไม่ส่ง = แบบเดิมตาม CONTRACT
    return ok({"places": places.nearby(lat, lng, radius_km, tuple(k.strip() for k in kinds.split(",") if k.strip()))})


# ---------- ทดลอง: ชั้นพื้นที่น้ำท่วมจากดาวเทียม GISTDA ----------
# ส่งต่อภาพแผนที่ของ GISTDA key อยู่ฝั่ง server เท่านั้น ไม่ต้อง login (เป็นข้อมูลเปิดภาครัฐ และ Leaflet ส่ง header ไม่ได้)

import os
import httpx

FLOOD_TMS = "https://api-gateway.gistda.or.th/api/2.0/resources/maps/flood/{window}/tms/{z}/{x}/{y}"
FLOOD_WINDOWS = {"1day", "3days", "7days", "30days"}
_tile_cache: dict[tuple, tuple[float, bytes]] = {}


@app.get("/api/v1/maps/flood/{window}/{z}/{x}/{y}")
def flood_tile(window: str, z: int, x: int, y: int):
    key = os.getenv("GISTDA_API_KEY")
    if not key or window not in FLOOD_WINDOWS or not 0 <= z <= 18:
        raise ApiError("NOT_FOUND", "ไม่มีชั้นข้อมูลนี้")
    now = datetime.now().timestamp()
    hit = _tile_cache.get((window, z, x, y))
    if hit and now - hit[0] < 1800:
        body = hit[1]
    else:
        try:
            res = httpx.get(FLOOD_TMS.format(window=window, z=z, x=x, y=y), headers={"API-Key": key}, timeout=8)
            res.raise_for_status()
        except httpx.TimeoutException:
            raise ApiError("UPSTREAM_TIMEOUT", "ภาพแผนที่น้ำท่วมโหลดไม่ทัน")
        except httpx.HTTPError:
            raise ApiError("UPSTREAM_ERROR", "โหลดภาพแผนที่น้ำท่วมไม่ได้")
        body = res.content
        if len(_tile_cache) > 5000:
            _tile_cache.clear()
        _tile_cache[(window, z, x, y)] = (now, body)
    return Response(content=body, media_type="image/png", headers={"Cache-Control": "public, max-age=1800"})
