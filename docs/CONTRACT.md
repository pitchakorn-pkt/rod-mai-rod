# CONTRACT.md - กฎกลางของ rod-mai-rod

ทุกคนต้องทำตามไฟล์นี้เหมือนกันหมด งานของแต่ละคนถึงจะเสียบเข้าหากันได้โดยไม่พัง
ไฟล์นี้แก้ได้ผ่าน PR ที่เจ้าของโปรเจกต์อนุมัติเท่านั้น ถ้าคิดว่าตรงไหนผิดหรือขาด ให้ทักในกลุ่มก่อน อย่าแก้เองแล้วเขียนโค้ดตามที่ตัวเองแก้

อ่านคู่กับ [`SPEC.md`](SPEC.md) (ฟีเจอร์), [`MODULES.md`](MODULES.md) (ใครทำอะไร) และ [`RUNBOOK.md`](RUNBOOK.md) (ถ้าพังทำยังไง)

---

## 1. Service และพอร์ต

| โมดูล | โฟลเดอร์ | ชื่อ host ใน Docker | พอร์ตภายใน container | พอร์ตบนเครื่อง (ไว้ยิงทดสอบเท่านั้น) |
|---|---|---|---|---|
| Frontend | `apps/web/` | `web` | 8000 | 3000 |
| API Gateway + Auth + DB | `services/api-backend/` | `api-backend` | 8000 | 8001 |
| Routing Engine | `services/routing-engine/` | `routing-engine` | 8000 | 8002 |
| Weather & Disaster | `services/weather-disaster/` | `weather-disaster` | 8000 | 8003 |
| Risk & Decision | `services/risk-decision/` | `risk-decision` | 8000 | 8004 |
| Assistant Agent | `services/assistant-agent/` | `assistant-agent` | 8000 | 8005 |
| Safety Knowledge | `services/safety-knowledge/` | `safety-knowledge` | 8000 | 8006 |
| Postgres | - | `postgres` | 5432 | 5433 (กันชนกับ Postgres ที่ลงไว้ในเครื่อง) |

**กฎสำคัญที่สุดของตารางนี้**

- service คุยกันเองใน Docker ใช้ `http://<ชื่อ host>:8000` เสมอ เช่น `http://routing-engine:8000` **ไม่ใช่** `routing-engine:8002`
- พอร์ต 8001 ถึง 8006 มีไว้ยิง curl ทดสอบจากเครื่องตัวเองเท่านั้น ห้ามเขียนลงในโค้ด
- ห้าม hardcode URL ของ service อื่นในโค้ด ให้อ่านจาก env ตามชื่อใน `.env.example` เช่น `ROUTING_ENGINE_URL`
- ห้ามใช้ `localhost` เรียก service อื่น (ใน container `localhost` คือตัวมันเอง)

## 2. ใครเรียกใครได้บ้าง

```
browser ──> web (Next.js) ──> api-backend            ทางเดียวที่ frontend ใช้
api-backend ──> routing-engine ──> risk-decision ──> weather-disaster
api-backend ──> weather-disaster                      สภาพอากาศแบบ area + หมุด Safety Map
api-backend ──> assistant-agent ──> api-backend       assistant แก้ทริปผ่าน api-backend เท่านั้น
assistant-agent ──> safety-knowledge                  ค้นคำแนะนำความปลอดภัยมาตอบในแชท
api-backend ──> safety-knowledge                      คำแนะนำฉุกเฉินให้หน้าเว็บ
api-backend ──> postgres                              มีแค่ api-backend ที่แตะฐานข้อมูล
```

- frontend ห้ามเรียก service หลังบ้านตัวอื่นตรงๆ
- ห้าม service ไหนต่อฐานข้อมูลเองนอกจาก api-backend
- ห้ามเพิ่มเส้นเรียกใหม่ที่ไม่อยู่ในผังนี้โดยไม่คุยกันก่อน (กันเรียกวนเป็นวงแล้วค้าง)

## 3. กฎ API ที่ทุก service ต้องทำเหมือนกัน

- ทุก endpoint ขึ้นต้นด้วย `/api/v1/`
- ทุก service มี `GET /health` ตอบ `{"status":"ok","service":"<ชื่อ service>"}` (endpoint นี้ตัวเดียวที่ไม่ห่อ envelope)
- ทุก request ที่ข้าม service ต้องส่ง header `X-Request-ID` ต่อไปด้วย frontend (`shared/api.ts`) สร้างให้ทุกคำขอ ถ้าคำขอไหนมาถึง service โดยไม่มี ให้ service นั้นสร้างใหม่ ทุก service ส่งค่านี้กลับใน response header และทุกบรรทัด log ต้องมี request_id
- ทุก response ห่อแบบเดียวกัน:

```json
{ "data": { }, "error": null }
{ "data": null, "error": { "code": "OUT_OF_THAILAND", "message": "ตอนนี้รองรับเฉพาะสถานที่ในประเทศไทย" } }
```

### รหัส error และ HTTP status (ใช้ชุดนี้ชุดเดียว)

| code | HTTP | ใช้เมื่อ |
|---|---|---|
| `VALIDATION_ERROR` | 400 | ข้อมูลที่ส่งมาไม่ครบหรือผิดรูปแบบ |
| `UNAUTHORIZED` | 401 | ไม่มี token หรือ token หมดอายุ |
| `FORBIDDEN` | 403 | พยายามแตะทริปของคนอื่น |
| `NOT_FOUND` | 404 | ไม่เจอทริป/หมุดที่ขอ |
| `OUT_OF_THAILAND` | 422 | พิกัดอยู่นอกประเทศไทย |
| `RATE_LIMITED` | 429 | API ภายนอกหรือ LLM โดนจำกัดโควตา |
| `UPSTREAM_ERROR` | 502 | service ปลายทางหรือ API ภายนอกตอบผิดพลาด |
| `UPSTREAM_TIMEOUT` | 504 | service ปลายทางตอบไม่ทันเวลา |
| `INTERNAL_ERROR` | 500 | บั๊กในโค้ดตัวเอง |

