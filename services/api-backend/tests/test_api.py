import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import psycopg
from fastapi.testclient import TestClient

import auth
from app import app

# ไม่รัน lifespan ใช้กับเทสต์ที่ไม่ต้องแตะฐานข้อมูล
bare = TestClient(app)
TRIP = {
    "origin": {"lat": 13.7563, "lng": 100.5018},
    "destination": {"lat": 18.7883, "lng": 98.9853},
    "departure_time": "2030-01-01T01:00:00Z",
}


def test_no_token_is_unauthorized():
    res = bare.get("/api/v1/trips")
    assert res.status_code == 401
    assert res.json() == {"data": None, "error": {"code": "UNAUTHORIZED", "message": res.json()["error"]["message"]}}


def test_request_id_is_echoed():
    res = bare.get("/health", headers={"X-Request-ID": "abc-123"})
    assert res.headers["X-Request-ID"] == "abc-123"


def test_time_without_timezone_is_rejected(client, auth_header):
    res = client.post("/api/v1/trips", headers=auth_header, json={**TRIP, "departure_time": "2030-01-01T08:00"})
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_outside_thailand_is_rejected(client, auth_header):
    res = client.post("/api/v1/trips", headers=auth_header, json={**TRIP, "origin": {"lat": 35.68, "lng": 139.76}})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "OUT_OF_THAILAND"


def test_upcoming_is_not_treated_as_trip_id(client, auth_header):
    res = client.get("/api/v1/trips/upcoming", headers=auth_header)
    assert res.json()["error"] is None


def test_routing_down_is_upstream_error_not_crash(client, auth_header, monkeypatch):
    monkeypatch.setenv("ROUTING_ENGINE_URL", "http://127.0.0.1:9")
    trip_id = client.post("/api/v1/trips", headers=auth_header, json=TRIP).json()["data"]["trip_id"]
    res = client.post(f"/api/v1/trips/{trip_id}/plan", headers=auth_header)
    assert res.status_code == 502
    assert res.json()["error"]["code"] == "UPSTREAM_ERROR"


# ---------- auth ----------

def test_register_then_login_without_password_hash(client):
    email = f"user-{uuid.uuid4()}@example.com"
    reg = client.post("/api/v1/auth/register", json={"email": email, "password": "secret123"})
    assert reg.json()["error"] is None
    assert "password_hash" not in reg.text
    res = client.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
    assert res.json()["data"]["user"] == reg.json()["data"]
    assert "password_hash" not in res.text
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {res.json()['data']['token']}"})
    assert me.json()["data"] == reg.json()["data"]


def test_old_slow_hash_still_logs_in_and_is_upgraded(client):
    import bcrypt
    import db
    email = f"old-{uuid.uuid4()}@example.com"
    db.create_user(email, bcrypt.hashpw(b"secret123", bcrypt.gensalt(12)).decode())
    res = client.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
    assert res.json()["error"] is None
    assert db.find_user_by_email(email)["password_hash"].startswith("$2b$10$")
    again = client.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
    assert again.json()["error"] is None


