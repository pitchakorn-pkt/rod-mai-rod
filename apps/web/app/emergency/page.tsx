"use client";

// หน้าฉุกเฉิน: รวมเบอร์ขอความช่วยเหลือ + วิธีรับมือภัยทุกชนิด เห็นครบในจอเดียว ไม่ต้องกดเลือก
// เบอร์: มือถือกดแล้วโทรออก คอมพิวเตอร์โทรไม่ได้ เลยคัดลอกเบอร์ให้แทน
import { useEffect, useMemo, useState } from "react";
import Icon from "@/components/Icon";
import { Topbar, openChat } from "@/components/Shell";
import { HAZARD_META, RISK_TH, riskKey, type Hazard, type HazardType, type LatLng } from "@/lib/data";
import { useApp, type LiveTrip } from "@/lib/store";
import { distanceKm } from "@/lib/segments";

type Line = { phone: string; name: string; note?: string };

// สมุดเบอร์: เบอร์จาก safety-knowledge (GET /safety/emergency) รวมกับเบอร์ที่คนเดินทางควรมี จัดกลุ่มตามเหตุ
const GROUPS: { title: string; icon: string; tone: "red" | "sun" | "aqua"; lines: Line[] }[] = [
  {
    title: "ชีวิตและความปลอดภัย",
    icon: "alert",
    tone: "red",
    lines: [
      { phone: "1669", name: "เจ็บป่วยฉุกเฉิน", note: "รถพยาบาล สพฉ." },
      { phone: "191", name: "เหตุด่วนเหตุร้าย", note: "ตำรวจ" },
      { phone: "199", name: "ดับเพลิงและกู้ภัย" },
    ],
  },
  {
    title: "ภัยพิบัติและสภาพอากาศ",
    icon: "shield",
    tone: "sun",
    lines: [
      { phone: "1784", name: "สายด่วนนิรภัย ปภ.", note: "น้ำท่วม ดินถล่ม พายุ" },
      { phone: "1182", name: "กรมอุตุนิยมวิทยา", note: "สอบถามสภาพอากาศ" },
      { phone: "1130", name: "ไฟฟ้าขัดข้อง กฟน.", note: "กรุงเทพ นนทบุรี สมุทรปราการ" },
      { phone: "1129", name: "ไฟฟ้าขัดข้อง กฟภ.", note: "ต่างจังหวัด" },
    ],
  },
  {
    title: "บนถนนและการเดินทาง",
    icon: "car",
    tone: "aqua",
    lines: [
      { phone: "1193", name: "ตำรวจทางหลวง", note: "อุบัติเหตุบนทางหลวง" },
      { phone: "1586", name: "กรมทางหลวง", note: "ถนนเสีย ถนนขาด" },
      { phone: "1146", name: "กรมทางหลวงชนบท" },
      { phone: "1543", name: "การทางพิเศษ", note: "เหตุบนทางด่วน" },
      { phone: "1155", name: "ตำรวจท่องเที่ยว", note: "พูดภาษาอังกฤษได้" },
    ],
  },
];
const SOS: Line[] = [
  { phone: "1669", name: "เจ็บป่วยฉุกเฉิน" },
  { phone: "191", name: "เหตุด่วนเหตุร้าย" },
  { phone: "1784", name: "สายด่วน ปภ." },
];

// ใช้ได้ทุกภัย: เจอเหตุระหว่างทางทำอะไรก่อนหลัง
const ON_ROAD = [
  "เปิดไฟฉุกเฉิน จอดในที่ปลอดภัย ห่างต้นไม้ใหญ่และเสาไฟ",
  "โทรแจ้งเหตุ บอกหลักกิโลเมตร ชื่อถนน จำนวนคน และอาการผู้บาดเจ็บ",
  "ส่งตำแหน่งให้ครอบครัว และบอกว่าจะรอที่ไหน",
  "เช็กแผนที่ความเสี่ยงอีกครั้งก่อนไปต่อ",
];

const TYPES = Object.keys(HAZARD_META) as HazardType[];
const HAZARD_TONE: Record<HazardType, string> = {
  RAIN: "#2f6fe4",
  HEAVY_RAIN: "#1d4ed8",
  STRONG_WIND: "#8b5cf6",
  FLOOD: "#0891b2",
  LANDSLIDE_RISK: "#a16207",
  STORM: "#6d28d9",
  EARTHQUAKE: "#b45309",
};