### ข้อมูลไม่ครบ ไม่ใช่ error

ถ้าส่วนใดส่วนหนึ่งพัง (เช่น ดึงสภาพอากาศไม่ได้) แต่ส่วนอื่นยังใช้ได้ **ห้ามตอบ error ทั้งก้อน** ให้ตอบ `data` เท่าที่มี แล้วใส่ `warnings` ในตัว `data`:

```json
{ "data": { "...": "...", "warnings": ["WEATHER_UNAVAILABLE"] }, "error": null }
```

warning ที่ใช้ได้: `WEATHER_UNAVAILABLE`, `HAZARD_FEED_UNAVAILABLE`, `ALTERNATIVE_ROUTES_UNAVAILABLE`, `FORECAST_OUT_OF_RANGE`, `LLM_UNAVAILABLE`
frontend ต้องแสดงแถบแจ้งเตือนตาม warning ที่ได้ ห้ามทำเป็นไม่เห็น
**ห้ามถือว่า "ไม่มีข้อมูล" เท่ากับ "ปลอดภัย"** ถ้าไม่มีข้อมูลอากาศของจุดไหน ให้ `risk_level` และ `risk_score` ของจุดนั้นเป็น `null` พร้อม `WEATHER_UNAVAILABLE` ห้ามเติม LOW เอง frontend แสดง `null` เป็น "ไม่ทราบ"
ระดับรวมของเส้นทางคิดจากจุดที่มีข้อมูล แต่ต้องมี warning ติดไปด้วยเสมอ ถ้าไม่มีข้อมูลเลยสักจุด ระดับรวมก็เป็น `null`

### Timeout (ทุกการเรียกออกไปข้างนอกต้องตั้ง timeout ห้ามรอไม่จำกัด)

| จาก ไป | timeout |
|---|---|
| web ไป api-backend (ทั่วไป) | 60 วินาที |
| web ไป api-backend (`/assistant/chat` เท่านั้น) | 120 วินาที |
| api-backend ไป routing-engine | 45 วินาที (`/trips/{id}/departures` ถาม +3 และ +6 ชม. พร้อมกัน ครั้งละ 45 วินาที) |
| api-backend ไป weather-disaster | 10 วินาที (`/forecast/route` 20 วินาที เพราะส่งหลายจุด) |
| api-backend ไป บริการค้นสถานที่ (Photon) | 5 วินาที |
| api-backend ไป Overpass (สถานที่เที่ยวใกล้ตัว) | 8 วินาที (ไม่ทันโหลดต่อเบื้องหลังได้ถึง 30 วินาที, Overpass ตอบ error ใช้ Photon ค้นตามหมวดแทน 8 วินาที) |
| weather-disaster ไป GISTDA (น้ำท่วมจากดาวเทียม) | 30 วินาทีต่อหน้า ทำเบื้องหลังเท่านั้น ห้ามเรียกระหว่างคำขอของผู้ใช้ |
| routing-engine ไป risk-decision | 30 วินาที |
| risk-decision ไป weather-disaster | 10 วินาทีต่อครั้ง |
| weather-disaster ไป API ภายนอก | 8 วินาทีต่อครั้ง ยิงหลายแหล่งพร้อมกัน ไม่ใช่ทีละแหล่ง |
| api-backend ไป assistant-agent | 100 วินาที |
| assistant-agent ไป LLM | 30 วินาทีต่อครั้ง |
| assistant-agent ไป api-backend | 60 วินาที (เพราะอาจเรียก `/plan` ต่อ) |
| assistant-agent / api-backend ไป safety-knowledge | 10 วินาที |

ตัวในต้องสั้นกว่าตัวนอกเสมอ ไม่งั้นตัวนอกจะตัดสายก่อนตัวในตอบ

### จำกัดจำนวนครั้ง (api-backend)

| เส้น | จำกัด | นับตาม |
|---|---|---|
| `POST /auth/login` | 10 ครั้งต่อนาที | IP ผู้ใช้ (`X-Forwarded-For` ตัวแรก) กันเดารหัสผ่าน |
| `POST /assistant/chat` | 10 ข้อความต่อนาที | ผู้ใช้ที่ login กันโควตา LLM ฟรีหมด |

เกินได้ `RATE_LIMITED` (429) "ส่งคำขอถี่เกินไป รอสักครู่แล้วลองใหม่" · **web ต้องส่ง `X-Forwarded-For` ต่อให้ api-backend เสมอ** (ตัวส่งต่อใน `app/api/v1/[...path]/route.ts` ทำให้แล้ว) ไม่งั้นทุกคนนับเป็น IP ของ web แล้วโดนล็อกพร้อมกัน

**เรียก service อื่นด้วย `call()` ใน `envelope.py` เท่านั้น** เช่น `call("ROUTING_ENGINE_URL", "POST", "/api/v1/routes/plan", timeout=45, json=...)`
มันอ่าน URL จาก env, ส่ง `X-Request-ID` ต่อ, คืนค่า `data` ให้เลย และถ้าพังจะ raise `ApiError` ที่เป็น `UPSTREAM_TIMEOUT` / `UPSTREAM_ERROR` หรือ code เดิมของปลายทาง
ถ้าอยากให้ส่วนที่พังกลายเป็น warning แทน error ให้ `try: ... except ApiError:` ครอบเอง (ตัวอย่างใน `services/routing-engine/app.py`)

### Stub ก่อนโค้ดจริง

ทุก service ใน repo มี stub ที่ตอบข้อมูลปลอมตาม endpoint ในหัวข้อ 6 อยู่แล้ว **ห้ามลบ endpoint ออกจาก stub ก่อนมีของจริงมาแทน** คนอื่นกำลังต่ออยู่

## 4. รูปแบบข้อมูลกลาง

