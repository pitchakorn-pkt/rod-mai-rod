from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from envelope import ApiError, ok, setup

app = FastAPI(title="safety-knowledge")
setup(app, "safety-knowledge")

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
HAZARD_TYPES = {
    "RAIN",
    "HEAVY_RAIN",
    "STRONG_WIND",
    "FLOOD",
    "LANDSLIDE_RISK",
    "STORM",
    "EARTHQUAKE",
}

CONTACTS = [
    {"name_th": "สายด่วนนิรภัย ปภ.", "phone": "1784"},
    {"name_th": "เจ็บป่วยฉุกเฉิน", "phone": "1669"},
    {"name_th": "เหตุด่วนเหตุร้าย", "phone": "191"},
    {"name_th": "สายด่วนกรมทางหลวง", "phone": "1586"},
    {"name_th": "ตำรวจทางหลวง", "phone": "1193"},
]

EMERGENCY = {
    "RAIN": [
        "เปิดที่ปัดน้ำฝนและใช้ความเร็วที่เหมาะสม",
        "เปิดไฟหน้าปกติ ห้ามเปิดไฟฉุกเฉินขณะขับรถ",
        "เว้นระยะห่างจากรถคันหน้ามากกว่าปกติ 2 เท่า",
    ],
    "HEAVY_RAIN": [
        "ลดความเร็วลงและเปิดไฟหน้าต่ำ",
        "หากมองไม่เห็นทาง ให้เปิดไฟเลี้ยวเข้าจอดในที่ปลอดภัย",
        "หลีกเลี่ยงการเบรกกะทันหันเพื่อป้องกันรถเหินน้ำ",
    ],
    "STRONG_WIND": [
        "จับพวงมาลัยด้วยสองมือให้มั่นคงเพื่อควบคุมรถ",
        "ลดความเร็วลงโดยเฉพาะเมื่อต้องขับผ่านที่โล่งหรือสะพาน",
        "หลีกเลี่ยงการขับรถใกล้รถบรรทุกขนาดใหญ่หรือป้ายโฆษณา",
    ],
    "FLOOD": [
        "อย่าขับรถผ่านบริเวณที่มีน้ำท่วมขังสูงเกินครึ่งล้อ",
        "ถ้ารถดับกลางน้ำท่วม ให้ขนย้ายคนออกจากรถไปที่สูงทันที",
        "ปิดเครื่องปรับอากาศและใช้เกียร์ต่ำขณะขับลุยน้ำ",
    ],
    "LANDSLIDE_RISK": [
        "สังเกตสีของน้ำและเศษดินหินที่ไหลลงมาจากไหล่ทาง",
        "หากพบดินหรือต้นไม้ไถลลงมา ให้หยุดรถและถอยห่างทันที",
        "หลีกเลี่ยงการจอดรถบริเวณไหล่เขาหรือหน้าผาเสี่ยงภัย",
    ],
    "STORM": [
        "จอดรถในที่ปลอดภัย ห่างจากต้นไม้ใหญ่ ป้ายโฆษณา และเสาไฟฟ้า",
        "อยู่ภายในรถยนต์และปิดกระจกทุกด้านให้มิดชิด",
        "เปิดสัญญาณไฟฉุกเฉินหากจำเป็นต้องจอดข้างทาง",
    ],
    "EARTHQUAKE": [
        "ค่อยๆ ชะลอรถและนำรถเข้าจอดข้างทางในที่โล่งแจ้ง",
        "ห้ามจอดรถใต้สะพาน ทางด่วน เสาไฟฟ้า หรือป้ายขนาดใหญ่",
        "อยู่ภายในรถจนกว่าการสั่นสะเทือนจะหยุดลง",
    ],
}


class SearchIn(BaseModel):
    query: str
    hazard_types: list[str] = []
    limit: int = Field(4, ge=1, le=10)


def load_docs() -> list[dict]:
    docs = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        parts = content.split("---", 2)
        if len(parts) < 3:
            continue
        head, body = parts[1], parts[2]

        title_th = ""
        source = ""
        hazard_types = []

        lines = head.strip().splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("title_th:"):
                title_th = line.split(":", 1)[1].strip()
            elif line.startswith("source:"):
                source = line.split(":", 1)[1].strip()
            elif line.startswith("hazard_types:"):
                val = line.split(":", 1)[1].strip()
                if val:
                    hazard_types.extend([h.strip() for h in val.split(",") if h.strip()])
                else:
                    while i + 1 < len(lines) and lines[i + 1].strip().startswith("-"):
                        i += 1
                        h_val = lines[i].strip().lstrip("-").strip()
                        if h_val:
                            hazard_types.append(h_val)
            i += 1

        docs.append({
            "doc_id": path.stem,
            "title_th": title_th,
            "hazard_types": hazard_types,
            "source": source,
            "lines": [ln.strip() for ln in body.strip().splitlines() if ln.strip()],
        })
    return docs


