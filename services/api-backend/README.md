# api-backend (โมดูล 4)

**หน้าที่**: ประตูเดียวที่ frontend คุยด้วย ดูแล login/JWT, ฐานข้อมูลผู้ใช้และทริป, และส่งต่องานไป routing-engine / weather-disaster / assistant-agent
**ผู้รับผิดชอบ**: Karmolputh Phatarathorn (@Chakamon02)
**branch**: `feature/api-backend/<ชื่อ>`
**endpoint**: ทั้งชุด api-backend ใน `docs/CONTRACT.md` หัวข้อ 6
**เรียกใคร**: postgres, routing-engine, weather-disaster, assistant-agent, safety-knowledge, Photon (ค้นสถานที่), Overpass (ที่เที่ยวใกล้ตัว), Google (กุญแจตรวจ ID token)
**ใครเรียกเรา**: frontend, assistant-agent (เรียกกลับมาแก้ทริป)

## ทำอะไรได้แล้วตอนนี้

| เรื่อง | รายละเอียด |
|---|---|
| ฐานข้อมูล | Postgres ตาราง `users` (`email`, `password_hash`, `display_name`) และ `trips` สร้างตารางเองตอนเริ่ม (`db.SCHEMA` คอลัมน์ใหม่ใช้ `ADD COLUMN IF NOT EXISTS` ไม่ต้อง reset) · สร้างบัญชี `demo@example.com` / `demo1234` ให้อัตโนมัติ |
| login | อีเมล + รหัสผ่าน (bcrypt 10 รอบ hash เก่า 12 รอบแปลงให้ตอน login) · **Google**: `POST /auth/google` ตรวจ ID token ด้วยกุญแจสาธารณะของ Google (PyJWT[crypto]) ต้องออกให้ `GOOGLE_CLIENT_ID` และอีเมลยืนยันแล้ว อีเมลเดียวกับบัญชีเดิม = เข้าบัญชีเดิม ครั้งแรกสร้างบัญชีพร้อมชื่อจาก Google · `GET /auth/config` บอกหน้าเว็บว่าเปิด Google ไหม |
| โปรไฟล์ | `PATCH /me` ตั้งชื่อที่ให้น้องกิเลนเรียก (ไม่เกิน 40 ตัว) · `POST /me/password` เปลี่ยนรหัสผ่าน |
| ทริป | สร้าง/แก้/ลบ, `trip_no` แยกต่อผู้ใช้, จุดแวะไม่เกิน 5, ห้ามเวลาออกย้อนหลังเกิน 1 ชม., แก้แล้ว `plan_status = STALE` · `/plan` เรียก routing-engine · `/departures` เทียบออกตามเวลา / +3 / +6 ชม. |
| ข้อมูลอากาศและภัย | `/weather/area`, `/forecast/route` (ฝนตามเส้นทาง), `/hazards`, `/maps/flood/...` (ส่งต่อภาพชั้นน้ำท่วม) |
| ค้นสถานที่ | `/places/search` ผ่าน Photon กรองเฉพาะไทย · ขยายคำย่อก่อนค้น (`ABBREVIATIONS` ใน `places.py` เช่น มทร, ราชมงคล, มก, รพ และแบบ "มทร.ธัญบุรี") |
| ที่เที่ยวรอบตัว | `/places/nearby` ผ่าน Overpass cache รายวัน สำรองด้วย Photon · รัศมีกว้างเลือกกระจาย 4 วงจากใกล้ถึงไกล (`NEARBY_RINGS`) ไม่กองอยู่จุดเดียว |
| แชท | `/assistant/chat` ส่ง token ของผู้ใช้ + `user_name` + `location` (GPS ถ้ามี) ไป assistant-agent |
| กันโหลด | rate limit login/เปลี่ยนรหัส 10 ครั้ง/นาทีต่อ IP, แชท 10 ข้อความ/นาทีต่อคน · ใช้ HTTP client ร่วมกันทุกคำขอ (`envelope.call`) |