| field | รูปแบบ | ตัวอย่าง | หมายเหตุ |
|---|---|---|---|
| พิกัด | `{lat, lng}` | `{"lat": 13.7563, "lng": 100.5018}` | ห้ามใช้ array เด็ดขาด API ภายนอกหลายตัวส่ง `[lng, lat]` มา ต้องแปลงก่อนส่งต่อ |
| เวลา | ISO 8601 UTC ลงท้าย `Z` | `"2026-09-28T01:00:00Z"` | เก็บและส่งเป็น UTC เท่านั้น แปลงเป็นเวลาไทยตอนแสดงผลที่ frontend |
| `trip_id` / `waypoint_id` | UUID | `"a1b2c3d4-..."` | api-backend สร้าง |
| `trip_no` | จำนวนเต็ม นับแยกต่อผู้ใช้ | `1` | แสดงเป็น "Trip 01" ให้คนพูดถึงทริปได้ในแชท |
| `risk_level` | `"LOW"` / `"MEDIUM"` / `"HIGH"` / `null` | | ตัวพิมพ์ใหญ่เท่านั้น ตัดสินจากเกณฑ์ด้านล่าง `null` = ไม่มีข้อมูล (ต้องมี warning) |
| `risk_score` | 0 ถึง 100 / `null` | `48` | เลือกตัวเลขภายในช่วงของ `risk_level`: LOW 0-33, MEDIUM 34-66, HIGH 67-100 ห้ามตัดสิน level จาก score |
| `summary_th` | ข้อความสั้น | `"ฝนปานกลางช่วงนครสวรรค์ ประมาณ 10:00 น."` | risk-decision เขียน ใช้แสดงใน popup สรุปทริป ใส่ทุกครั้ง รวมถึงกรณี NORMAL ที่เส้นทางเป็น MEDIUM |
| `plan_status` | `"NONE"` / `"FRESH"` / `"STALE"` | | ยังไม่เคยแพลน / แผนล่าสุด / ทริปถูกแก้หลังแพลน ต้องแพลนใหม่ |
| `severity` (ของหมุดภัย) | `"LOW"` / `"MEDIUM"` / `"HIGH"` | | MEDIUM = ระดับเฝ้าระวัง, HIGH = ระดับรุนแรงหรือให้อพยพ ตรงกับเกณฑ์ด้านล่าง |
| หมุดระหว่างทาง | ไม่เกิน 5 จุดต่อทริป | | api-backend ตรวจ frontend จำกัดตั้งแต่ฟอร์ม |
| `departure_time` ตอนสร้าง/แก้ทริป | ย้อนหลังได้ไม่เกิน 1 ชม. | | เกินได้ `VALIDATION_ERROR` "เวลาออกเดินทางผ่านไปแล้ว เลือกเวลาในอนาคต" (ทริปย้อนหลังไม่มีพยากรณ์ให้ประเมิน) |
| ต้นทาง = ปลายทาง | ห่างกันน้อยกว่า 0.5 กม. และไม่มีจุดแวะ | | `VALIDATION_ERROR` "ต้นทางกับปลายทางเป็นที่เดียวกัน" (มีจุดแวะ = ทริปวนกลับที่เดิม ทำได้) |
| `recommendation` | `"NORMAL"` / `"DELAY"` / `"REROUTE"` / `"AVOID"` | | risk-decision เป็นคนตัดสิน |
| `hazard_type` | `RAIN` `HEAVY_RAIN` `STRONG_WIND` `FLOOD` `LANDSLIDE_RISK` `STORM` `EARTHQUAKE` | | frontend มีไอคอนครบทุกตัว + ไอคอนสำรองสำหรับค่าที่ไม่รู้จัก |
| `waypoint.kind` | `"ORIGIN"` / `"STOP"` / `"DESTINATION"` | | แท็บขวาของ My Trip แสดงครบทุกจุดรวมต้นทางและปลายทาง |
| `geometry` | array ของ `{lat, lng}` | | ไม่เกิน 500 จุดต่อเส้นทาง (ย่อเส้นก่อนส่ง) |
| หน่วย | ฝน มม./ชม., ลม กม./ชม., อุณหภูมิ °C, ระยะทาง กม., เวลา นาที | | แปลงหน่วยให้เสร็จที่ weather-disaster ที่เดียว |

### เกณฑ์ความเสี่ยง (ค่าตั้งต้น)

| ปัจจัย | LOW | MEDIUM | HIGH |
|---|---|---|---|
| ฝน (มม./ชม.) | ต่ำกว่า 10 | 10 ถึง 35 | มากกว่า 35 |
| ลม (กม./ชม.) | ต่ำกว่า 40 | 40 ถึง 61 | มากกว่า 61 |
| แจ้งเตือนภัยใกล้จุด (ในรัศมี 20 กม.) | ไม่มี | ระดับเฝ้าระวัง | ระดับรุนแรง / อพยพ |

ระดับของจุด = ปัจจัยที่แย่ที่สุด / ระดับของเส้นทาง = จุดที่แย่ที่สุดบนเส้นทาง
ค่าขอบพอดี (เช่น ฝน 35.0) นับเป็นระดับกลาง (MEDIUM)
ต้องใช้ **พยากรณ์ ณ เวลาที่คาดว่าจะไปถึงจุดนั้น** ไม่ใช่อากาศตอนกดแพลน

### คำแนะนำ (เช็คจากบนลงล่าง เจอข้อไหนก่อนใช้ข้อนั้น)

"เส้นทางหลัก" คือเส้นที่เร็วที่สุด (ตัวที่ routing API ให้มาเป็นอันดับแรก)