DOCS = load_docs()


def get_trigrams(text: str) -> set[str]:
    clean_text = text.replace(" ", "").lower()
    if not clean_text:
        return set()
    if len(clean_text) < 3:
        return {clean_text}
    return {clean_text[i : i + 3] for i in range(len(clean_text) - 2)}


def score(query: str, line: str) -> float:
    """นับจำนวน Trigrams ของ Query ที่พบใน Line"""
    query_grams = get_trigrams(query)
    line_grams = get_trigrams(line)
    if not query_grams or not line_grams:
        return 0.0

    return float(len(query_grams.intersection(line_grams)))


@app.post("/api/v1/safety/search")
def search(body: SearchIn):
    if not body.query.strip():
        raise ApiError("VALIDATION_ERROR", "ข้อความค้นหาว่าง")

    wanted = set(body.hazard_types)
    query_grams = get_trigrams(body.query)

    min_match_threshold = min(3, len(query_grams) // 2) if len(query_grams) >= 2 else 1

    hits = []
    for doc in DOCS:
        if wanted and not wanted & set(doc["hazard_types"]):
            continue

        # คำนวณคะแนน Trigram ของ title_th
        title_score = score(body.query, doc["title_th"])
        title_matched = title_score >= min_match_threshold and title_score > 0
        title_bonus = title_score * 2.0 if title_matched else 0.0

        matched_lines_count = 0
        for line in doc["lines"]:
            s = score(body.query, line)

            # ให้คะแนนบรรทัดที่ตรงตามเกณฑ์ + คะแนนโบนัสจาก Title
            if s >= min_match_threshold and s > 0:
                matched_lines_count += 1
                score_weight = s + title_bonus + (1.0 if wanted else 0.0)
                hits.append((
                    score_weight,
                    {
                        "doc_id": doc["doc_id"],
                        "title_th": doc["title_th"],
                        "snippet_th": line,
                        "source": doc["source"],
                    },
                ))

        # ถ้าไม่มีบรรทัดไหนในเนื้อหาตรงเลย แต่ title_th ตรงเกณฑ์ ให้ส่งบรรทัดแรกของเอกสารมา 1 บรรทัด
        if matched_lines_count == 0 and title_matched and doc["lines"]:
            score_weight = title_bonus + (1.0 if wanted else 0.0)
            hits.append((
                score_weight,
                {
                    "doc_id": doc["doc_id"],
                    "title_th": doc["title_th"],
                    "snippet_th": doc["lines"][0],
                    "source": doc["source"],
                },
            ))

    hits.sort(key=lambda h: -h[0])
    if not hits:
        return ok({"results": [], "warnings": []})

    # เอกสารที่ตรงที่สุดเป็นหลัก: บรรทัดที่ตรงคำถามก่อน แล้วเติมบรรทัดอื่นของเอกสารนั้น (คำตอบได้ครบขั้นตอน
    # ไม่ใช่ประโยคเดียว) เว้นที่ 1 บรรทัดให้เอกสารอื่นที่ตรงด้วย เผื่อคำถามคาบเกี่ยวหลายเรื่อง
    top = next(d for d in DOCS if d["doc_id"] == hits[0][1]["doc_id"])
    item = lambda doc, line: {"doc_id": doc["doc_id"], "title_th": doc["title_th"], "snippet_th": line, "source": doc["source"]}
    primary = [h for _, h in hits if h["doc_id"] == top["doc_id"]]
    primary += [item(top, line) for line in top["lines"] if line not in {h["snippet_th"] for h in primary}]
    others = [h for _, h in hits if h["doc_id"] != top["doc_id"]]
    room = body.limit - 1 if others and body.limit > 1 else body.limit
    picked = primary[:room] + others

    unique_results, seen = [], set()
    for h in picked:
        key = (h["doc_id"], h["snippet_th"])
        if key not in seen:
            seen.add(key)
            unique_results.append(h)
            if len(unique_results) >= body.limit:
                break

    return ok({"results": unique_results, "warnings": []})


@app.get("/api/v1/safety/emergency")
def emergency(hazard_type: str):
    if hazard_type not in HAZARD_TYPES:
        raise ApiError("VALIDATION_ERROR", f"ไม่รู้จัก hazard_type: {hazard_type}")
    steps: Optional[list[str]] = EMERGENCY.get(hazard_type)
    if steps is None:
        raise ApiError("NOT_FOUND", "ยังไม่มีคำแนะนำสำหรับภัยชนิดนี้")
    return ok({"hazard_type": hazard_type, "steps_th": steps, "contacts": CONTACTS})