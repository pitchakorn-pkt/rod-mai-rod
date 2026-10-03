"""ถามตอบทั่วไปผ่าน LLM ด้วยไลบรารี openai ตัวเดียว เปลี่ยนผู้ให้บริการด้วย base_url (CONTRACT หัวข้อ 10)"""
import json
import logging
import os
import re
import time
from typing import Callable, Optional

from openai import OpenAI, OpenAIError

import rules
import tools
from envelope import _request_id

log = logging.getLogger("assistant-agent")

LLM_TIMEOUT = 30  # วินาทีต่อครั้ง ตาม CONTRACT หัวข้อ 3
HISTORY_LIMIT = 10
MAX_TOOL_ROUNDS = 4
TIME_BUDGET = 90  # วินาที api-backend รอเรา 100 วิ
TOOL_MIN_TIME = 45  # ต้องเหลือเวลาพอให้ /plan ตอบ (api-backend รอ routing-engine 45 วิ)

RunTool = Callable[[str, Optional[dict]], tuple[dict, list]]

BOT_NAME = "น้องกิเลน"  # ชื่อมาสคอต เปลี่ยนที่นี่ที่เดียว (หน้าเว็บใช้ชื่อเดียวกัน)

SYSTEM_PROMPT = (
    f"คุณชื่อ{BOT_NAME} มาสคอตกิเลนของเว็บรอดไม่รอด ผู้ช่วยวางแผนเที่ยวในประเทศไทยให้ปลอดภัย "
    f"แทนตัวเองว่า{BOT_NAME}หรือผม เป็นกันเอง ใจดี ถ้าผู้ใช้ถามชื่อหรือถามว่าเป็นใคร ให้แนะนำตัวว่าเป็น{BOT_NAME} "
    f"ถ้าผู้ใช้เรียกด้วยชื่ออื่น ให้บอกสุภาพว่าตัวเองชื่อ{BOT_NAME} "
    "ตอบภาษาอังกฤษให้ใช้ชื่อ Nong Qilin มาสคอต qilin ของเว็บ Rod Mai Rod "
    "ตอบสั้น กระชับ ไม่เกิน 5 บรรทัด เป็นภาษาเดียวกับที่ผู้ใช้พิมพ์ (ส่วนใหญ่คือภาษาไทย) ภาษาไทยลงท้ายด้วยครับ "
    "ถ้าข้อความล่าสุดของผู้ใช้เป็นภาษาอังกฤษ ให้ตอบเป็นภาษาอังกฤษทั้งข้อความ แม้ข้อมูลจาก tool จะเป็นภาษาไทย "
    "หน้าแชทแสดงข้อความธรรมดา ห้ามใช้ markdown เช่น ** หรือ # ใช้ขีด - นำหน้าข้อได้ "
    "บอกระดับความเสี่ยงเป็นคำไทย (ต่ำ ปานกลาง สูง) ห้ามพิมพ์รหัสภาษาอังกฤษของระบบ "
    "ห้ามแต่งข้อมูลสภาพอากาศ ความเสี่ยง หรือเบอร์โทรเอง ถ้าไม่มีข้อมูลให้บอกตรงๆ "
    "ระดับความเสี่ยงของทริปมาจากระบบเท่านั้น คุณไม่ได้เป็นคนตัดสิน "
    "ถ้าผู้ใช้สั่งดู สร้าง หรือแก้ทริป ให้เรียก tools ที่มี ห้ามบอกว่าทำแล้วถ้า tool ไม่ได้ตอบว่าสำเร็จ "
    "ผู้ใช้บอกว่าอยากไป จะไป วางแผนไป หรือพาไปที่ไหน = ทริปใหม่เสมอ ให้สร้างด้วย create_trip "
    "แม้มีทริปไปที่เดียวกันหรือใกล้กันอยู่แล้ว (คนไปที่เดิมซ้ำได้ เช่น ไปอีกวัน) ห้ามตอบว่ามีทริปนี้อยู่แล้วแทนการสร้าง "
    "ทริปเดิมใช้เฉพาะตอนผู้ใช้พูดถึงทริปที่มีอยู่ชัดเจน เช่น บอกเลขทริป หรือพูดว่า ทริปที่ใกล้ที่สุด ทริปไปเชียงใหม่ "
    "เลื่อนทริป แก้ทริป ดูอากาศของทริป ให้เลือกเลขทริปจากข้อมูลบริบท "
    "ถามกลับเฉพาะตอนที่ยังกำกวมจริง เช่น มีสองทริปไปที่เดียวกันแล้วผู้ใช้สั่งแก้ "
    "เวลาแบบคน เช่น 12 หรือเที่ยง = 12:00 บ่ายสอง = 14:00 "
    "บอกระดับความเสี่ยงและตัวเลขอากาศตามที่ tool ตอบเท่านั้น "
    "สร้างทริปใช้ create_trip ต้องรู้ต้นทาง ปลายทาง วันและเวลาออก ขาดข้อไหนให้ถามเฉพาะข้อที่ขาดทีเดียวให้ครบ "
    "ห้ามถามซ้ำข้อที่ผู้ใช้บอกแล้วในข้อความนี้หรือข้อความก่อนหน้า เช่น บอกปลายทางแล้วไม่ต้องถามปลายทางอีก "
    "แก้ต้นทาง ปลายทาง จุดแวะ ใช้ update_trip_places แก้เวลาใช้ update_trip_time "
    "ถามว่าที่ไหนฝนตก น้ำท่วม หรือมีภัยไหม (ไม่ใช่ทริป) ให้เรียก place_conditions แล้วตอบตามผลนั้น บอกด้วยว่าเป็นข้อมูลตอนนี้ "
    "ถ้าถามอากาศล่วงหน้า เช่น พรุ่งนี้ หรือเสาร์อาทิตย์นี้ ให้บอกตรงๆ ว่าดูได้แค่ตอนนี้ แล้วเสนอสร้างทริปเพื่อดูพยากรณ์ตามเวลาที่ไปถึง "
    "ถามเบอร์โทรฉุกเฉินหรือต้องบอกเบอร์โทร ให้เรียก emergency_info แล้วบอกเฉพาะเบอร์ที่ได้ ห้ามบอกเบอร์จากความจำ "
    "ห้ามเดาระยะทางหรือเวลาขับรถระหว่างเมือง ให้เสนอสร้างทริปเพื่อให้ระบบคำนวณเส้นทางจริง "
    "เรื่องที่ไม่เกี่ยวกับการเดินทางในไทย เช่น เขียนโค้ด ทำการบ้าน ให้ปฏิเสธสุภาพสั้นๆ แล้วบอกว่าช่วยอะไรได้บ้าง "
    "ขอให้แนะนำที่เที่ยว ให้เรียก nearby_places แล้วแนะนำจากผลนั้นเท่านั้น แล้วถามว่าจะให้สร้างทริปไปไหม "
    "คำถามต่อที่ต้องบอกชื่อสถานที่ เช่น แล้วคาเฟ่ล่ะ หรือ ที่ไหนเหมาะกับเด็ก ให้เรียก nearby_places ใหม่ทุกครั้ง "
    "ใช้เมืองเดิมจากบทสนทนาและ kinds ที่ตรงคำถาม ห้ามเอาชื่อสถานที่จากความจำหรือจากคำตอบก่อนหน้า ห้ามบอกชื่อเดียวกันซ้ำ "
    "ถ้าผู้ใช้บอกแนว เช่น วัยรุ่น ชิลๆ ช้อปปิ้ง กินดื่ม ธรรมชาติ ให้ส่ง kinds ให้ตรงแนว และใช้ radius_km 15 เมื่อถามทั้งเมือง "
    "ถ้า nearby_places ดึงไม่ได้ ให้บอกตรงๆ ว่าตอนนี้ดึงข้อมูลไม่ได้ ห้ามแต่งชื่อสถานที่เอง "
    "แชทนี้ลบทริปไม่ได้ ถ้าผู้ใช้ขอ ให้บอกว่าลบได้ที่หน้า \"ทริปของฉัน\" "
    "ถ้า tool ตอบ error ให้บอกเหตุผลเป็นภาษาคน เช่น วันที่ขอผ่านไปแล้ว ห้ามพูดถึงชื่อ tool หรือตัวเลขข้อจำกัดภายใน"
)