| เงื่อนไข | recommendation |
|---|---|
| เส้นทางหลักเป็น LOW | `NORMAL` |
| เส้นทางหลักเป็น MEDIUM/HIGH และมีเส้นทางอื่นที่ระดับต่ำกว่า และช้ากว่าเส้นหลักไม่เกิน 50% | `REROUTE` |
| เส้นทางหลักเป็น MEDIUM/HIGH และถ้าออกช้าไป 3 หรือ 6 ชม. ระดับลดลง | `DELAY` |
| เส้นทางหลักเป็น HIGH และไม่เข้าสองข้อบน | `AVOID` |
| เส้นทางหลักเป็น MEDIUM และไม่เข้าข้อไหนข้างบน | `NORMAL` พร้อมข้อความเตือน |

### เส้นทางสำรอง

- ถ้าเส้นทางหลักเป็น MEDIUM/HIGH หรือหาได้มากกว่า 1 เส้นทาง routing-engine ต้องส่ง `route_options` กลับมากกว่า 1 ตัว และมี `is_recommended: true` แค่ตัวเดียว
- routing-engine ส่งทุกเส้นไปให้ risk-decision ประเมินในคำขอเดียว risk-decision เป็นคนเลือกเส้นที่แนะนำ (`recommended_route_id`) และตัดสิน `recommendation` ตามตารางข้างบน routing-engine ห้ามเลือกเอง
- ตัวที่แนะนำ = ระดับความเสี่ยงต่ำสุดก่อน ถ้าเท่ากันเลือกตัวที่เร็วกว่า แต่ถ้าช้ากว่าเส้นหลักเกิน 50% ให้แนะนำเส้นหลักพร้อม `summary_th` เตือนแทน
- ถ้าหาเส้นทางสำรองไม่ได้ ให้ส่งเส้นเดียวพร้อม warning `ALTERNATIVE_ROUTES_UNAVAILABLE` ห้าม error
- frontend แสดงทุก `route_options` ที่ได้ ไม่ใช่แค่ตัวแรก

## 5. Auth

- อีเมล + รหัสผ่าน (ไม่ทำ OAuth)
- api-backend hash รหัสผ่านด้วย bcrypt และไม่ส่ง hash กลับไปใน response ใดๆ
- login สำเร็จได้ JWT อายุ 7 วัน frontend แนบทุก request ด้วย `Authorization: Bearer <token>`
- api-backend ตรวจ token ทุก endpoint ยกเว้น `/auth/*` และ `/health` และตรวจทุกครั้งว่าทริปที่ขอเป็นของคนที่ login อยู่
- service หลังบ้านอื่นเชื่อ api-backend ไม่ต้องตรวจ token เอง ยกเว้น assistant-agent ที่ต้องส่ง token ของผู้ใช้กลับไปเวลาเรียก api-backend (ห้ามมี token พิเศษที่แก้ทริปของใครก็ได้)

## 6. รายการ endpoint

### api-backend (frontend เรียกแค่ชุดนี้ stub ใน `services/api-backend/` ตอบครบทุกเส้นแล้ว)

| Method | Path | ใช้ทำอะไร |
|---|---|---|
| POST | `/api/v1/auth/register` | สมัคร `{email, password}` |
| POST | `/api/v1/auth/login` | ได้ `{token, user}` รหัสผิดทุกแบบ (รวมสั้นกว่า 6 ตัว) ได้ `UNAUTHORIZED` "อีเมลหรือรหัสผ่านไม่ถูกต้อง" |
| GET | `/api/v1/me` | ข้อมูลผู้ใช้ที่ login อยู่ `{user_id, email, display_name}` (`display_name` เป็น `null` ถ้ายังไม่ได้ตั้ง) |
| PATCH | `/api/v1/me` | ตั้งชื่อที่แสดง `{display_name}` ไม่เกิน 40 ตัว ส่งว่างหรือ `null` = ลบชื่อ ได้ผู้ใช้กลับมา น้องกิเลนเรียกผู้ใช้ด้วยชื่อนี้ |
| POST | `/api/v1/me/password` | เปลี่ยนรหัส `{current_password, new_password}` รหัสเดิมผิดได้ `VALIDATION_ERROR` "รหัสผ่านเดิมไม่ถูกต้อง" ได้ `{"changed": true}` จำกัด 10 ครั้งต่อนาที |
| GET | `/api/v1/trips` | ทริปทั้งหมดของผู้ใช้ เรียงตามเวลาออกเดินทาง |
| GET | `/api/v1/trips/upcoming` | ทริปถัดไปที่ยังไม่ถึงเวลาออก หรือ `null` (ใช้ในหน้า Overview) |
| POST | `/api/v1/trips` | สร้างทริป `{origin, destination, departure_time, waypoints[]}` ยังไม่แพลน |
| GET | `/api/v1/trips/{trip_id}` | ทริปเดียว พร้อมแผนล่าสุดถ้ามี |
| PATCH | `/api/v1/trips/{trip_id}` | แก้บาง field (เวลา ต้นทาง ปลายทาง หมุด) แก้แล้วแผนเดิมถือว่าเก่า `plan_status: "STALE"` |
| DELETE | `/api/v1/trips/{trip_id}` | ลบทริป |
| POST | `/api/v1/trips/{trip_id}/plan` | คำนวณแผน ได้ `TripPlan` (ด้านล่าง) |
| GET | `/api/v1/trips/{trip_id}/departures` | ถ้าเลื่อนเวลาออก +3 / +6 ชม. ได้ `{"departures": [{offset_h, risk_level, risk_score, recommendation}]}` ไม่บันทึกอะไร เวลาที่ถามไม่ได้ข้ามไป (การ์ด "ออกเวลาไหนดี" หน้าทริป) |
| POST | `/api/v1/forecast/route` | `{geometry[], departure_time, duration_min}` พยากรณ์ ณ เวลาที่รถผ่าน เก็บจุดทุก 15 กม. ตามเส้น ได้รูปแบบเดียวกับ `POST /forecast/points` ของ weather-disaster (วงฝนตามเส้นทางหน้าทริป) ทริปที่ออกไปแล้วก็ถามได้ |
| GET | `/api/v1/maps/flood/{window}/{z}/{x}/{y}` | ภาพชั้นน้ำท่วม GISTDA (PNG) `window` = `1day` `3days` `7days` `30days` ส่งต่อพร้อม key ฝั่ง server **key ห้ามถึงหน้าเว็บ** |
| GET | `/api/v1/weather/area?lat=&lng=` | สภาพอากาศแบบพื้นที่รอบจุด (ใช้ตอนยังไม่มีทริป) |
| GET | `/api/v1/hazards?min_lat=&min_lng=&max_lat=&max_lng=` | หมุดภัยในกรอบแผนที่ (Safety Map) กรอบกลับด้าน (min > max) ได้ `VALIDATION_ERROR` |
| POST | `/api/v1/assistant/chat` | `{message, history[]}` ได้ `ChatReply` |
| GET | `/api/v1/safety/emergency?hazard_type=` | คำแนะนำฉุกเฉินของภัยชนิดนั้น ได้ `Emergency` (แสดงเมื่อเส้นทางหรือหมุดภัยเป็น HIGH) |
| GET | `/api/v1/places/search?q=` | ค้นสถานที่ในไทยจากชื่อที่พิมพ์ (ช่องปักหมุดในฟอร์มทริป) ได้ `{"places": [Place...]}` ไม่เกิน 5 ตัว (รูปแบบด้านล่าง) |
| GET | `/api/v1/places/nearby?lat=&lng=[&radius_km=&kinds=]` | สถานที่เที่ยวใกล้ตำแหน่ง ได้ `{"places": [NearbyPlace...]}` เรียงจากใกล้ไปไกล ไม่ส่ง `radius_km`/`kinds` = 5 กม. ไม่เกิน 8 ตัว (แบบเดิม) ส่ง = รัศมี 1-20 กม. ไม่เกิน 20 ตัว เลือกกระจายตั้งแต่วงใกล้ถึงวงไกล (หน้าหลักใช้ 20 กม. แชทใช้ตามแนวที่ผู้ใช้ขอ) |