เทสต์ 76 ข้อ (ต้องมี Postgres) รันกับฐานข้อมูลทดสอบแยก: `DATABASE_URL=postgresql://rodmairod:changeme@localhost:5433/rmr_test pytest -q` ไม่งั้นจะสร้างทริปขยะในบัญชี demo

## รันเดี่ยว

```bash
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
sh ../../scripts/smoke.sh http://localhost:8000
```

## จุดที่คนส่วนใหญ่พลาด (อ่านก่อนเขียน)

1. **ลืมเช็คว่าทริปเป็นของใคร** แค่ตรวจว่า login แล้วไม่พอ ต้องตรวจ `trip.user_id == ผู้ใช้ใน token` ทุก endpoint ที่มี `{trip_id}` ไม่งั้นใครเดา id ได้ก็แก้ทริปคนอื่นได้ (ใช้ `get_owned_trip`)
2. **ลำดับ route ใน FastAPI** `/trips/upcoming` ต้องประกาศก่อน `/trips/{trip_id}` ไม่งั้นคำว่า "upcoming" จะถูกมองเป็น trip_id
3. **error ของ FastAPI ไม่ใช่รูปแบบเรา** ค่าเริ่มต้นตอบ `{"detail": ...}` ต้องใช้ handler ใน `envelope.py` ต่อไป อย่าลบทิ้งตอนเขียนใหม่
4. **ส่ง password hash กลับไปใน response** เวลา return object ผู้ใช้จากฐานข้อมูลตรงๆ hash ติดไปด้วย ต้องเลือก field เอง
5. **เก็บเวลาผิด timezone** คอลัมน์เวลาใน Postgres ใช้ `timestamptz` แล้วเก็บเป็น UTC ถ้าได้เวลาที่ไม่มี timezone มา ให้ตอบ `VALIDATION_ERROR` (ทำไว้แล้ว)
6. **`trip_no` ซ้ำ** ต้องนับแยกต่อผู้ใช้ และตั้ง unique (`user_id`, `trip_no`) ในฐานข้อมูล แชทใช้เลขนี้อ้างถึงทริป
7. **แก้ทริปแล้วไม่บอกว่าแผนเก่า** PATCH อะไรก็ตามต้องตั้ง `plan_status = "STALE"` หน้า My Trip และ assistant ใช้ค่านี้ตัดสินว่าต้องแพลนใหม่
8. **เรียก service อื่นโดยไม่ตั้ง timeout** ใช้ `httpx` พร้อม timeout ตาม CONTRACT หัวข้อ 3 และส่ง `X-Request-ID` ต่อทุกครั้ง ถ้าปลายทาง timeout ให้ตอบ `UPSTREAM_TIMEOUT` ไม่ใช่ปล่อยค้าง
9. **ส่ง `Authorization` ของผู้ใช้ไปทุก service** ส่งไปแค่ assistant-agent (ต้องใช้เรียกกลับ) ตัวอื่นไม่ต้องรู้
10. **`/health` ตอบ ok ทั้งที่ต่อฐานข้อมูลไม่ได้** ของจริงให้ `/health` ลอง `SELECT 1` ด้วย ถ้าไม่ผ่านให้ตอบ 503 และถ้าตอนเริ่มต่อฐานข้อมูลไม่ได้ ให้ process จบการทำงาน (exit) ไปเลย Docker จะ restart ให้เฉพาะตอน process ตาย ไม่ได้ restart ตอน health ไม่ผ่าน
11. **เติม `summary_th` เอง** ข้อความสรุปมาจาก routing-engine (ซึ่งได้จาก risk-decision) ส่งต่อตามนั้น อย่าแต่งใหม่
12. **แก้ schema เงียบๆ** ทุกครั้งที่เปลี่ยนตาราง ประกาศในกลุ่ม คนอื่นต้อง `make reset`

## ถือว่าเสร็จเมื่อ

- `make smoke` ผ่านโดยข้อมูลอยู่ใน Postgres จริง (restart แล้วทริปยังอยู่)
- `POST /trips/{id}/plan` เรียก routing-engine จริงและบันทึกแผนลงฐานข้อมูล
- ผู้ใช้ A แก้/ดูทริปของผู้ใช้ B ไม่ได้ (ได้ `FORBIDDEN`)
