"""รหัสผ่าน, JWT และ login ด้วย Google"""
import os
import secrets
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


# ---------- login ด้วย Google ----------
# หน้าเว็บได้ ID token (JWT ที่ Google เซ็น) จากปุ่ม Sign in with Google แล้วส่งมาให้ตรวจ
# ตรวจลายเซ็นด้วยกุญแจสาธารณะของ Google + ต้องออกให้ client ของเรา + อีเมลยืนยันแล้ว
GOOGLE_CERTS = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
_google_keys: "jwt.PyJWKClient | None" = None


def google_client_id() -> str:
    """ค่าว่าง = ปิด login ด้วย Google (หน้าเว็บไม่แสดงปุ่ม)"""
    return (os.getenv("GOOGLE_CLIENT_ID") or "").strip()


def _google_signing_key(credential: str):
    global _google_keys
    if _google_keys is None:
        _google_keys = jwt.PyJWKClient(GOOGLE_CERTS, cache_keys=True, timeout=10)  # เก็บกุญแจไว้ ไม่ดึงทุกครั้ง
    return _google_keys.get_signing_key_from_jwt(credential).key


def read_google_token(credential: str) -> dict:
    """คืน {email, name} ถ้า token ถูกต้อง"""
    client_id = google_client_id()
    if not client_id:
        raise ApiError("VALIDATION_ERROR", "ระบบนี้ยังไม่เปิดให้เข้าสู่ระบบด้วย Google")
    try:
        key = _google_signing_key(credential)
        payload = jwt.decode(credential, key, algorithms=["RS256"], audience=client_id,
                             options={"require": ["exp", "iss", "aud", "email"]})
    except jwt.PyJWKClientConnectionError:
        raise ApiError("UPSTREAM_ERROR", "เชื่อมต่อ Google ไม่ได้ ลองใหม่อีกครั้ง")
    except (jwt.InvalidTokenError, jwt.PyJWKClientError):
        raise ApiError("UNAUTHORIZED", "ยืนยันบัญชี Google ไม่สำเร็จ ลองใหม่อีกครั้ง")
    if payload["iss"] not in GOOGLE_ISSUERS or payload.get("email_verified") is not True:
        raise ApiError("UNAUTHORIZED", "ยืนยันบัญชี Google ไม่สำเร็จ ลองใหม่อีกครั้ง")
    return {"email": payload["email"], "name": (payload.get("name") or "").strip() or None}


def unusable_password_hash() -> str:
    """บัญชีที่สร้างจาก Google ไม่มีรหัสผ่าน ใส่ hash ของค่าสุ่มที่ไม่มีใครรู้ (ตาราง users บังคับว่าต้องมี)"""
    return hash_password(secrets.token_urlsafe(32))