### routing-engine

| Method | Path | ใช้ทำอะไร |
|---|---|---|
| POST | `/api/v1/routes/plan` | `{origin, destination, waypoints[], departure_time}` ได้ทุก field ของ `TripPlan` ยกเว้น `trip_id`, `trip_no` (api-backend เติมเอง) routing-engine เรียก risk-decision เอง |

### risk-decision

| Method | Path | ใช้ทำอะไร |
|---|---|---|
| POST | `/api/v1/risk/evaluate` | ทุกเส้นทางในคำขอเดียว ได้ความเสี่ยงรายจุด/รายเส้น + เส้นที่แนะนำ + recommendation (รูปแบบด้านล่าง) |

### weather-disaster

| Method | Path | ใช้ทำอะไร |
|---|---|---|
| POST | `/api/v1/forecast/points` | `{points: [{lat, lng, time}]}` ได้ `{points: [{lat, lng, forecast}], warnings}` **เรียงตามลำดับที่ส่งมา จำนวนเท่ากัน** จุดที่ไม่มีข้อมูลให้ `forecast: null` |
| GET | `/api/v1/area?lat=&lng=` | สภาพอากาศเป็นตาราง 3x3 จุดรอบตำแหน่ง ห่างกันประมาณ 25 กม. |
| GET | `/api/v1/hazards?min_lat=&min_lng=&max_lat=&max_lng=` | หมุดภัยในกรอบ เปิด GISTDA อยู่มี `flood_window` (`"3days"` / `"7days"` / `null`) บอกชุดน้ำท่วมที่ใช้ หน้าเว็บใช้ชั้นภาพชุดเดียวกัน |

### assistant-agent

| Method | Path | ใช้ทำอะไร |
|---|---|---|
| POST | `/api/v1/chat` | `{message, history[], user_name}` + header `Authorization` ของผู้ใช้ ได้ `ChatReply` (`user_name` = ชื่อในโปรไฟล์ api-backend ใส่ให้ อาจเป็น `null`) |

### safety-knowledge

| Method | Path | ใช้ทำอะไร |
|---|---|---|
| POST | `/api/v1/safety/search` | `{query, hazard_types[], limit}` ได้ `{results: [{doc_id, title_th, snippet_th, source}], warnings}` ไม่เจอได้ `results: []` |
| GET | `/api/v1/safety/emergency?hazard_type=` | ได้ `Emergency` hazard_type ที่ไม่รู้จักได้ `VALIDATION_ERROR` ยังไม่มีคำแนะนำได้ `NOT_FOUND` |

### ตัวอย่างข้อมูลที่ใช้ร่วมกัน

`TripPlan` (คำตอบของ `POST /trips/{id}/plan`) ค่า `risk_level`, `risk_score`, `duration_min` ระดับบนสุดคือของเส้นทางที่แนะนำ

```json
{
  "trip_id": "a1b2c3d4-0000-0000-0000-000000000001",
  "trip_no": 1,
  "departure_time": "2026-09-28T01:00:00Z",
  "arrival_time": "2026-09-28T10:25:00Z",
  "duration_min": 565,
  "risk_level": "MEDIUM",
  "risk_score": 41,
  "recommendation": "REROUTE",
  "summary_th": "เส้นทางหลักเจอฝนหนักช่วงนครสวรรค์ แนะนำเส้นทางสำรอง ช้ากว่า 25 นาที",
  "route_options": [
    { "route_id": "r1", "duration_min": 540, "distance_km": 688, "risk_level": "HIGH", "risk_score": 72, "is_recommended": false, "geometry": [{ "lat": 13.7563, "lng": 100.5018 }] },
    { "route_id": "r2", "duration_min": 565, "distance_km": 702, "risk_level": "MEDIUM", "risk_score": 41, "is_recommended": true, "geometry": [{ "lat": 13.7563, "lng": 100.5018 }] }
  ],
  "waypoints": [
    { "waypoint_id": "wp-0", "kind": "ORIGIN", "name": "กรุงเทพมหานคร", "lat": 13.7563, "lng": 100.5018, "eta": "2026-09-28T01:00:00Z",
      "forecast": { "time": "2026-09-28T01:00:00Z", "rain_mm_per_h": 0.2, "wind_kmh": 9, "temp_c": 27, "condition_th": "มีเมฆบางส่วน" }, "risk_level": "LOW" }
  ],
  "warnings": []
}
```

