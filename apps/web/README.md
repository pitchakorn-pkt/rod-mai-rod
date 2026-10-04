# apps/web - Frontend (โมดูล 1, 2, 3, 9 ทำในแอปเดียวกัน)

Next.js 15 (App Router) + TypeScript + Leaflet ดีไซน์ธีมกระจกเข้ม (Dark Glass) มาสคอตน้องกิเลน

```bash
cd apps/web
npm ci
cp .env.example .env.local   # ชี้ไป api-backend ที่ http://localhost:8001
npm run dev                  # http://localhost:3000
npm run typecheck            # ต้องผ่านก่อนเปิด PR
npm run build                # ต้องผ่านก่อนเปิด PR (Docker build แบบนี้)
```

บัญชีทดลอง `demo@example.com` / `demo1234` (api-backend สร้างให้ตอนเริ่ม) หรือสมัครใหม่จากหน้า login หรือกดเข้าสู่ระบบด้วย Google (ต้องตั้ง `GOOGLE_CLIENT_ID` ใน `.env` ของ api-backend)

## หน้าในเว็บ

| path | ไฟล์ | ต้อง login |
|---|---|---|
| `/login` | `app/login/page.tsx` | ไม่ |
| `/` หน้าหลัก | `app/page.tsx` | ต้อง |
| `/trips` ทริปของฉัน (`?id=` เปิดทริปนั้น, `?new=1` เปิดฟอร์มทริปใหม่) | `app/trips/page.tsx` | ต้อง |
| `/map` แผนที่ความเสี่ยง | `app/map/page.tsx` | ต้อง |
| `/emergency` ฉุกเฉิน | `app/emergency/page.tsx` | ต้อง |
| `/assistant` คุยกับน้องกิเลน | `app/assistant/page.tsx` | ต้อง |
| `/privacy`, `/terms` | `app/privacy/`, `app/terms/` + `components/Legal.tsx` | ไม่ (Google ลิงก์มาจากหน้าต่าง login) |
| `/health` | `app/health/` | ไม่ |

หน้าที่ไม่ต้อง login กำหนดใน `PUBLIC_PATHS` ของ `components/Shell.tsx` เพิ่มหน้าสาธารณะใหม่ต้องเพิ่มที่นี่ ไม่งั้นจะถูกพาไปหน้า login

## ใครดูแลไฟล์ไหน

| ไฟล์ | หน้า | โมดูล |
|---|---|---|
| `app/layout.tsx`, `app/globals.css`, `app/page.tsx`, `app/login/`, `app/privacy/`, `app/terms/`, `components/{Shell,Icon,Map,MapView,ui,ChatFab,ChatDrawer,Legal}.tsx`, `lib/*`, `public/assets/`, `public/fonts/`, `app/api/v1/`, `app/health/` | โครงเว็บ หน้าหลัก login แชทลอย นโยบาย/เงื่อนไข ของกลาง | 1 |
| `app/trips/`, `components/PlanTrip.tsx`, `components/trip.tsx` | ทริปของฉัน + ฟอร์มวางแผน + เช็กลิสต์ + ออกเวลาไหนดี | 2 |
| `app/map/`, `app/assistant/` | แผนที่ความเสี่ยง + คุยกับน้องกิเลนเต็มหน้า | 3 |
| `app/emergency/` | ฉุกเฉิน (สมุดเบอร์ + วิธีรับมือ) | 9 |

หน้าตาต้องตรงกับภาพใน `public/assets/showcase/` (ถ่ายจากเว็บจริง) **ห้ามเปลี่ยนสี ขนาด หรือข้อความเอง** ถ้าจำเป็นต้องเปลี่ยนให้คุยกับเจ้าของโมดูล 1 ก่อน

ภาพใน `public/assets/showcase/` (`home`, `trips`, `map`, `chat`, `emergency` `.webp` ขนาด 1280×800) เป็นภาพที่หมุนโชว์ในหน้า login ถ่ายใหม่ล่าสุด 4 ต.ค. 2569 ด้วยธีมมืด บัญชีชั่วคราวชื่อ "นักเดินทาง" และตำแหน่งกรุงเทพ (ไม่ให้ภาพมีชื่อหรือตำแหน่งจริงของใคร) แก้หน้าตาเว็บจนภาพไม่ตรงแล้วให้ถ่ายใหม่ชุดเดียวกันทั้ง 5 ภาพ

