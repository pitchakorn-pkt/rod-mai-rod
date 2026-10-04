"use client";

import { useEffect, useState } from "react";
import Map from "./Map";
import Icon from "./Icon";
import type { LatLng } from "@/lib/data";
import { api } from "@/lib/api";
import { useApp, type NewTrip } from "@/lib/store";

type Place = LatLng & { name: string; detail?: string };

// ปุ่มลัดสถานที่ยอดนิยม ส่วนช่องค้นหาเรียก GET /places/search จริง
const PLACES: Place[] = [
  { name: "กรุงเทพมหานคร", detail: "กรุงเทพมหานคร", lat: 13.7563, lng: 100.5018 },
  { name: "สนามบินดอนเมือง", detail: "เขตดอนเมือง, กรุงเทพมหานคร", lat: 13.9126, lng: 100.6068 },
  { name: "เชียงใหม่", detail: "อำเภอเมืองเชียงใหม่, จังหวัดเชียงใหม่", lat: 18.7883, lng: 98.9853 },
  { name: "ดอยสุเทพ", detail: "อำเภอเมืองเชียงใหม่, จังหวัดเชียงใหม่", lat: 18.8048, lng: 98.9217 },
  { name: "นครสวรรค์", detail: "อำเภอเมืองนครสวรรค์, จังหวัดนครสวรรค์", lat: 15.7047, lng: 100.1372 },
  { name: "หัวหิน", detail: "อำเภอหัวหิน, จังหวัดประจวบคีรีขันธ์", lat: 12.5684, lng: 99.9577 },
  { name: "พระนครศรีอยุธยา", detail: "จังหวัดพระนครศรีอยุธยา", lat: 14.3532, lng: 100.5689 },
  { name: "นครราชสีมา", detail: "อำเภอเมืองนครราชสีมา", lat: 14.9799, lng: 102.0978 },
  { name: "เขาใหญ่", detail: "อำเภอปากช่อง, จังหวัดนครราชสีมา", lat: 14.4392, lng: 101.3722 },
  { name: "พัทยา", detail: "อำเภอบางละมุง, จังหวัดชลบุรี", lat: 12.9236, lng: 100.8825 },
  { name: "ภูเก็ต", detail: "อำเภอเมืองภูเก็ต, จังหวัดภูเก็ต", lat: 7.8804, lng: 98.3923 },
  { name: "พิษณุโลก", detail: "อำเภอเมืองพิษณุโลก", lat: 16.8211, lng: 100.2659 },
];
const PRESETS = ["กรุงเทพมหานคร", "นครสวรรค์", "เชียงใหม่"];

