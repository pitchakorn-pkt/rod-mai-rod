"""weather-disaster (stub)

ตอนนี้ตอบข้อมูลตัวอย่าง ให้คนอื่นต่อได้ก่อน
ของจริง: Open-Meteo (พยากรณ์), GDACS + USGS (ภัยพิบัติ), Thaiwater / TMD (ถ้าได้ key)
แปลงหน่วยให้ตรง docs/CONTRACT.md หัวข้อ 4 และ cache ทุกคำขอ
DEMO_MODE=true ต้องตอบจากข้อมูลที่บันทึกไว้ ไม่เรียกเน็ตเลย
"""
import os
import threading
from datetime import datetime, timezone

from fastapi import FastAPI
from pydantic import BaseModel

import doh
import gistda
import hazard_feeds
import weather
from envelope import ApiError, ok, setup
from geo import to_iso

app = FastAPI(title="weather-disaster")
setup(app, "weather-disaster")

DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"


@app.on_event("startup")
def warm_hazards():
    # HAZARD_WARMUP=false turns it off; tests do, so no thread touches the network
    if os.getenv("HAZARD_WARMUP", "true").lower() == "true":
        threading.Thread(target=hazard_feeds.keep_warm, daemon=True).start()
    if not DEMO_MODE and gistda.enabled():
        threading.Thread(target=gistda.keep_fresh, daemon=True).start()
    # ถนนปิด/น้ำท่วมทางหลวงจากกรมทางหลวง ใช้สวิตช์เดียวกับ warm-up (เทสต์ปิดไว้ ไม่ให้ยิงเน็ตจริง)
    if not DEMO_MODE and doh.enabled() and os.getenv("HAZARD_WARMUP", "true").lower() == "true":
        threading.Thread(target=doh.keep_fresh, daemon=True).start()


class TimedPoint(BaseModel):
    lat: float
    lng: float
    time: datetime


class PointsIn(BaseModel):
    points: list[TimedPoint]


@app.post("/api/v1/forecast/points")
def forecast_points(body: PointsIn):
    for p in body.points:
        if p.time.tzinfo is None:
            raise ApiError("VALIDATION_ERROR", "time ต้องมี timezone")
    forecasts, warnings = weather.forecast_points([(p.lat, p.lng, p.time) for p in body.points])
    out = [{"lat": p.lat, "lng": p.lng, "forecast": fc} for p, fc in zip(body.points, forecasts)]
    return ok({"points": out, "warnings": warnings})


@app.get("/api/v1/area")
def area(lat: float, lng: float):
    now = datetime.now(timezone.utc)
    grid = weather.area_grid(lat, lng)
    forecasts, warnings = weather.forecast_points([(g_lat, g_lng, now) for g_lat, g_lng in grid])
    # the web reads cell.forecast directly, so cells without data are left out
    cells = [
        {"lat": g_lat, "lng": g_lng, "forecast": fc}
        for (g_lat, g_lng), fc in zip(grid, forecasts) if fc is not None
    ]
    return ok({"center": {"lat": lat, "lng": lng}, "cells": cells, "updated_at": to_iso(now), "warnings": warnings})


@app.get("/api/v1/hazards")
def hazards(min_lat: float, min_lng: float, max_lat: float, max_lng: float):
    if min_lat > max_lat or min_lng > max_lng:
        raise ApiError("VALIDATION_ERROR", "กรอบพิกัดไม่ถูกต้อง ค่า min ต้องไม่มากกว่า max")
    found, warnings = hazard_feeds.get_hazards((min_lat, min_lng, max_lat, max_lng))
    data = {"hazards": found, "warnings": warnings}
    if gistda.enabled():
        # ชุดน้ำท่วม GISTDA ที่ใช้อยู่ หน้าเว็บใช้ชั้นภาพชุดเดียวกัน
        data["flood_window"] = gistda.window()
    return ok(data)
