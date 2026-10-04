"""รูปแบบคำตอบกลางตาม docs/CONTRACT.md หัวข้อ 3

ทุก service มีสำเนาไฟล์นี้ของตัวเอง แก้ของตัวเองได้ แต่พฤติกรรม 4 อย่างนี้ต้องคงไว้:
  1. GET /health
  2. X-Request-ID รับต่อหรือสร้างใหม่ แล้วส่งกลับใน header ของ response
  3. ทุก error ออกมาเป็น {"data": null, "error": {"code", "message"}} รวมถึง error จากการ validate ของ FastAPI
  4. log เป็น JSON บรรทัดละ request และมี request_id

เรียก service อื่นด้วย call() เท่านั้น มันตั้ง timeout, ส่ง X-Request-ID ต่อ และแปลง error ให้ตาม CONTRACT ให้แล้ว
"""
import json
import logging
import os
import uuid
from contextvars import ContextVar

import httpx

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

ERROR_STATUS = {
    "VALIDATION_ERROR": 400,
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "OUT_OF_THAILAND": 422,
    "RATE_LIMITED": 429,
    "UPSTREAM_ERROR": 502,
    "UPSTREAM_TIMEOUT": 504,
    "INTERNAL_ERROR": 500,
}

_HTTP_TO_CODE = {
    400: "VALIDATION_ERROR",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "NOT_FOUND",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    502: "UPSTREAM_ERROR",
    504: "UPSTREAM_TIMEOUT",
}


_request_id: ContextVar[str] = ContextVar("request_id", default="")


class ApiError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def ok(data):
    return {"data": data, "error": None}


def _fail(code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=ERROR_STATUS.get(code, 500),
        content={"data": None, "error": {"code": code, "message": message}},
    )


def setup(app: FastAPI, service_name: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger(service_name)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = rid
        _request_id.set(rid)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        logger.info(json.dumps({
            "service": service_name,
            "request_id": rid,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
        }, ensure_ascii=False))
        return response

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError):
        return _fail(exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError):
        fields = ", ".join(".".join(str(p) for p in e["loc"][1:]) for e in exc.errors())
        return _fail("VALIDATION_ERROR", f"ข้อมูลไม่ครบหรือผิดรูปแบบ: {fields}")

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, exc: StarletteHTTPException):
        return _fail(_HTTP_TO_CODE.get(exc.status_code, "INTERNAL_ERROR"), str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):
        logger.exception("unhandled error")
        return _fail("INTERNAL_ERROR", "เกิดข้อผิดพลาดภายในระบบ")

    @app.get("/health")
    def health():
        return {"status": "ok", "service": service_name}


# client ตัวเดียวใช้ร่วมกันทุกคำขอ httpx.request() สร้าง client ใหม่ทุกครั้ง ต้องโหลดใบรับรอง SSL ใหม่
# กิน CPU ราว 100 ms ต่อครั้งตอนคนใช้พร้อมกัน (เครื่อง 1 CPU บน Render ตันที่จุดนี้)
_client = httpx.Client()


def call(url_env: str, method: str, path: str, *, timeout: float, json=None, params=None, headers=None):
    """เรียก service อื่นแล้วคืนค่า data ถ้าพังจะ raise ApiError ที่ส่งต่อให้ผู้ใช้ได้เลย

    url_env คือชื่อตัวแปรใน .env เช่น "ROUTING_ENGINE_URL" timeout เป็นวินาทีตาม CONTRACT หัวข้อ 3
    """
    base = os.getenv(url_env)
    if not base:
        raise ApiError("INTERNAL_ERROR", f"ยังไม่ได้ตั้งค่า {url_env} ใน .env")
    name = url_env.removesuffix("_URL").lower().replace("_", "-")
    hdrs = {"X-Request-ID": _request_id.get() or str(uuid.uuid4()), **(headers or {})}
    try:
        res = _client.request(method, base.rstrip("/") + path, json=json, params=params, headers=hdrs, timeout=timeout)
        body = res.json()
    except httpx.TimeoutException:
        raise ApiError("UPSTREAM_TIMEOUT", f"ระบบ {name} ตอบไม่ทันเวลา ลองใหม่อีกครั้ง")
    except (httpx.HTTPError, ValueError):
        raise ApiError("UPSTREAM_ERROR", f"ติดต่อระบบ {name} ไม่ได้ ลองใหม่อีกครั้ง")
    if not isinstance(body, dict) or "error" not in body:
        raise ApiError("UPSTREAM_ERROR", f"ระบบ {name} ตอบผิดรูปแบบ")
    err = body["error"]
    if err:
        # บั๊กของปลายทางไม่ใช่บั๊กของเรา
        code = "UPSTREAM_ERROR" if err.get("code") == "INTERNAL_ERROR" else err.get("code", "UPSTREAM_ERROR")
        raise ApiError(code, err.get("message", ""))
    return body["data"]
