"""รหัสผ่านและ JWT"""
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from envelope import ApiError

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _expires_in() -> timedelta:
    """อ่าน JWT_EXPIRES_IN แบบ 7d, 12h, 30m, 90s หรือตัวเลขเปล่าเป็นวินาที"""
    # ค่าว่างใน .env (JWT_EXPIRES_IN=) ให้ใช้ค่าตั้งต้น ไม่งั้น raw[-1] พัง
    raw = (os.getenv("JWT_EXPIRES_IN") or "").strip() or "7d"
    if raw[-1] in _UNITS:
        return timedelta(seconds=int(raw[:-1]) * _UNITS[raw[-1]])
    return timedelta(seconds=int(raw))


def _secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise ApiError("INTERNAL_ERROR", "ยังไม่ได้ตั้งค่า JWT_SECRET ใน .env")
    return secret


# bcrypt ค่าเริ่มต้น 12 ใช้ CPU ราว 300 ms ต่อครั้ง เครื่อง 1 CPU บน Render มีคน login พร้อมกัน 20 คนรอกัน 6 วิ
# 10 เร็วขึ้น 4 เท่าและยังเดายากพอสำหรับเว็บนี้ hash เดิมที่เป็น 12 ยังตรวจได้ และ login ครั้งถัดไปจะเปลี่ยนเป็น 10 ให้
BCRYPT_ROUNDS = 10


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()


def needs_rehash(password_hash: str) -> bool:
    """รูปแบบ $2b$12$... ตัวเลขคือ rounds"""
    return password_hash.split("$")[2] != f"{BCRYPT_ROUNDS:02d}"


def check_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def make_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": user_id, "iat": now, "exp": now + _expires_in()}, _secret(), algorithm="HS256")


def read_token(token: str) -> str:
    """คืน user_id ถ้า token ถูกต้องและยังไม่หมดอายุ"""
    try:
        payload = jwt.decode(token, _secret(), algorithms=["HS256"], options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError:
        raise ApiError("UNAUTHORIZED", "เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่")
    except jwt.InvalidTokenError:
        raise ApiError("UNAUTHORIZED", "กรุณาเข้าสู่ระบบก่อน")
    return payload["sub"]