FALLBACK_REPLY = (
    "ตอนนี้ตอบคำถามทั่วไปไม่ได้ชั่วคราว แต่ยังสั่งได้ เช่น "
    "\"เลื่อน Trip 01 ไปวันถัดไป\", \"เลื่อน Trip 01 เป็นช่วงบ่าย\", \"Trip 01 อากาศเป็นยังไง\""
)


def providers() -> list[dict]:
    """ผู้ให้บริการตามลำดับ LLM_PRIMARY แล้ว LLM_FALLBACK (ใส่หลายตัวคั่นด้วย , ได้) ข้ามตัวที่ยังไม่ได้ใส่ key หรือชื่อโมเดล"""
    out = []
    for name in [os.getenv("LLM_PRIMARY", ""), *os.getenv("LLM_FALLBACK", "").split(",")]:
        prefix = name.strip().upper()
        if not prefix:
            continue
        key, model = os.getenv(f"{prefix}_API_KEY"), os.getenv(f"{prefix}_MODEL")
        if key and model:
            out.append({"name": name, "api_key": key, "model": model, "base_url": os.getenv(f"{prefix}_BASE_URL")})
    return out


def clean(snippet: str) -> str:
    """บรรทัดในเอกสารขึ้นต้นด้วย "- " อยู่แล้ว ตัดออกไม่ให้ขึ้น "- -" ซ้อน"""
    return snippet.lstrip("-*• ").strip()