## สิ่งที่เว็บต้องทำเสมอ (ห้ามพัง)

- `GET /health` ตอบ `{"status":"ok","service":"web"}` · ฟังพอร์ต 8000 ใน container (compose map ออกเป็น 3000)
- ส่งต่อ `/api/v1/*` ไปที่ `API_INTERNAL_URL` ด้วย `app/api/v1/[...path]/route.ts` ที่อ่าน env ตอนรัน ส่ง `Authorization`, `X-Request-ID`, **`X-Forwarded-For`** ต่อ (api-backend จำกัด login ต่อ IP ไม่ส่งต่อ = ทุกคนนับเป็น IP เดียว) ภาพชั้นน้ำท่วมส่งต่อเป็นไฟล์ภาพ
- **อย่าใช้ `rewrites` ใน `next.config`** ค่าในนั้นถูกฝังตอน build ใน Docker จะชี้ผิดที่
- browser เรียก api-backend ผ่าน `api()` ใน `lib/api.ts` เท่านั้น (แนบ token, แกะ `{data, error}`, 401 พากลับหน้า login)

## ระบบที่ควรรู้ก่อนแก้

| เรื่อง | อยู่ที่ไหน | สรุป |
|---|---|---|
| ฟอนต์ | `public/fonts/` + `@font-face` ต้น `globals.css` | Noto Sans Thai เก็บไฟล์ไว้ใน repo (ไม่ใช้ `next/font` เพราะ build เคยพังตอนโหลดจาก Google) แยกไฟล์ไทย / ละติน ด้วย `unicode-range` ส่วนละตินตั้ง `ascent-override` ให้ตัวเลขและอังกฤษอยู่กลางกล่อง ใช้ผ่าน `var(--font-main)` · ตัวเลขกว้างเท่ากัน (`tabular-nums`) |
| แผนที่พื้นหลัง | `components/MapView.tsx` | Esri World Street Map ชื่อทุกประเทศเป็นอังกฤษภาษาเดียว ไม่ต้องใช้ key (OpenStreetMap แสดงภาษาท้องถิ่นปนกัน, CARTO ต้องใช้ key แล้ว) |
| ตำแหน่ง GPS | `lib/store.tsx` (`locate()`, `here`, `hereFallback`) | ขอตำแหน่งตอนเปิดเว็บ (รอได้ 15 วิ) ระหว่างรอใช้กรุงเทพ `hereFallback = true` = ยังไม่ใช่ตำแหน่งจริง ห้ามใช้เป็นต้นทางเงียบๆ · ฟอร์มทริปใหม่เติมต้นทาง "ตำแหน่งปัจจุบัน" ให้เฉพาะตอนได้ตำแหน่งจริง และไม่ทับถ้าผู้ใช้เลือกต้นทางเองแล้ว · แชทส่ง `location` ไปด้วยเฉพาะตอนได้ตำแหน่งจริง |
| แชท | `lib/chat.tsx` | ประวัติเก็บใน localStorage แยกตามบัญชี · ส่ง history 10 ข้อความล่าสุด · คำตอบที่สร้าง/แก้ทริปสำเร็จจริงแนบ "(ระบบ: สร้าง Trip 02 สำเร็จ)" ไปใน history (ผู้ใช้ไม่เห็น) ให้น้องกิเลนรู้ว่ารอบก่อนทำจริงไหม |
| login ด้วย Google | `GoogleButton` ใน `app/login/page.tsx` | ถาม `GET /auth/config` ก่อน ได้ client id ค่อยโหลดสคริปต์ `accounts.google.com/gsi/client` แล้ววาดปุ่ม ได้ ID token ส่งไป `POST /auth/google` · ไม่มี client id = ไม่แสดงปุ่ม |
| โปรไฟล์ | `ProfileMenu` ใน `components/Shell.tsx` | แก้ชื่อ (`PATCH /me`) เปลี่ยนรหัสผ่าน (`POST /me/password`) ออกจากระบบ (ที่เดียวในเว็บ) |
| ธีม | `lib/theme.ts` + `html[data-theme="glass"]` ใน `globals.css` | ธีมมืดเป็นค่าตั้งต้น ธีมขาวใช้ชื่อ `glass` · สีกำหนดเป็นตัวแปรที่ `:root` แล้วเขียนทับในธีมขาว เช็กคอนทราสต์ทั้ง 2 ธีมทุกครั้ง (ข้อความควร ≥ 4.5) |
| จอเตี้ย | `@media (max-height: 920px)` ส่วน login และ `(max-height: 820px)` หน้าหลัก | ย่อหัวข้อและการ์ดให้พอดีจอ ลองที่ 1440×825 (หน้าต่าง Safari บนจอ 900) ทุกครั้งที่แก้หน้า login |

