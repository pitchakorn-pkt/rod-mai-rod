# ขึ้น Render

> เว็บที่ใช้งานจริงตอนนี้รันด้วย `docker compose` บนเซิร์ฟเวอร์ทั่วไป (README หลัก หัวข้อ 6) Render เป็นทางสำรอง

ทั้งระบบเป็น **web service เดียว** (`Dockerfile` ในโฟลเดอร์นี้) + **Render Postgres** ตาม `render.yaml` ที่ root

- บริการ Python 6 ตัวฟังแค่ `127.0.0.1:8001-8006` ภายใน container (`start.sh` ตั้งที่อยู่ให้เอง ทับค่าใน `.env`)
- หน้าเว็บ (Next.js standalone) ฟังพอร์ต `$PORT` ที่ Render กำหนด ส่งต่อ `/api/v1/*` ไป api-backend ใน container เดียวกัน
- ตัวไหนล้ม container จะปิดตัวเอง แล้ว Render เปิดใหม่ให้

## ต้องใช้แพ็กเกจไหน

แรมทั้งระบบราว **450-600 MB** (ตอนโหลดข้อมูลน้ำท่วม GISTDA สูงสุด) แพ็กเกจ Free / Starter (512 MB) ไม่พอ ใช้ **Standard (2 GB)** ตามที่ตั้งไว้ใน `render.yaml`
Postgres ใช้แบบ Free ได้ (หมดอายุตามเงื่อนไขของ Render)

## ขั้นตอน

1. Render > **New > Blueprint** > เลือก repo นี้ Render จะอ่าน `render.yaml` สร้าง web service `rod-mai-rod` + ฐานข้อมูล `rod-mai-rod-db`
2. ใส่ค่าเองในหน้า **Environment** ของ web service `rod-mai-rod` (ไม่ใช่หน้า Blueprint) ค่าเหล่านี้ไม่อยู่ใน repo: `GROQ_API_KEY`, `GROQ2_API_KEY` (ใส่ key เดียวกับ `GROQ_API_KEY` ได้), `GEMINI_API_KEY`, `GISTDA_API_KEY`, `GOOGLE_CLIENT_ID` (และเพิ่มโดเมน `.onrender.com` ใน Google Cloud)
   `JWT_SECRET` Render สุ่มให้เอง `DATABASE_URL` Render ต่อกับฐานข้อมูลให้เอง
3. กด **Deploy** รอ build ราว 5-8 นาที เสร็จแล้วเปิด `https://<ชื่อ>.onrender.com/health` ต้องได้ `{"status":"ok","service":"web"}`
4. ตรวจหลังขึ้น: สมัครบัญชีใหม่ > สร้างทริป > กดวางแผน > เปิดแผนที่ (หลังเปิดใหม่ ข้อมูลน้ำท่วมใช้เวลาโหลดราว 1.5 นาที) > ถามน้องกิเลน

`autoDeploy: false` = push แล้วไม่ขึ้นเอง ต้องกด Deploy ในหน้า Render (กันของที่ยังไม่ผ่านการตรวจขึ้นไปจริง)

## ลองแบบ Render ในเครื่องก่อน

```sh
docker compose up -d postgres
docker build -f deploy/render/Dockerfile -t rodmairod-render .
docker run --rm -p 10000:10000 -e PORT=10000 --env-file .env --network rod-mai-rod_default rodmairod-render
# เปิด http://localhost:10000
```

## ข้อควรรู้

- บัญชี `demo@example.com` / `demo1234` ถูกสร้างอัตโนมัติ (ใช้กับ `scripts/smoke.sh`) บนเว็บจริงทุกคนเข้าได้ ห้ามใส่ข้อมูลส่วนตัว
- api-backend จำกัด login 10 ครั้งต่อนาทีต่อ IP และแชท 10 ข้อความต่อนาทีต่อคน (CONTRACT หัวข้อ 3)
- เส้นทางใช้ OSRM สาธารณะ (เซิร์ฟเวอร์สาธิต ไม่รับประกันว่าไม่ล่ม) ที่เที่ยวใช้ Overpass แล้วสำรองด้วย Photon