def document_reply(sources: list[dict]) -> str:
    """ตอบจากเอกสารตรงๆ ตอน LLM ล่ม รวมบรรทัดของแหล่งเดียวกันแล้วบอกที่มาครั้งเดียว"""
    by_source: dict[str, list[str]] = {}
    for s in sources:
        by_source.setdefault(s["source"], []).append(clean(s["snippet_th"]))
    parts = ["\n".join(f"- {line}" for line in lines) + f"\n(ที่มา: {src})" for src, lines in by_source.items()]
    return "ข้อแนะนำจากเอกสาร:\n" + "\n\n".join(parts)


def build_messages(message: str, history: list[dict], sources: list[dict], context: str = "") -> list[dict]:
    # รวมเป็น system ข้อความเดียว: Gemini ใช้แค่ system อันสุดท้าย ถ้าแยกหลายอันคำสั่งหลัก (ชื่อ กฎห้ามแต่ง) จะหาย
    system = [SYSTEM_PROMPT]
    if context:
        system.append(context)
    if sources:
        refs = "\n".join(f"- {clean(s['snippet_th'])} (ที่มา: {s['source']})" for s in sources)
        system.append("ข้อมูลความปลอดภัยจากเอกสารที่เชื่อถือได้ ใช้ตอบและบอกที่มา:\n" + refs)
    msgs = [{"role": "system", "content": "\n\n".join(system)}]
    for h in history[-HISTORY_LIMIT:]:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
            msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": message})
    return msgs


def plain(text: str) -> str:
    """หน้าแชทแสดงข้อความธรรมดา โมเดลบางตัวยังใส่ markdown มาแม้สั่งห้าม ตัดทิ้งก่อนส่ง"""
    text = re.sub(r"\*\*|__|`|[​-‍﻿]", "", text)  # อักขระล่องหนติดมากับชื่อใน OSM
    text = re.sub(r"^(\s*)[*•]\s+", r"\1- ", text, flags=re.MULTILINE)  # Gemini ใช้ * เป็นหัวข้อย่อย
    text = text.replace("*", "")  # ตัวเอียง *(หมายเหตุ)* ที่เหลือ
    text = re.sub(r"^\s*#+\s*", "", text, flags=re.MULTILINE).strip()
    # บางครั้งโมเดลวนพิมพ์บรรทัดเดิมซ้ำ (เช่นชื่อร้านเดียว 10 บรรทัด) เก็บไว้แค่ครั้งแรก
    seen: set[str] = set()
    lines = []
    for line in text.split("\n"):
        key = line.strip()
        if key and key in seen:
            continue
        seen.add(key)
        lines.append(line)
    text = re.sub(r"\n\s*-{3,}\s*$", "", "\n".join(lines))  # เส้นคั่นค้างท้ายข้อความ
    return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text).strip()  # บรรทัดว่างติดกันเหลือบรรทัดเดียว