`ChatReply`

```json
{
  "reply": "เลื่อน Trip 01 ไปเป็นวันที่ 29 ก.ย. 13:00 น. แล้ว และคำนวณเส้นทางใหม่ให้เรียบร้อย ความเสี่ยงลดลงเหลือระดับต่ำ",
  "actions": [{ "type": "TRIP_UPDATED", "trip_id": "a1b2c3d4-0000-0000-0000-000000000001", "trip_no": 1 }],
  "warnings": []
}
```

`actions[].type` ที่ใช้ได้: `TRIP_CREATED`, `TRIP_UPDATED`, `TRIP_DELETED` เจอ action พวกนี้ frontend ต้องโหลดข้อมูลทริปใหม่

`Hazard`

```json
{ "hazard_id": "gdacs-123", "hazard_type": "FLOOD", "severity": "HIGH", "lat": 15.7047, "lng": 100.1372,
  "province": "นครสวรรค์", "title_th": "น้ำท่วมขังหลายพื้นที่", "source": "GDACS", "updated_at": "2026-09-24T03:00:00Z" }
```

`Emergency`

```json
{ "hazard_type": "FLOOD", "steps_th": ["อย่าขับผ่านน้ำที่มองไม่เห็นผิวถนน"],
  "contacts": [{ "name_th": "สายด่วนนิรภัย ปภ.", "phone": "1784" }] }
```

`province` เป็น `null` ได้ เมื่อแหล่งข้อมูลไม่บอกจังหวัด (GDACS, USGS) หน้าเว็บต้องซ่อนส่วนนั้น ห้ามแสดงคำว่า null

`source` ของ Hazard ที่ใช้ได้: `OPEN_METEO`, `GDACS`, `USGS`, `GISTDA`, `THAIWATER`, `TMD`, `DERIVED` (ประเมินเองจากข้อมูลอื่น เช่น เสี่ยงดินถล่มจากฝนสะสม ต้องบอกผู้ใช้ว่าเป็นการประเมิน)

หมุด `source: GISTDA` (น้ำท่วมจากดาวเทียม รวมช่องที่ท่วมเป็น 1 หมุดต่อตำบล) มีเพิ่ม `road_cells: [[lat, lng], ...]` = ช่องที่มีถนนท่วมจริง
- `severity` ตัดสินจากความยาวถนนที่ท่วมในตำบลเท่านั้น: 1 กม. ขึ้นไป `HIGH` · มากกว่า 0 `MEDIUM` · ไม่มีถนนท่วม (ท่วมนา) `LOW`
- ใช้ชุด 3 วันล่าสุดก่อน ถ้าว่าง (ดาวเทียมยังไม่มีภาพใหม่) ใช้ชุด 7 วัน · ไม่มี `GISTDA_API_KEY` = ไม่มีหมุดชนิดนี้ ไม่ใช่ error
คำตอบของ `GET /hazards`: `{"hazards": [Hazard...], "warnings": []}`

หมุด `source: OPEN_METEO` (`RAIN`, `HEAVY_RAIN`, `STRONG_WIND`) คือ**อากาศชั่วโมงนี้** มีไว้ให้ Safety Map แสดงว่าตอนนี้ฝนตก/ลมแรงที่ไหน ระดับ `severity` ใช้เกณฑ์ฝน/ลมในหัวข้อ 4 (ฝนเบา 2 ถึง 10 มม./ชม. เป็น `RAIN` LOW) **risk-decision ต้องข้ามหมุดชนิดนี้** เพราะใช้พยากรณ์ ณ เวลาที่ไปถึงอยู่แล้ว ถ้านับซ้ำจะได้ความเสี่ยงของ "ตอนนี้" แทน "ตอนที่ไปถึง"

`Place` (คำตอบของ `GET /places/search`)

```json
{ "places": [ { "name": "กรุงเทพมหานคร", "detail": "กรุงเทพมหานคร", "lat": 13.7525, "lng": 100.4935 } ] }
```

- `q` สั้นกว่า 2 ตัวอักษรได้ `VALIDATION_ERROR` · ไม่เจอได้ `places: []` · ทุกผลต้องอยู่ในประเทศไทย
- คำย่อที่คนไทยพิมพ์บ่อยต้องเจอ เช่น `กทม` > กรุงเทพมหานคร, `โคราช` > นครราชสีมา
- บริการค้นสถานที่ล่มหรือช้าได้ `UPSTREAM_ERROR` / `UPSTREAM_TIMEOUT` หน้าเว็บบอกผู้ใช้ให้ปักหมุดบนแผนที่แทน ห้ามค้าง
- ใช้ Photon (`photon.komoot.io`) ซึ่งอนุญาตให้ค้นแบบพิมพ์ไปเจอไป ห้ามใช้ Nominatim ทำแบบนี้ (ผิดเงื่อนไขการใช้งานของเขา)

`NearbyPlace` (คำตอบของ `GET /places/nearby`) = `Place` + `kind_th`

`kinds` (คั่นด้วยจุลภาค ไม่ส่ง = `attraction`): `attraction` วัด พิพิธภัณฑ์ อนุสาวรีย์ จุดชมวิว · `cafe` · `market` ตลาด ถนนคนเดิน · `park` · `mall` · `nightlife` บาร์ ผับ · `waterfall` น้ำตก หมวดที่ไม่รู้จักหรือรัศมีนอก 1-20 ได้ `VALIDATION_ERROR`