## ของกลาง (ใช้ตัวนี้ ห้ามเขียนซ้ำ)

| ไฟล์ | ใช้ทำอะไร |
|---|---|
| `lib/api.ts` | `api<T>(path, {method, body, timeoutMs, signal})` + `ApiError` (`code`, `message` ภาษาคน) |
| `lib/store.tsx` | `useApp()` ทริป หมุดภัย อากาศรอบตัว ตำแหน่ง (`here`, `hereFallback`, `locate()`) แจ้งเตือน `floodWindow` โปรไฟล์ (`displayName`) + คำสั่งสร้าง/แก้/ลบ/วางแผนทริป `loadDepartures()` |
| `lib/chat.tsx` | บทสนทนากับน้องกิเลน (แชทลอยและหน้าเต็มใช้ชุดเดียวกัน) เก็บประวัติในเครื่องแยกตามบัญชี |
| `lib/data.ts` | ชนิดข้อมูลตาม CONTRACT, `RISK_TH`, `RISK_COLOR`, `RECO`, `HAZARD_META`, เวลาไทย (`thaiTime`, `thaiDateTime`, ...) |
| `lib/segments.ts` | ระบายสีเส้นทางตามความเสี่ยงแต่ละช่วง, ระยะทาง |
| `lib/theme.ts`, `lib/mapStyle.ts`, `lib/layout.tsx` | ธีม, สีแผนที่, ขนาดตัวอักษร + ลากปรับขนาดการ์ด (`useSplit`) |
| `components/Map.tsx` | แผนที่ Leaflet (ปิด SSR ให้แล้ว) หมุด กลุ่มหมุด เส้นทาง วงรัศมี ชั้นน้ำท่วม |
| `components/Shell.tsx` | `Topbar`, เมนูซ้ายพับได้, แถบล่างมือถือ, `openChat()` |
| `components/ui.tsx`, `components/Icon.tsx` | การ์ดหัวเรื่อง ป้ายความเสี่ยง และไอคอนทั้งเว็บ |

**ถ้าเปลี่ยน props ของของกลาง ต้องแจ้งเจ้าของโมดูล 2, 3, 9 ก่อน** ไม่งั้นหน้าเขาพังตอน merge

## จุดที่คนส่วนใหญ่พลาด

1. **ต่างคนต่างลง package** ขอเจ้าของโมดูล 1 ก่อน lockfile conflict ให้ลบแล้ว `npm install` ใหม่ ห้ามแก้ด้วยมือ
2. **เรียก `http://localhost:8001` ตรง** พังใน Docker ให้เรียก `/api/v1/...` ผ่าน `lib/api.ts`
3. **Leaflet พังตอน build** ใช้ `components/Map` (dynamic ปิด SSR) อย่า import `MapView` ตรง
4. **แสดงเวลาตาม timezone เครื่อง** ใช้ตัวช่วยใน `lib/data.ts` (`Asia/Bangkok`) เสมอ
5. **ไม่มีสถานะโหลด/พัง/ว่าง** ทุกการ์ดและแผนที่ต้องมีครบ 3 สถานะ
6. **สีตายตัวในหน้า** ใช้ตัวแปรใน `globals.css` (`var(--lime)` ฯลฯ) ไม่งั้นธีมขาวใสพัง ตัวอย่างที่เคยเจอ: ป้ายตัวขาวบนพื้นขาว, เบอร์ฉุกเฉินแดงบนการ์ดแดง
7. **ตั้งฟอนต์เอง** ใช้ `var(--font-main)` ห้ามเพิ่ม `font-family` อื่นหรือโหลดฟอนต์จากเน็ต
8. **เพิ่มหน้าที่ต้องเปิดได้โดยไม่ login แล้วลืม `PUBLIC_PATHS`** หน้าจะเด้งไป `/login`