def test_duplicate_email_is_validation_error(client):
    res = client.post("/api/v1/auth/register", json={"email": "demo@example.com", "password": "whatever1"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_wrong_password_is_unauthorized(client):
    res = client.post("/api/v1/auth/login", json={"email": "demo@example.com", "password": "wrong-pass"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


def test_fake_token_is_unauthorized(client):
    res = client.get("/api/v1/me", headers={"Authorization": "Bearer dev-token"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


# ---------- trips ----------

def new_user_header(client) -> dict:
    return new_user(client)[1]


def test_trip_shape_is_unchanged_and_stored(client, auth_header):
    created = client.post("/api/v1/trips", headers=auth_header,
                          json={**TRIP, "departure_time": "2030-01-01T08:00:00+07:00"}).json()["data"]
    assert list(created) == ["trip_id", "trip_no", "user_id", "origin", "destination",
                             "departure_time", "waypoints", "plan_status", "plan"]
    assert created["departure_time"] == "2030-01-01T01:00:00Z"
    assert created["plan_status"] == "NONE" and created["plan"] is None
    got = client.get(f"/api/v1/trips/{created['trip_id']}", headers=auth_header).json()["data"]
    assert got == created


def test_other_user_gets_forbidden(client, auth_header):
    trip_id = client.post("/api/v1/trips", headers=auth_header, json=TRIP).json()["data"]["trip_id"]
    other = new_user_header(client)
    url = f"/api/v1/trips/{trip_id}"
    for res in (client.get(url, headers=other),
                client.patch(url, headers=other, json={"departure_time": "2030-01-02T06:00:00Z"}),
                client.delete(url, headers=other),
                client.post(f"{url}/plan", headers=other)):
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN"
    # ทริปของเจ้าของต้องไม่ถูกแก้หรือลบ
    mine = client.get(url, headers=auth_header).json()["data"]
    assert mine["departure_time"] == TRIP["departure_time"]


def test_unknown_trip_is_not_found(client, auth_header):
    for trip_id in (str(uuid.uuid4()), "not-a-uuid"):
        res = client.get(f"/api/v1/trips/{trip_id}", headers=auth_header)
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "NOT_FOUND"


def test_trip_no_is_counted_per_user(client):
    a, b = new_user_header(client), new_user_header(client)
    nos_a = [client.post("/api/v1/trips", headers=a, json=TRIP).json()["data"]["trip_no"] for _ in range(2)]
    no_b = client.post("/api/v1/trips", headers=b, json=TRIP).json()["data"]["trip_no"]
    assert nos_a == [1, 2]
    assert no_b == 1


def test_patch_after_plan_is_stale(client, auth_header, monkeypatch):
    # แทน routing-engine ด้วยคำตอบปลอม เทสต์นี้สนแค่ plan_status
    monkeypatch.setattr("app.call", lambda *args, **kwargs: {"route_options": [], "warnings": []})
    trip_id = client.post("/api/v1/trips", headers=auth_header, json=TRIP).json()["data"]["trip_id"]
    client.post(f"/api/v1/trips/{trip_id}/plan", headers=auth_header)
    assert client.get(f"/api/v1/trips/{trip_id}", headers=auth_header).json()["data"]["plan_status"] == "FRESH"
    res = client.patch(f"/api/v1/trips/{trip_id}", headers=auth_header, json={"departure_time": "2030-01-02T06:00:00Z"})
    assert res.json()["data"]["plan_status"] == "STALE"


# ---------- health / token ----------

class DeadPool:
    def connection(self, timeout=None):
        raise psycopg.OperationalError("database is down")


def test_health_ok_when_db_is_up(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "service": "api-backend"}


def test_health_is_503_when_db_is_down(monkeypatch):
    monkeypatch.setattr("db._pool", DeadPool())
    res = bare.get("/health")
    assert res.status_code == 503
    assert res.json()["status"] == "error"


def test_empty_jwt_expires_in_falls_back_to_7_days(monkeypatch):
    for value in ("", "  "):
        monkeypatch.setenv("JWT_EXPIRES_IN", value)
        assert auth._expires_in() == timedelta(days=7)


def test_expired_token_is_unauthorized(client):
    login = client.post("/api/v1/auth/login", json={"email": "demo@example.com", "password": "demo1234"})
    user_id = login.json()["data"]["user"]["user_id"]
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    token = jwt.encode({"sub": user_id, "exp": past}, os.environ["JWT_SECRET"], algorithm="HS256")
    res = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


# ---------- weather ----------

def test_weather_area_outside_thailand_is_rejected_without_calling_upstream(client, auth_header, monkeypatch):
    calls = []

    def fake_call(*args, **kwargs):
        calls.append(args)
        return {"center": {"lat": 13.75, "lng": 100.5}, "cells": [], "updated_at": None, "warnings": []}

    monkeypatch.setattr("app.call", fake_call)
    res = client.get("/api/v1/weather/area", params={"lat": 35.6, "lng": 139.7}, headers=auth_header)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "OUT_OF_THAILAND"
    assert calls == []
    res = client.get("/api/v1/weather/area", params={"lat": 13.75, "lng": 100.5}, headers=auth_header)
    assert res.status_code == 200
    assert len(calls) == 1


# ---------- โปรไฟล์: ชื่อและเปลี่ยนรหัสผ่าน ----------

def new_user(client, password="secret123"):
    """สมัครแล้ว login คืน (อีเมล, header)"""
    email = f"user-{uuid.uuid4()}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    token = client.post("/api/v1/auth/login", json={"email": email, "password": password}).json()["data"]["token"]
    return email, {"Authorization": f"Bearer {token}"}


def test_display_name_is_saved_trimmed_and_cleared(client):
    _, h = new_user(client)
    assert client.get("/api/v1/me", headers=h).json()["data"]["display_name"] is None
    res = client.patch("/api/v1/me", headers=h, json={"display_name": "  แพนด้า  "})
    assert res.json()["data"]["display_name"] == "แพนด้า"
    assert client.get("/api/v1/me", headers=h).json()["data"]["display_name"] == "แพนด้า"
    assert client.patch("/api/v1/me", headers=h, json={"display_name": "   "}).json()["data"]["display_name"] is None


def test_display_name_too_long_is_validation_error(client):
    _, h = new_user(client)
    res = client.patch("/api/v1/me", headers=h, json={"display_name": "ก" * 41})
    assert res.status_code == 400 and res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_change_password_needs_the_current_one(client):
    email, h = new_user(client)
    wrong = client.post("/api/v1/me/password", headers=h, json={"current_password": "nope12345", "new_password": "newpass99"})
    assert wrong.status_code == 400 and wrong.json()["error"]["message"] == "รหัสผ่านเดิมไม่ถูกต้อง"
    good = client.post("/api/v1/me/password", headers=h, json={"current_password": "secret123", "new_password": "newpass99"})
    assert good.json()["data"] == {"changed": True}
    assert client.post("/api/v1/auth/login", json={"email": email, "password": "secret123"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": email, "password": "newpass99"}).json()["error"] is None


def test_chat_sends_display_name_to_the_agent(client, monkeypatch):
    import app as appmod
    sent = {}
    monkeypatch.setattr(appmod, "call", lambda *a, **k: sent.update(k) or {"reply": "ok", "actions": []})
    _, h = new_user(client)
    client.patch("/api/v1/me", headers=h, json={"display_name": "แพนด้า"})
    client.post("/api/v1/assistant/chat", headers=h, json={"message": "ฉันชื่ออะไร"})
    assert sent["json"]["user_name"] == "แพนด้า"


def test_chat_passes_gps_location_to_the_agent(client, monkeypatch):
    import app as appmod
    sent = {}
    monkeypatch.setattr(appmod, "call", lambda *a, **k: sent.update(k) or {"reply": "ok", "actions": []})
    _, h = new_user(client)
    client.post("/api/v1/assistant/chat", headers=h, json={"message": "ไปเชียงใหม่", "location": {"lat": 14.03, "lng": 100.72}})
    assert sent["json"]["location"] == {"lat": 14.03, "lng": 100.72, "name": None}
    client.post("/api/v1/assistant/chat", headers=h, json={"message": "ไปเชียงใหม่"})
    assert sent["json"]["location"] is None
