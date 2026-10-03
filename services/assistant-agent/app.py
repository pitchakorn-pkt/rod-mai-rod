"""assistant-agent

คำสั่งหลัก 3 แบบจับด้วยกฎตายตัว (rules.py) ใช้ได้แม้ LLM ล่ม นอกนั้นส่งให้ LLM (llm.py)
แก้ทริปผ่าน backend() ด้วย token ของผู้ใช้เท่านั้น แล้วคืน actions ตาม docs/CONTRACT.md หัวข้อ 6
"""
from typing import Optional

from fastapi import FastAPI, Header
from pydantic import BaseModel

import llm
import rules
import tools
from envelope import ApiError, call, ok, setup

app = FastAPI(title="assistant-agent")
setup(app, "assistant-agent")

BACKEND_TIMEOUT = 60  # วินาที ตาม CONTRACT หัวข้อ 3 (PATCH แล้วอาจต้อง /plan ต่อ)
SAFETY_TIMEOUT = 10
MAX_MESSAGE = 2000


class ChatIn(BaseModel):
    message: str
    history: list[dict] = []
    user_name: Optional[str] = None  # ชื่อที่ผู้ใช้ตั้งในโปรไฟล์ (api-backend ส่งมา)


def backend(method: str, path: str, authorization: str, json=None, params=None):
    """เรียก api-backend ด้วยสิทธิ์ของผู้ใช้คนนี้เท่านั้น เช่น backend("GET", "/api/v1/trips", auth)
    ถ้า api-backend ปฏิเสธจะ raise ApiError ห้ามตอบผู้ใช้ว่าสำเร็จในกรณีนั้น"""
    return call("API_BACKEND_URL", method, path, timeout=BACKEND_TIMEOUT, json=json, params=params,
                headers={"Authorization": authorization})


def trips_context(authorization: str) -> str:
    """สรุปทริปของผู้ใช้ให้ LLM ดึงไม่ได้ก็ข้ามไป LLM ยังเรียก list_trips เองได้"""
    try:
        return tools.context_text(backend("GET", "/api/v1/trips", authorization))
    except ApiError:
        return ""


def name_context(name: Optional[str]) -> str:
    if not name:
        return ""
    return f"ผู้ใช้ชื่อ {name} เรียกผู้ใช้ว่า คุณ{name} ได้ ถ้าผู้ใช้ถามว่าตัวเองชื่ออะไรให้ตอบชื่อนี้\n"


def safety_search(query: str, hazard_types: Optional[list[str]] = None) -> list[dict]:
    """คำแนะนำความปลอดภัยจากเอกสารจริง ใช้ตอบคำถามแบบ "น้ำท่วมต้องทำยังไง" แทนให้ LLM แต่งเอง
    คืน [] ถ้าค้นไม่เจอหรือ safety-knowledge ล่ม ส่ง source ไปให้ LLM อ้างอิงด้วย"""
    try:
        data = call("SAFETY_KNOWLEDGE_URL", "POST", "/api/v1/safety/search", timeout=SAFETY_TIMEOUT,
                    json={"query": query, "hazard_types": hazard_types or []})
    except ApiError:
        return []
    return data["results"]



@app.post("/api/v1/chat")
def chat(body: ChatIn, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise ApiError("UNAUTHORIZED", "ต้องส่ง Authorization ของผู้ใช้มาด้วย")
    message = body.message.strip()
    if not message:
        raise ApiError("VALIDATION_ERROR", "ข้อความว่าง")
    if len(message) > MAX_MESSAGE:
        raise ApiError("VALIDATION_ERROR", f"ข้อความยาวเกิน {MAX_MESSAGE} ตัวอักษร")

    reply = rules.try_rules(message, authorization, backend)
    if reply is not None:
        return ok(reply)
    return ok(llm.answer(message, body.history, safety_search(message),
                         lambda name, args: tools.run(name, args, backend, authorization),
                         context=name_context(body.user_name) + trips_context(authorization)))