```json
{ "places": [ { "name": "ประตูท่าแพ", "detail": null, "lat": 18.7877, "lng": 98.9933, "kind_th": "สถานที่ท่องเที่ยว" } ] }
```

- ดึงจาก Overpass (OpenStreetMap) ครั้งเดียวต่อคำขอ ใช้กรอบสี่เหลี่ยม (`[bbox:...]`) แล้วตัดตามรัศมีจริงทีหลัง: `tourism` = attraction / viewpoint / museum / zoo / theme_park และ `historic` = monument / temple / ruins ที่มีชื่อ ใช้ `name:th` ถ้ามี
- Overpass ตอบ error (504/429) ใช้ Photon ค้นตามหมวดแทน (เก็บ cache แค่ 1 ชม.) และข้าม Overpass ไป 5 นาที · Overpass ตอบ 200 แต่มี `remark` ว่าหมดเวลา ถือว่าพัง ห้ามเก็บลง cache ว่า "ไม่มีที่เที่ยว"
- **ประหยัดโควตา**: รัศมี 5 กม. ไม่เกิน 8 ตัว cache ตามพิกัดที่ปัดเป็นทศนิยม 2 ตำแหน่ง (ประมาณ 1 กม.) นาน 24 ชม. ไม่เรียก LLM
- นอกประเทศไทยได้ `OUT_OF_THAILAND` · Overpass ล่มหรือช้าได้ `UPSTREAM_ERROR` / `UPSTREAM_TIMEOUT` หน้าเว็บแสดงแผนที่และอากาศต่อไปโดยไม่มีหมุดสถานที่ ห้ามทำให้ทั้งการ์ดพัง

คำตอบของ `GET /weather/area` และ `GET /area`

```json
{ "center": { "lat": 13.75, "lng": 100.5 },
  "cells": [ { "lat": 13.53, "lng": 100.28, "forecast": { "time": "...Z", "rain_mm_per_h": 0.2, "wind_kmh": 9, "temp_c": 29, "condition_th": "มีเมฆบางส่วน" } } ],
  "updated_at": "2026-09-24T03:00:00Z", "warnings": [] }
```

คำขอและคำตอบของ `POST /risk/evaluate` (routing-engine ส่งทุกเส้นในครั้งเดียว risk-decision ลองเลื่อนเวลาออก 3 และ 6 ชม. เองเพื่อตัดสิน `DELAY`)

```json
{ "routes": [ { "route_id": "r1", "duration_min": 540, "points": [ { "lat": 13.75, "lng": 100.5, "eta": "2026-09-28T01:00:00Z" } ],
                "geometry": [ { "lat": 13.75, "lng": 100.5 } ] } ] }
```

`geometry` ไม่บังคับ (routing-engine ส่งเส้นเต็มมาด้วย) มี `geometry` แล้ว หมุดน้ำท่วม GISTDA นับว่าโดนเส้นทางก็ต่อเมื่อเส้นทางผ่านห่างช่อง `road_cells` ไม่เกิน 0.5 กม. (ใส่ไว้ที่จุดตรวจที่ใกล้ที่สุด) ไม่มี `geometry` ใช้รัศมีแบบเดิม

```json
{ "routes": [ { "route_id": "r1", "risk_level": "MEDIUM", "risk_score": 41,
                "points": [ { "lat": 13.75, "lng": 100.5, "eta": "...Z", "forecast": { }, "hazards": [], "risk_level": "LOW", "risk_score": 12 } ] } ],
  "recommended_route_id": "r1", "recommendation": "NORMAL",
  "summary_th": "ฝนปานกลางบางช่วง ขับช้าลงและเปิดไฟหน้า", "warnings": [] }
```

## 7. กฎฝั่ง frontend (3 คนทำในแอปเดียวกัน)

- เจ้าของโมดูล 1 ดูแล `package.json`, lockfile, `next.config`, `app/layout`, `app/globals.css`, หน้าหลัก (`app/page.tsx`), `app/login`, `components/` ที่ใช้ร่วมกัน (`Shell`, `Icon`, `Map`, `MapView`, `ui`, แชทลอย `ChatFab` + `ChatDrawer`), `lib/` ทั้งหมด และ `public/assets`
- โมดูล 2 ดูแล `app/trips` + `components/PlanTrip.tsx` + `components/trip.tsx` · โมดูล 3 ดูแล `app/map` + `app/assistant` · โมดูล 9 ดูแล `app/emergency`
- หน้าตาตามแบบในเครื่องเจ้าของโปรเจกต์ (ภาพตัวอย่างอยู่ที่ `public/assets/showcase/`) สีและขนาดใช้ตัวแปรใน `globals.css` เท่านั้น ห้ามใส่สีตายตัวในหน้า
- คนอื่นอยากเพิ่ม package ให้บอกเจ้าของโมดูล 1 ก่อน ห้ามต่างคนต่างลง แล้วห้ามแก้ lockfile ด้วยมือตอน conflict
- browser เรียก `/api/v1/...` แบบ relative path แล้วให้ Next.js ส่งต่อไปที่ `API_INTERNAL_URL` ฝั่ง server (เลี่ยงปัญหา CORS ทั้งหมด) ใช้ route handler `app/api/v1/[...path]/route.ts` ที่อ่าน env ตอนรัน **ไม่ใช้ `rewrites` ใน `next.config`** เพราะค่านั้นถูกฝังตอน build แล้วใน Docker จะชี้ผิดที่
- แผนที่ใช้ Leaflet (`react-leaflet`) ตัวเดียวทั้งเว็บ ผ่าน component กลาง `components/Map` (โหลด `MapView` แบบไม่ทำตอน server) ห้ามใครลงไลบรารีแผนที่ตัวอื่นเพิ่ม
- แปลงเวลาเป็นเวลาไทยด้วย `timeZone: "Asia/Bangkok"` ทุกครั้ง ห้ามพึ่ง timezone ของเครื่องที่เปิดเว็บ
- ทุกการ์ดและแผนที่ที่ดึงข้อมูลต้องมี 3 สถานะ: กำลังโหลด / โหลดไม่สำเร็จพร้อมปุ่มลองใหม่ / ไม่มีข้อมูล

