"""การเชื่อมต่อ Postgres และสร้างตารางตอนเริ่ม"""
import os
from typing import Optional

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout

from geo import to_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email         text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);
-- ชื่อที่ผู้ใช้ตั้งเอง (น้องกิเลนเรียกชื่อนี้) ฐานข้อมูลเก่าไม่มีคอลัมน์นี้ เพิ่มให้ตอนเปิด
ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name text;

CREATE TABLE IF NOT EXISTS trips (
    trip_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    trip_no        int NOT NULL,
    origin         jsonb NOT NULL,
    destination    jsonb NOT NULL,
    departure_time timestamptz NOT NULL,
    waypoints      jsonb NOT NULL DEFAULT '[]',
    plan_status    text NOT NULL DEFAULT 'NONE' CHECK (plan_status IN ('NONE', 'FRESH', 'STALE')),
    plan           jsonb,
    UNIQUE (user_id, trip_no)
);
"""

_pool: Optional[ConnectionPool] = None


def init_db(timeout: float = 10) -> None:
    """ต่อฐานข้อมูลแล้วสร้างตาราง ต่อไม่ได้ภายใน timeout ให้ raise เพื่อให้ process จบ"""
    global _pool
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("ยังไม่ได้ตั้งค่า DATABASE_URL ใน .env")
    # timeout=5: ฐานข้อมูลล่มระหว่างทำงาน request จะได้ error ใน 5 วิ ไม่ค้าง 30 วิ
    _pool = ConnectionPool(url, min_size=1, max_size=10, open=False, timeout=5,
                           kwargs={"connect_timeout": 3, "row_factory": dict_row})
    try:
        # pool ลองต่อซ้ำเองจนได้หรือครบ timeout
        _pool.open(wait=True, timeout=timeout)
    except PoolTimeout:
        _pool.close()
        raise RuntimeError(f"ต่อฐานข้อมูลไม่ได้ภายใน {timeout} วินาที")
    with _pool.connection() as conn:
        conn.execute(SCHEMA)


def close_db() -> None:
    if _pool is not None:
        _pool.close()


def connection():
    """ใช้แบบ `with db.connection() as conn:` ออกจาก with แล้ว commit ให้เอง ถ้า error จะ rollback"""
    return _pool.connection()


def ping() -> None:
    """raise ถ้าฐานข้อมูลใช้ไม่ได้ /health ใช้ ต้องตอบทันก่อน healthcheck ของ Docker (5 วิ)"""
    with _pool.connection(timeout=2) as conn:
        conn.execute("SELECT 1")


def create_user(email: str, password_hash: str) -> Optional[dict]:
    """คืน None ถ้าอีเมลนี้มีอยู่แล้ว"""
    with connection() as conn:
        return conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s) "
            "ON CONFLICT (email) DO NOTHING RETURNING user_id::text AS user_id, email, display_name",
            (email, password_hash),
        ).fetchone()


def find_user_by_email(email: str) -> Optional[dict]:
    """มี password_hash ติดมาด้วย ใช้ตอน login เท่านั้น ห้าม return ออกไปตรงๆ"""
    with connection() as conn:
        return conn.execute(
            "SELECT user_id::text AS user_id, email, display_name, password_hash FROM users WHERE email = %s",
            (email,),
        ).fetchone()


def set_display_name(user_id: str, display_name: Optional[str]) -> dict:
    with connection() as conn:
        return conn.execute(
            "UPDATE users SET display_name = %s WHERE user_id = %s "
            "RETURNING user_id::text AS user_id, email, display_name",
            (display_name, user_id),
        ).fetchone()


def get_password_hash(user_id: str) -> str:
    with connection() as conn:
        return conn.execute("SELECT password_hash FROM users WHERE user_id = %s", (user_id,)).fetchone()["password_hash"]


def set_password_hash(user_id: str, password_hash: str) -> None:
    with connection() as conn:
        conn.execute("UPDATE users SET password_hash = %s WHERE user_id = %s", (password_hash, user_id))


def find_user(user_id: str) -> Optional[dict]:
    with connection() as conn:
        return conn.execute(
            "SELECT user_id::text AS user_id, email, display_name FROM users WHERE user_id = %s",
            (user_id,),
        ).fetchone()


# ---------- trips ----------

# ลำดับคอลัมน์ = ลำดับ key ใน response ต้องเหมือนตอนเป็น stub
TRIP_COLUMNS = ("trip_id::text AS trip_id, trip_no, user_id::text AS user_id, origin, destination, "
                "departure_time, waypoints, plan_status, plan")


def _trip(row: Optional[dict]) -> Optional[dict]:
    if row is not None:
        row["departure_time"] = to_iso(row["departure_time"])
    return row


def _json(value):
    return None if value is None else Jsonb(value)


def list_trips(user_id: str) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            f"SELECT {TRIP_COLUMNS} FROM trips WHERE user_id = %s ORDER BY departure_time, trip_no",
            (user_id,),
        ).fetchall()
    return [_trip(r) for r in rows]


def upcoming_trip(user_id: str) -> Optional[dict]:
    with connection() as conn:
        return _trip(conn.execute(
            f"SELECT {TRIP_COLUMNS} FROM trips WHERE user_id = %s AND departure_time >= now() "
            "ORDER BY departure_time LIMIT 1",
            (user_id,),
        ).fetchone())


def create_trip(user_id: str, origin: dict, destination: dict, departure_time, waypoints: list) -> dict:
    with connection() as conn:
        # ล็อกแถวผู้ใช้ไว้ก่อน สร้างทริปพร้อมกันสองอันจะได้ไม่ได้ trip_no ซ้ำ
        conn.execute("SELECT 1 FROM users WHERE user_id = %s FOR UPDATE", (user_id,))
        return _trip(conn.execute(
            "INSERT INTO trips (user_id, trip_no, origin, destination, departure_time, waypoints) "
            "VALUES (%(user_id)s, (SELECT COALESCE(MAX(trip_no), 0) + 1 FROM trips WHERE user_id = %(user_id)s), "
            "%(origin)s, %(destination)s, %(departure_time)s, %(waypoints)s) "
            f"RETURNING {TRIP_COLUMNS}",
            {"user_id": user_id, "origin": Jsonb(origin), "destination": Jsonb(destination),
             "departure_time": departure_time, "waypoints": Jsonb(waypoints)},
        ).fetchone())


def get_trip(trip_id: str) -> Optional[dict]:
    with connection() as conn:
        return _trip(conn.execute(
            f"SELECT {TRIP_COLUMNS} FROM trips WHERE trip_id = %s", (trip_id,),
        ).fetchone())


def update_trip(trip_id: str, origin=None, destination=None, departure_time=None, waypoints=None) -> dict:
    """ค่าที่เป็น None คือไม่แก้ ถ้าเคยแพลนแล้ว plan_status จะเป็น STALE"""
    with connection() as conn:
        return _trip(conn.execute(
            "UPDATE trips SET origin = COALESCE(%s, origin), destination = COALESCE(%s, destination), "
            "departure_time = COALESCE(%s, departure_time), waypoints = COALESCE(%s, waypoints), "
            "plan_status = CASE WHEN plan IS NULL THEN plan_status ELSE 'STALE' END "
            f"WHERE trip_id = %s RETURNING {TRIP_COLUMNS}",
            (_json(origin), _json(destination), departure_time, _json(waypoints), trip_id),
        ).fetchone())


def delete_trip(trip_id: str) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM trips WHERE trip_id = %s", (trip_id,))


def save_plan(trip_id: str, plan: dict) -> None:
    with connection() as conn:
        conn.execute("UPDATE trips SET plan = %s, plan_status = 'FRESH' WHERE trip_id = %s",
                     (Jsonb(plan), trip_id))