def tool_call_message(msg) -> dict:
    calls = []
    for c in msg.tool_calls:
        call = {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
        # Gemini 3 ต้องได้ thought_signature ใน extra_content คืนไปด้วย ไม่งั้นรอบถัดไปตอบ 400
        extra = getattr(c, "extra_content", None)
        if extra:
            call["extra_content"] = extra
        calls.append(call)
    return {"role": "assistant", "content": msg.content or "", "tool_calls": calls}


def done_reply(results: list[dict]) -> str:
    """ใช้ตอนแก้ทริปสำเร็จแล้วแต่ LLM ไม่ได้ตอบต่อ ต้องบอกผู้ใช้ว่าเกิดอะไรขึ้นจริง"""
    lines = []
    for r in results:
        if r.get("created"):
            lines.append(f"สร้าง {r['name']} {r['route_th']} ออก {r['departure_th']} แล้ว")
        elif r.get("updated") and r.get("route_th"):
            lines.append(f"แก้ {r['name']} เป็น {r['route_th']} แล้ว")
        elif r.get("updated"):
            lines.append(f"เลื่อน {r['name']} ไปออกเดินทาง {r['departure_th']} แล้ว")
        elif r.get("planned"):
            lines.append(f"วางแผน {r['name']} ใหม่แล้ว")
        plan = r.get("plan") or (r if r.get("planned") else None)
        if plan:
            lines.append(f"ความเสี่ยงระดับ{plan.get('risk_th', 'ไม่ทราบ')} {plan.get('summary_th') or ''}".strip())
        if r.get("plan_error"):
            lines.append("แต่คำนวณเส้นทางใหม่ไม่สำเร็จ กด Plan ในหน้า My Trip อีกครั้งนะครับ")
    return "\n".join(lines)


def log_event(level: int, event: str, **fields):
    log.log(level, json.dumps({"service": "assistant-agent", "request_id": _request_id.get(),
                               "event": event, **fields}, ensure_ascii=False))


def unique(actions: list[dict]) -> list[dict]:
    """เลื่อนแล้วแพลนทริปเดียวกันซ้ำ ให้เหลือ action เดียว"""
    seen, out = set(), []
    for a in actions:
        key = (a["type"], a["trip_id"])
        if key not in seen:
            seen.add(key)
            out.append(a)
    return out


# คำถามต่อ เช่น "แล้วคาเฟ่ล่ะ" โมเดลบางทีตอบรายชื่อร้านจากความจำโดยไม่เรียก tool (ได้ชื่อมั่ว/ซ้ำ)
PLACE_ASK = re.compile(r"คาเฟ่|ร้าน|ที่เที่ยว|เที่ยว|ตลาด|ห้าง|สวน|ผับ|บาร์|น้ำตก|แนะนำ|ที่ไหน|แวะ")
LOOKUP_NUDGE = ("คำตอบก่อนหน้ามีรายชื่อสถานที่ที่ไม่ได้มาจาก tool ให้เรียก nearby_places (หรือ tool ที่ตรงคำถาม) ก่อน "
                "แล้วตอบจากผลนั้นเท่านั้น")


def unsourced_places(text: str, question: str) -> bool:
    """ตอบเป็นรายการชื่อสถานที่ 2 ข้อขึ้นไป ทั้งที่รอบนี้ยังไม่ได้เรียก tool"""
    return bool(PLACE_ASK.search(question)) and sum(bool(re.match(r"\s*([-*•]|\d+[.)])\s", l)) for l in text.split("\n")) >= 2


# ถามภาษาอังกฤษ แต่ Qwen มักตอบไทยตามข้อมูลจาก tool ที่เป็นภาษาไทย แม้ system สั่งแล้ว
ENGLISH_NUDGE = ("The user wrote in English. Rewrite your previous answer entirely in English. "
                 "Keep the same facts and numbers, and write Thai place names in English letters.")


def _thai(text: str) -> int:
    return sum("฀" <= c <= "๿" for c in text)


def wrong_language(text: str, question: str) -> bool:
    """ถามเป็นภาษาอังกฤษล้วน แต่คำตอบเป็นภาษาไทยเกิน 30% ของตัวอักษร"""
    if _thai(question) or not re.search(r"[A-Za-z]{2}", question):
        return False
    return _thai(text) > 0.3 * max(1, sum(c.isalpha() for c in text))


def complete(messages: list[dict], run_tool: Optional[RunTool] = None) -> tuple[Optional[str], list, list]:
    """ลองตัวหลักก่อน ล่ม / 429 / โมเดลถูกถอด ค่อยลองตัวสำรอง
    คืน (ข้อความ หรือ None ถ้าล่มหมด, actions, ผลของ tools ที่แก้ข้อมูลสำเร็จ)"""
    deadline = time.monotonic() + TIME_BUDGET
    actions: list = []
    changed: list[dict] = []
    for p in providers():
        convo = list(messages)
        used_tool = nudged = relang = False
        try:
            client = OpenAI(api_key=p["api_key"], base_url=p["base_url"], timeout=LLM_TIMEOUT, max_retries=0)
            extra = {"tools": tools.SCHEMAS} if run_tool else {}
            for _ in range(MAX_TOOL_ROUNDS + 1):
                remaining = deadline - time.monotonic()
                if remaining < 5:
                    break
                res = client.chat.completions.create(model=p["model"], messages=convo, temperature=0.3,
                                                     timeout=min(LLM_TIMEOUT, remaining), **extra)
                msg = res.choices[0].message
                if not getattr(msg, "tool_calls", None):
                    text = plain(msg.content or "")
                    if text and run_tool and not used_tool and not nudged and unsourced_places(msg.content or "", messages[-1]["content"]):
                        nudged = True
                        convo.append({"role": "user", "content": LOOKUP_NUDGE})  # Qwen ไม่ค่อยฟัง system กลางบทสนทนา
                        continue
                    if text and not relang and wrong_language(text, messages[-1]["content"]):
                        relang = True
                        convo += [{"role": "assistant", "content": msg.content or ""}, {"role": "user", "content": ENGLISH_NUDGE}]
                        continue
                    if text:
                        return text, unique(actions), changed
                    break
                convo.append(tool_call_message(msg))
                used_tool = True
                for c in msg.tool_calls:
                    if deadline - time.monotonic() < TOOL_MIN_TIME:
                        result, acts = {"error": "หมดเวลา ให้ผู้ใช้ลองใหม่อีกครั้ง"}, []
                    else:
                        try:
                            args = json.loads(c.function.arguments or "{}")
                        except ValueError:
                            args = None
                        result, acts = run_tool(c.function.name, args)
                    log_event(logging.INFO, "tool_called", provider=p["name"], tool=c.function.name,
                              ok="error" not in result)
                    if acts:
                        actions += acts
                        changed.append(result)
                    convo.append({"role": "tool", "tool_call_id": c.id,
                                  "content": json.dumps(result, ensure_ascii=False)})
        except OpenAIError as e:
            log_event(logging.WARNING, "llm_failed", provider=p["name"], error=type(e).__name__)
        if actions:
            # แก้ทริปไปแล้ว ห้ามเริ่มใหม่กับตัวสำรอง ไม่งั้นจะเลื่อนซ้ำ
            break
    return None, unique(actions), changed


def answer(message: str, history: list[dict], sources: list[dict], run_tool: Optional[RunTool] = None,
           context: str = "") -> dict:
    text, actions, changed = complete(build_messages(message, history, sources, context), run_tool)
    if text is not None:
        return {"reply": text, "actions": actions, "warnings": []}
    if changed:
        return {"reply": done_reply(changed), "actions": actions, "warnings": ["LLM_UNAVAILABLE"]}
    # คำสั่งเกี่ยวกับทริป เช่น "ทริป 1 ออกเร็วขึ้น" ค้นเอกสารเจอ "ความเร็ว" ได้ ตอบจากเอกสารจะไม่ตรงคำถาม
    # ให้บอกคำสั่งที่ยังใช้ได้แทน
    if sources and not (rules.MOVE.search(message) or rules.TRIP_NO.search(message)):
        # LLM ล่มแต่มีข้อมูลจากเอกสาร ยังตอบจากเอกสารตรงๆ ได้
        return {"reply": document_reply(sources), "actions": [], "warnings": ["LLM_UNAVAILABLE"]}
    return {"reply": FALLBACK_REPLY, "actions": [], "warnings": ["LLM_UNAVAILABLE"]}