## 8. Docker และ env

- ทุก service มี Dockerfile ของตัวเอง ฟังพอร์ต 8000 ภายใน และมี `.env.example` ในโฟลเดอร์ (ค่าตัวอย่างเท่านั้น)
- `.env` จริงอยู่นอก git เสมอ `docker-compose.yml`, `Makefile`, `.env.example` ที่ root เป็นของกลาง แก้ผ่านเจ้าของโปรเจกต์
- `DEMO_MODE=true` ทำให้ weather-disaster และ routing-engine ใช้ข้อมูลที่บันทึกไว้แทนการเรียก API ภายนอก (ไว้ใช้ตอนเน็ตไม่ดีวันนำเสนอ ดู RUNBOOK)
- เปิดดูผลรวมได้ด้วย `make up` / `make health` / `make smoke` (ใครไม่มี `make` บน Windows ดูคำสั่งเทียบใน README)

## 9. Hosting

- นำเสนอด้วย `docker compose up` บนเครื่องที่ใช้ demo เป็นหลัก
- ลิงก์ให้คนนอกใช้: Render ตาม `render.yaml` ทั้งระบบเป็น web service เดียว (`deploy/render/Dockerfile` รวมบริการ Python 6 ตัวบน `127.0.0.1:8001-8006` + หน้าเว็บที่พอร์ต `$PORT`) + Render Postgres วิธีทำอยู่ใน `deploy/render/README.md`
- บริการใหม่ต้องรันได้ทั้งใน docker compose (`http://<ชื่อบริการ>:8000`) และใน container เดียวของ Render (`http://127.0.0.1:800x`) อ่านที่อยู่จาก env เท่านั้น ห้ามเขียนตายตัว

## 10. LLM (assistant-agent และ risk-decision ถ้าใช้เขียนคำอธิบาย)

- ใช้ไลบรารี `openai` ตัวเดียว เปลี่ยนผู้ให้บริการด้วย `base_url` เท่านั้น
- ลำดับผู้ให้บริการ: `LLM_PRIMARY` แล้ว `LLM_FALLBACK` (ใส่หลายตัวคั่นด้วยจุลภาคได้ เช่น `gemini,groq2`) ตัวละ `<ชื่อ>_API_KEY` `<ชื่อ>_MODEL` `<ชื่อ>_BASE_URL` ชื่อโมเดลอ่านจาก env เสมอ ค่าที่ใช้อยู่ดู `.env.example`
- คำสั่งระบบทั้งหมด (prompt + ข้อมูลทริป + เอกสาร) ต้องรวมเป็น `system` **ข้อความเดียว** เพราะ Gemini อ่านแค่ system อันสุดท้าย
- Gemini 3 ต้องได้ `extra_content` (thought_signature) ของ tool call คืนไปด้วยทุกครั้ง ไม่งั้นรอบถัดไปตอบ 400
- ตอน dev แต่ละคนใช้ key ของตัวเอง key กลางเก็บไว้ใช้วันนำเสนอ
- การตัดสินใจเรื่องความเสี่ยงต้องมาจากกฎในหัวข้อ 4 เสมอ LLM มีหน้าที่แค่เรียบเรียงคำอธิบาย ห้ามให้ LLM ตัดสินระดับความเสี่ยงเอง

## 11. Git flow

- `main` เป็น branch หลัก (default) merge เข้าต้องมี 2 approval
- `dev` เป็น branch รวมงาน merge เข้าต้องมี 1 approval
- ห้าม push ตรงเข้า `main` หรือ `dev`
- ทุกคนทำงานใน branch ของตัวเอง แตกจาก `dev`: `feature/<module-slug>/<ชื่อ>` เช่น `feature/routing-engine/somchai`
  module-slug: `web-overview`, `web-mytrip`, `web-safety-assistant`, `api-backend`, `routing-engine`, `weather-disaster`, `risk-decision`, `assistant-agent`, `safety-knowledge`
- commit: `<type>(<module-slug>): <ทำอะไร>` type คือ `feat` `fix` `test` `docs` `refactor` `chore`
- **ตอนเปิด PR ช่อง base จะเด้งเป็น `main` เสมอ (เพราะ `main` เป็น default) ต้องเปลี่ยนเป็น `dev` เองทุกครั้ง** ถ้าลืม PR จะติดกฎ 2 approval ของ `main` และถูกปิดให้เปิดใหม่
- เจ้าของโปรเจกต์รีวิวทุก PR ก่อนเข้า `dev` และ `main` (เป็น code owner คนเดียวใน `.github/CODEOWNERS` GitHub จึงไม่ยอมให้ merge จนกว่าเขาจะ approve)
- repo ตั้งให้ merge แบบ "Create a merge commit" อย่างเดียว เพื่อเก็บ commit ของแต่ละคนไว้ครบเป็นหลักฐานการทำงาน
- ต้องแตะไฟล์นอกโฟลเดอร์ตัวเอง: ขอเจ้าของโฟลเดอร์นั้นก่อนเปิด PR และแท็กเขาใน PR ห้ามพุชหรือ merge มั่ว
- `dev` ต้องรันได้ตลอดเวลา ถ้า merge แล้วพังให้ revert ทันที (`git revert -m 1 <merge commit>`) ห้าม force push
- ห้าม commit `.env`, API key, ไฟล์ข้อมูลหรือโมเดลขนาดใหญ่
- `git add` เฉพาะโฟลเดอร์ของตัวเอง เช่น `git add services/routing-engine/` ห้ามใช้ `git add .` แล้วดู `git status` ก่อน commit ทุกครั้งว่ามีแต่ไฟล์ที่ตั้งใจ
- ก่อนขอ merge `dev` เข้า `main` ต้องผ่าน `make health` และ `make smoke`