// ภัยที่เจอบนเส้นทางของทริปที่กำลังจะถึง: อากาศตอนไปถึง + หมุดภัยใกล้เส้นทาง (น้ำท่วม 10 กม. อื่นๆ 20 กม.)
function tripHazards(trips: LiveTrip[], hazards: Hazard[]) {
  const found: Partial<Record<HazardType, string>> = {};
  const soon = trips.filter((t) => t.plan && new Date(t.departure_time).getTime() > Date.now() - 12 * 3600_000);
  for (const t of soon) {
    const no = `Trip ${String(t.trip_no).padStart(2, "0")}`;
    const plan = t.plan!;
    for (const w of plan.waypoints) {
      const f = w.forecast;
      if (!f) continue;
      if (f.rain_mm_per_h > 35) found.HEAVY_RAIN ??= no;
      else if (f.rain_mm_per_h >= 10) found.RAIN ??= no;
      if (f.wind_kmh >= 40) found.STRONG_WIND ??= no;
    }
    const route = plan.route_options.find((r) => r.is_recommended) ?? plan.route_options[0];
    if (!route) continue;
    const step = Math.max(1, Math.floor(route.geometry.length / 60));
    const pts: LatLng[] = route.geometry.filter((_, i) => i % step === 0);
    for (const h of hazards) {
      if (h.source === "OPEN_METEO" || h.severity === "LOW" || found[h.hazard_type]) continue;
      const r = h.hazard_type === "FLOOD" ? 10 : 20;
      if (pts.some((p) => distanceKm(p, h) <= r)) found[h.hazard_type] = no;
    }
  }
  return found;
}

