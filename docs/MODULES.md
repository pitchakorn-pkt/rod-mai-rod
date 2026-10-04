# MODULES.md - แบ่งงาน 8 คน 9 โมดูล

> บันทึกการแบ่งงานช่วงพัฒนา (ก.ย. 2569) เก็บไว้เป็นประวัติ สถานะล่าสุดของระบบ ไฟล์จริงของแต่ละหน้า และวิธีรัน ดู [`README.md`](../README.md)

ไม่มีกำหนดวัน คิวงานของแต่ละคนและใครรอใครอยู่ใน [`PLAN.md`](PLAN.md) เสร็จงานหนึ่งแล้วหยิบงานถัดไปได้ทันที
ทุกโมดูลมี stub ที่ตอบข้อมูลตัวอย่างตามรูปแบบจริงและเรียกหากันจริงแล้ว **ไม่มีใครต้องรอใครเพื่อเริ่มงาน** จุดที่ต้องเติมมี `TODO(<module-slug>)` กำกับไว้
README ในโฟลเดอร์ของแต่ละโมดูลมีรายการ "จุดที่คนส่วนใหญ่พลาด" อ่านก่อนเขียนบรรทัดแรก

## รายชื่อโมดูล

| # | โมดูล | โฟลเดอร์ | module-slug | ผู้รับผิดชอบ |
|---|---|---|---|---|
| 1 | Frontend: โครงเว็บ + Login + Overview + ของกลาง `shared/` | `apps/web/` (โครง), `app/login/`, `app/overview/` | `web-overview` | Patcharanat Budploy (@Patcharanat23) |
| 2 | Frontend: My Trip | `apps/web/app/my-trip/` | `web-mytrip` | Jirapa Gongmool (@jirapa-gm) |
| 3 | Frontend: Safety Map + หน้าแชท | `apps/web/app/safety-map/`, `app/assistant/` | `web-safety-assistant` | Suphakorn Nonthong (@SoSick41) |
| 4 | API Gateway + Auth + ฐานข้อมูล | `services/api-backend/` | `api-backend` | Karmolputh Phatarathorn (@Chakamon02) |
| 5 | Routing Engine + เส้นทางสำรอง | `services/routing-engine/` | `routing-engine` | Pitchakorn Phuadkhunthod (@pitchakorn-pkt) |
| 6 | Weather & Disaster | `services/weather-disaster/` | `weather-disaster` | Pathumporn Jorrapong (@pathumpornjorrapong-ops) |
| 7 | Risk & Decision | `services/risk-decision/` | `risk-decision` | Jakkrich Sriraksa (@jakkrich0912-web) |
| 8 | Assistant Agent (แชท + สั่งแก้ทริป) | `services/assistant-agent/` | `assistant-agent` | Patcharanat Budploy (@Patcharanat23) |
| 9 | Safety Knowledge (คำแนะนำความปลอดภัย + ฉุกเฉิน) | `services/safety-knowledge/` | `safety-knowledge` | Phitphibul Phrompheak (@phitphibul67) |

## อันดับความยาก

| อันดับ | โมดูล | ระดับ | ยากตรงไหน | ผู้รับผิดชอบ |
|---|---|---|---|---|
| 1 | 8 assistant-agent | ยากมาก | LLM + function calling ต้องแก้ข้อมูลจริงให้ถูกทุกครั้ง, แปลง "พรุ่งนี้/ช่วงบ่าย" เป็นเวลาจริงตามเวลาไทย, ตัวแยกคำสั่งสำรองตอน LLM ล่ม | Patcharanat Budploy (@Patcharanat23) |
| 2 | 5 routing-engine | ยาก | แกะผลจาก OSRM, เก็บจุดตัวอย่างทุก 20 กม. พร้อมเวลาถึงสะสม, ย่อเส้น, cache, fixture | Pitchakorn Phuadkhunthod (@pitchakorn-pkt) |
| 3 | 4 api-backend | ยาก | Postgres + bcrypt + JWT, ตรวจเจ้าของทริปทุกเส้น, endpoint เยอะ และเป็นจุดเดียวที่ห้ามล่ม | Karmolputh Phatarathorn (@Chakamon02) |
| 4 | 2 web-mytrip | กลางค่อนยาก | หน้าที่ซับซ้อนที่สุด ฟอร์ม + หลายเส้นทาง + popup + แท็บขวา + state หลายตัว | Jirapa Gongmool (@jirapa-gm) |
| 5 | 6 weather-disaster | กลาง | เรียก Open-Meteo / GDACS / USGS, timezone, หน่วย, cache, แหล่งหนึ่งพังห้ามลากทั้งหมด | Pathumporn Jorrapong (@pathumpornjorrapong-ops) |
| 6 | 7 risk-decision | กลาง | เกณฑ์หลักและเทสต์ทำไว้แล้ว เหลือหมุดภัยในรัศมี 20 กม., `risk_score`, `summary_th` และ `DELAY` ถ้าเหลือเวลา | Jakkrich Sriraksa (@jakkrich0912-web) |
| 7 | 9 safety-knowledge | ค่อนง่าย | เขียนเอกสารความปลอดภัยพร้อมแหล่งที่มา + ทำให้ค้นภาษาไทยได้ (ไม่มีเว้นวรรค) | Phitphibul Phrompheak (@phitphibul67) |
| 8 | 3 web-safety-assistant | ง่าย | สองหน้าใช้งานได้แล้วในระดับพื้นฐาน เหลือ debounce, ไอคอน, การ์ด actions, ปุ่มตัวอย่าง | Suphakorn Nonthong (@SoSick41) |

## ใครรอใคร (สำหรับของจริง ตอนนี้ทุกคนต่อ stub ได้เลย)

```
weather-disaster ──> risk-decision ──> routing-engine ──> api-backend ──> frontend
                                                          api-backend <──> assistant-agent
safety-knowledge ──> assistant-agent, api-backend (คำแนะนำฉุกเฉิน)
```

**ลำดับแนะนำ**

1. โมดูล 4 ต่อ Postgres + auth จริง โดยยังตอบรูปแบบเดิม frontend จะไม่รู้สึกถึงการเปลี่ยน
2. โมดูล 6 ต่อ Open-Meteo จริงก่อนแหล่งอื่น เพราะ 7 และ 5 ต้องใช้
3. ที่เหลือทำพร้อมกันได้หมด

## ทางถอยถ้าไม่ทัน

ดู `docs/RUNBOOK.md` หัวข้อ E ทุกโมดูลมีเวอร์ชันเล็กที่ยังสาธิตได้ ตัดสินใจถอยให้เร็ว อย่ารอจนใกล้นำเสนอ