function PlaceInput({ label, value, onPick, onClear, active, onFocus }: { label: string; value: Place | null; onPick: (p: Place) => void; onClear: () => void; active: boolean; onFocus: () => void }) {
  const [q, setQ] = useState("");
  const [hi, setHi] = useState(0);
  const [hits, setHits] = useState<Place[]>([]);
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  // รอพิมพ์เสร็จ 350 มิลลิวินาทีค่อยค้น (Photon ผ่าน api-backend)
  useEffect(() => {
    const t = q.trim();
    if (t.length < 2) {
      setHits([]);
      setState("idle");
      return;
    }
    setState("loading");
    let live = true;
    const timer = setTimeout(() => {
      api<{ places: Place[] }>(`/places/search?q=${encodeURIComponent(t)}`)
        .then((d) => live && (setHits(d.places), setState("done")))
        .catch(() => live && (setHits([]), setState("error")));
    }, 350);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [q]);
  if (value)
    return (
      <div className="field">
        <span className="label">{label}</span>
        <div className="row nowrap input" style={{ padding: "8px 8px 8px 12px" }}>
          <Icon name="pin" size={18} />
          <span className="grow bold">{value.name}</span>
          <button className="icon-btn" style={{ width: 32, height: 32 }} onClick={onClear} aria-label={`เปลี่ยน${label}`}>
            <Icon name="x" size={16} />
          </button>
        </div>
      </div>
    );
  return (
    <div className="field">
      <span className="label">{label}</span>
      <div className="input-icon" style={{ position: "relative" }}>
        <Icon name="search" size={18} />
        <input
          className="input"
          style={active ? { borderColor: "var(--violet)" } : undefined}
          placeholder="พิมพ์ชื่อสถานที่ เช่น กทม, เชียงใหม่ หรือจิ้มบนแผนที่"
          value={q}
          onFocus={onFocus}
          onChange={(e) => {
            setQ(e.target.value);
            setHi(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") setHi((h) => Math.min(h + 1, hits.length - 1));
            if (e.key === "ArrowUp") setHi((h) => Math.max(h - 1, 0));
            if (e.key === "Enter" && hits[hi]) {
              e.preventDefault();
              onPick(hits[hi]);
              setQ("");
            }
          }}
        />
        {q.trim().length >= 2 && (
          <div className="suggest">
            {state === "loading" && !hits.length ? (
              <p className="small muted" style={{ padding: 10 }}>กำลังค้นหา...</p>
            ) : state === "error" ? (
              <p className="small muted" style={{ padding: 10 }}>ค้นหาไม่ได้ตอนนี้ จิ้มบนแผนที่แทนได้เลย</p>
            ) : hits.length ? (
              hits.map((p, i) => (
                <button key={`${p.name}-${i}`} className={i === hi ? "on" : ""} onMouseDown={(e) => { e.preventDefault(); onPick(p); setQ(""); }}>
                  <Icon name="pin" size={18} />
                  <span>
                    <span className="bold">{p.name}</span>
                    <br />
                    <span className="tiny muted">{p.detail}</span>
                  </span>
                </button>
              ))
            ) : (
              <p className="small muted" style={{ padding: 10 }}>ไม่เจอสถานที่นี้ ลองชื่ออื่น หรือจิ้มบนแผนที่แทน</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ช่องเวลาเป็นเวลาไทยเสมอ ไม่ใช้ timezone ของเครื่อง (CONTRACT หัวข้อ 7) ไทยเป็น UTC+7 ไม่มีเวลาออมแสง
const TH_OFFSET_MS = 7 * 3600_000;

// ISO (UTC) -> ค่าของช่อง datetime-local เป็นเวลาไทย
function toThaiInput(iso: string) {
  return new Date(new Date(iso).getTime() + TH_OFFSET_MS).toISOString().slice(0, 16);
}

// ค่าของช่อง datetime-local (เวลาไทย) -> ISO (UTC)
function thaiInputToUtc(value: string) {
  return new Date(`${value}:00+07:00`).toISOString().replace(/\.\d{3}Z$/, "Z");
}

// ใช้ทั้งสร้างทริปใหม่ และแก้ทริปเดิม (ส่ง initial มา)
export default function PlanTrip({
  onClose,
  onCreate,
  initial,
  presetDestination,
}: {
  onClose: () => void;
  onCreate: (t: NewTrip) => Promise<void>;
  initial?: NewTrip;
  presetDestination?: Place;
}) {
  const { here, hereFallback, locate } = useApp();
  const [locating, setLocating] = useState(false);
  const editing = !!initial;
  const [error, setError] = useState<string | null>(null);
  // ไปที่เที่ยวรอบตัว: ต้นทาง = ตำแหน่งปัจจุบัน ปลายทาง = ที่ที่เลือก
  // ยังไม่ได้ตำแหน่งจริง ไม่เติมต้นทางให้ (ไม่งั้นจะได้กรุงเทพโดยผู้ใช้ไม่รู้ตัว)
  const [origin, setOrigin] = useState<Place | null>(initial?.origin ?? (presetDestination && !hereFallback ? { name: "ตำแหน่งปัจจุบัน", ...here } : null));
  const [dest, setDest] = useState<Place | null>(initial?.destination ?? presetDestination ?? null);
  const [stops, setStops] = useState<Place[]>(initial?.stops ?? []);
  const [focus, setFocus] = useState<"origin" | "dest" | "stop">(initial || presetDestination ? "stop" : "origin");
  const [title, setTitle] = useState(initial?.title ?? "");
  const [date, setDate] = useState(initial ? toThaiInput(initial.departure) : "");
  const [busy, setBusy] = useState(false);

  function place(p: Place) {
    if (focus === "origin") { setOrigin(p); setFocus(dest ? "stop" : "dest"); }
    else if (focus === "dest") { setDest(p); setFocus("stop"); }
    else if (stops.length < 5) setStops([...stops, p]);
  }
  const pins = [
    ...(origin ? [{ id: "o", ...origin, color: "#7a6af2", label: "ต้นทาง" }] : []),
    ...stops.map((s, i) => ({ id: `s${i}`, ...s, color: "#22bfc8", label: `แวะ ${i + 1}` })),
    ...(dest ? [{ id: "d", ...dest, color: "#243457", label: "ปลายทาง" }] : []),
  ];
  // เวลาออกต้องอยู่ในอนาคต (ทริปเดิมที่ผ่านไปแล้วแก้อย่างอื่นได้ ถ้าไม่ได้เปลี่ยนเวลา)
  const nowInput = toThaiInput(new Date().toISOString());
  const past = !!date && date < nowInput && date !== (initial ? toThaiInput(initial.departure) : "");
  const ready = origin && dest && date && !past;

  return (
    <>
      <div className="drawer-bg" onClick={onClose} />
      <section className="card plan-dialog" role="dialog" aria-label={editing ? "แก้ไขทริป" : "วางแผนทริปใหม่"}>
        <div className="map" style={{ borderRadius: 0, border: 0 }}>
          <Map pins={pins} fit={pins.length > 1 ? pins : undefined} onClick={(p) => place({ ...p, name: focus === "stop" ? `จุดแวะ ${stops.length + 1}` : "ตำแหน่งที่เลือก" })} />
          <div className="panel" style={{ top: 16, left: 16, padding: "10px 14px" }}>
            <p className="small">
              <b>จิ้มบนแผนที่</b> เพื่อวาง{focus === "origin" ? "ต้นทาง" : focus === "dest" ? "ปลายทาง" : "จุดแวะ"}
            </p>
          </div>
        </div>
        <div className="stack" style={{ padding: 22, overflowY: "auto", alignContent: "start" }}>
          <div className="row between">
            <h2>{editing ? "แก้ไขทริป" : "วางแผนทริปใหม่"}</h2>
            <button className="icon-btn" onClick={onClose} aria-label="ปิด">
              <Icon name="x" />
            </button>
          </div>
          <div className="row" style={{ gap: 6 }}>
            <span className="small muted">ตัวอย่าง:</span>
            {PRESETS.map((n) => (
              <button key={n} className="chip" onClick={() => place(PLACES.find((p) => p.name === n)!)}>
                {n}
              </button>
            ))}
            <button
              className="chip"
              disabled={locating}
              onClick={async () => {
                setLocating(true);
                setError(null);
                const p = await locate();
                setLocating(false);
                if (p) place({ name: "ตำแหน่งปัจจุบัน", ...p });
                else setError("ใช้ตำแหน่งปัจจุบันไม่ได้ (เบราว์เซอร์ไม่อนุญาตหรือหาตำแหน่งไม่เจอ) พิมพ์ชื่อสถานที่หรือจิ้มบนแผนที่แทน");
              }}
            >
              <Icon name="locate" size={14} />
              {locating ? "กำลังหาตำแหน่ง..." : "ตำแหน่งฉัน"}
            </button>
          </div>
          <PlaceInput label="ต้นทาง" value={origin} onPick={(p) => { setOrigin(p); setFocus(dest ? "stop" : "dest"); }} onClear={() => { setOrigin(null); setFocus("origin"); }} active={focus === "origin"} onFocus={() => setFocus("origin")} />
          {stops.map((s, i) => (
            <div key={i} className="row nowrap input" style={{ padding: "8px 8px 8px 12px" }}>
              <span className="badge" style={{ background: "var(--aqua)" }}>{i + 1}</span>
              <span className="grow">{s.name}</span>
              <button className="icon-btn" style={{ width: 32, height: 32 }} onClick={() => setStops(stops.filter((_, j) => j !== i))} aria-label="ลบจุดแวะ">
                <Icon name="trash" size={16} />
              </button>
            </div>
          ))}
          {focus === "stop" && stops.length < 5 && (
            <PlaceInput label={`จุดแวะ ${stops.length + 1} (ไม่บังคับ)`} value={null} onPick={place} onClear={() => {}} active onFocus={() => setFocus("stop")} />
          )}
          {focus !== "stop" && stops.length < 5 && origin && (
            <button className="link-btn small" style={{ justifySelf: "start" }} onClick={() => setFocus("stop")}>
              + เพิ่มจุดแวะ ({stops.length}/5)
            </button>
          )}
          <PlaceInput label="ปลายทาง" value={dest} onPick={(p) => { setDest(p); setFocus("stop"); }} onClear={() => { setDest(null); setFocus("dest"); }} active={focus === "dest"} onFocus={() => setFocus("dest")} />
          <div className="field">
            <label htmlFor="dep">เวลาออกเดินทาง (เวลาไทย)</label>
            <input id="dep" className="input" type="datetime-local" min={nowInput} value={date} onChange={(e) => setDate(e.target.value)} />
            {past && <span className="tiny error-text">เวลานี้ผ่านไปแล้ว เลือกเวลาในอนาคต</span>}
          </div>
          <div className="field">
            <label htmlFor="title">ตั้งชื่อทริป (ไม่บังคับ)</label>
            <input id="title" className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="เช่น เที่ยวเขาใหญ่กับครอบครัว" />
          </div>
          <button
            className="btn block"
            disabled={!ready || busy}
            onClick={async () => {
              setBusy(true);
              setError(null);
              const pt = (p: Place) => ({ lat: p.lat, lng: p.lng, name: p.name });
              try {
                await onCreate({
                  title: title.trim(),
                  origin: pt(origin!),
                  destination: pt(dest!),
                  stops: stops.map(pt),
                  departure: thaiInputToUtc(date),
                });
              } catch (e) {
                setError((e as Error).message);
                setBusy(false);
              }
            }}
          >
            {busy ? "น้องกิเลนกำลังเช็กเส้นทางและอากาศ..." : editing ? "บันทึกและวางแผนใหม่" : "บันทึกและวางแผนเส้นทาง"}
          </button>
          {error && (
            <div className="notice">
              <Icon name="alert" size={18} />
              <span className="small">{error}</span>
            </div>
          )}
          {!ready && <p className="tiny muted" style={{ textAlign: "center" }}>เลือกต้นทาง ปลายทาง และเวลาออกก่อน</p>}
        </div>
      </section>
    </>
  );
}