// ปุ่มเบอร์: มือถือ = โทร, คอม = คัดลอก
function PhoneButton({ line, big, touch }: { line: Line; big?: boolean; touch: boolean }) {
  const [copied, setCopied] = useState(false);
  const inner = (
    <>
      <span className="ph-num">{line.phone}</span>
      <span className="ph-name">
        <b>{line.name}</b>
        {line.note && <small>{line.note}</small>}
      </span>
      <span className="ph-act" aria-hidden>
        <Icon name={touch ? "phone" : copied ? "check" : "share"} size={big ? 18 : 15} />
      </span>
    </>
  );
  if (touch)
    return (
      <a href={`tel:${line.phone}`} className={`ph ${big ? "big" : ""}`}>
        {inner}
      </a>
    );
  return (
    <button
      className={`ph ${big ? "big" : ""} ${copied ? "copied" : ""}`}
      title="คัดลอกเบอร์"
      onClick={() => {
        navigator.clipboard?.writeText(line.phone).catch(() => {});
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    >
      {inner}
    </button>
  );
}

export default function Emergency() {
  const { emergency, here, trips, hazards, nextTrip } = useApp();
  const [touch, setTouch] = useState(false);
  const [copied, setCopied] = useState<"loc" | "trip" | null>(null);
  useEffect(() => setTouch(window.matchMedia("(pointer: coarse)").matches), []);

  const onRoute = useMemo(() => tripHazards(trips, hazards), [trips, hazards]);
  // ภัยที่เจอบนเส้นทางขึ้นก่อน
  const order = [...TYPES].sort((a, b) => Number(!!onRoute[b]) - Number(!!onRoute[a]));
  // เบอร์จากระบบที่ยังไม่อยู่ในสมุด ต่อท้ายกลุ่มแรก
  const known = new Set(GROUPS.flatMap((g) => g.lines.map((l) => l.phone)));
  const extra = (emergency.FLOOD?.contacts ?? []).filter((c) => !known.has(c.phone)).map((c) => ({ phone: c.phone, name: c.name_th }));

  function copy(kind: "loc" | "trip") {
    let text = `ตำแหน่งปัจจุบันของฉัน https://www.google.com/maps?q=${here.lat.toFixed(5)},${here.lng.toFixed(5)}`;
    if (kind === "trip" && nextTrip) {
      const p = nextTrip.plan;
      text = [
        `ทริป ${nextTrip.title}: ${nextTrip.origin} → ${nextTrip.destination}`,
        `ออก ${new Date(nextTrip.departure_time).toLocaleString("th-TH", { timeZone: "Asia/Bangkok", dateStyle: "medium", timeStyle: "short" })}`,
        p ? `ถึงประมาณ ${new Date(p.arrival_time).toLocaleTimeString("th-TH", { timeZone: "Asia/Bangkok", hour: "2-digit", minute: "2-digit" })} · ความเสี่ยง${RISK_TH[riskKey(p.risk_level)]}` : "",
        text,
      ]
        .filter(Boolean)
        .join("\n");
    }
    navigator.clipboard?.writeText(text).catch(() => {});
    setCopied(kind);
    setTimeout(() => setCopied(null), 2000);
  }

  return (
    <>
      <Topbar title="ฉุกเฉิน" sub={touch ? "กดเบอร์เพื่อโทรออกได้ทันที" : "กดเบอร์เพื่อคัดลอก แล้วโทรจากมือถือ"} />
      <div className="emer">
        {/* ซ้าย: ขอความช่วยเหลือ */}
        <div className="emer-side">
          <section className="card sos-card">
            <div className="row nowrap" style={{ gap: 12, marginBottom: 12 }}>
              <span className="sos-badge">
                <Icon name="sos" size={22} />
              </span>
              <div>
                <h3 style={{ color: "#fff" }}>ต้องการความช่วยเหลือด่วน</h3>
                <p className="tiny" style={{ color: "rgba(255,255,255,.85)" }}>ตั้งสติ บอกตำแหน่งให้ชัด แล้วทำตามที่เจ้าหน้าที่บอก</p>
              </div>
            </div>
            <div className="stack" style={{ gap: 8 }}>
              {SOS.map((l) => (
                <PhoneButton key={l.phone} line={l} big touch={touch} />
              ))}
            </div>
            <div className="grid-2" style={{ gap: 8, marginTop: 10 }}>
              <button className="sos-ghost" onClick={() => copy("loc")}>
                <Icon name={copied === "loc" ? "check" : "locate"} size={16} />
                {copied === "loc" ? "คัดลอกแล้ว" : "คัดลอกตำแหน่ง"}
              </button>
              <button className="sos-ghost" onClick={() => copy("trip")} disabled={!nextTrip}>
                <Icon name={copied === "trip" ? "check" : "share"} size={16} />
                {copied === "trip" ? "คัดลอกแล้ว" : "ส่งทริปให้ครอบครัว"}
              </button>
            </div>
          </section>

          <section className="card dash-card grow phonebook">
            <p className="row bold" style={{ gap: 8, marginBottom: 8 }}>
              <Icon name="list" size={18} /> สมุดเบอร์ฉุกเฉิน
            </p>
            <div className="dash-scroll">
              {GROUPS.map((g, gi) => (
                <div key={g.title} className="pb-group">
                  <p className={`pb-head ${g.tone}`}>
                    <Icon name={g.icon} size={14} />
                    {g.title}
                  </p>
                  {[...g.lines, ...(gi === 0 ? extra : [])].map((l) => (
                    <PhoneButton key={l.phone} line={l} touch={touch} />
                  ))}
                </div>
              ))}
            </div>
          </section>
        </div>

        {/* ขวา: วิธีรับมือทุกภัย */}
        <section className="card dash-card grow emer-guides">
          <div className="row between nowrap" style={{ marginBottom: 12 }}>
            <div>
              <h3>วิธีรับมือเมื่อเจอภัยระหว่างเดินทาง</h3>
              <p className="tiny muted">จากเอกสารของ ปภ. กรมการขนส่งทางบก และกรมอุตุนิยมวิทยา · ภัยที่อยู่บนเส้นทางทริปของคุณขึ้นก่อน</p>
            </div>
            <button className="btn sm ghost" onClick={() => openChat("เจอเหตุระหว่างทางต้องทำยังไง")}>
              <Icon name="chat" size={16} />
              ถามน้องกิเลน
            </button>
          </div>
          <div className="dash-scroll">
            <div className="guide-grid">
              <article className="guide general">
                <div className="guide-head">
                  <span className="guide-icon">
                    <Icon name="car" size={20} />
                  </span>
                  <div>
                    <h4>เจอเหตุระหว่างทาง</h4>
                    <p className="tiny muted">ใช้ได้กับทุกภัย ทำตามลำดับ</p>
                  </div>
                </div>
                <ol className="guide-steps">
                  {ON_ROAD.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ol>
              </article>
              {order.map((t) => {
                const g = emergency[t];
                const hit = onRoute[t];
                return (
                  <article key={t} className={`guide ${hit ? "hit" : ""}`} style={{ ["--tone" as string]: HAZARD_TONE[t] }}>
                    <div className="guide-head">
                      <span className="guide-icon">
                        <Icon name={HAZARD_META[t].icon} size={20} />
                      </span>
                      <div style={{ minWidth: 0 }}>
                        <h4>{HAZARD_META[t].label}</h4>
                        {hit ? <p className="guide-hit">เจอบนเส้นทาง {hit}</p> : <p className="tiny muted">ถ้าเจอระหว่างทาง</p>}
                      </div>
                    </div>
                    <ol className="guide-steps">
                      {(g?.steps_th ?? []).map((s) => (
                        <li key={s}>{s}</li>
                      ))}
                    </ol>
                  </article>
                );
              })}
            </div>
          </div>
        </section>
      </div>
    </>
  );
}
