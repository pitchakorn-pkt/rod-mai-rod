"use client";

// หน้าหลัก: ตอบคำถามเดียวให้ชัด "ทริปถัดไปไปได้ไหม ต้องทำอะไร"
// รายละเอียดเชิงลึก (อากาศรายจุด เทียบเวลาออก เช็กลิสต์) อยู่หน้าทริป เบอร์ครบชุดอยู่หน้าฉุกเฉิน
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import Map from "@/components/Map";
import Icon from "@/components/Icon";
import { Topbar, openChat } from "@/components/Shell";
import { CardHead } from "@/components/ui";
import { HAZARD_META, RECO, RISK_COLOR, RISK_TH, duration, riskKey, thaiDate, thaiDateTime, thaiTime, weatherIcon, type HazardType, type Risk } from "@/lib/data";
import { useApp, type LiveTrip } from "@/lib/store";
import { api, ApiError } from "@/lib/api";
import { coloredSegments, distanceKm, placeRisk, riskSegments } from "@/lib/segments";
import { useSplit } from "@/lib/layout";

function greeting() {
  const h = Number(new Date().toLocaleString("en-US", { timeZone: "Asia/Bangkok", hour: "numeric", hour12: false }));
  return h < 12 ? "สวัสดีตอนเช้า" : h < 17 ? "สวัสดีตอนบ่าย" : "สวัสดีตอนเย็น";
}

function countdown(iso: string) {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return "กำลังเดินทาง";
  const h = Math.floor(ms / 3600_000);
  if (h < 1) return `อีก ${Math.max(1, Math.round(ms / 60_000))} นาที`;
  return h >= 24 ? `อีก ${Math.floor(h / 24)} วัน ${h % 24} ชม.` : `อีก ${h} ชม.`;
}

// เคล็ดลับเดินทางปลอดภัย (ช่วงหน้าฝน) หมุนเปลี่ยนทุก 7 วินาที ข้อแรกอิงอากาศรอบตัวจริง
const TIPS = [
  { icon: "clock", text: "เช็กความเสี่ยงอีกรอบก่อนออกเดินทาง 1 ชั่วโมง อากาศเปลี่ยนเร็วในหน้าฝน" },
  { icon: "rain", text: "ฝนตกหนักให้เปิดไฟหน้า ห้ามเปิดไฟฉุกเฉินขณะขับ และเว้นระยะห่างเป็น 2 เท่า" },
  { icon: "flood", text: "เจอน้ำท่วมถนนสูงเกินครึ่งล้อหรือมองไม่เห็นผิวถนน อย่าฝ่า ให้หาทางเลี่ยง" },
  { icon: "car", text: "ขับรถนานเกิน 2 ชั่วโมง แวะพักยืดเส้น 15 นาที ลดอาการง่วง" },
  { icon: "share", text: "บอกเส้นทางและเวลาถึงให้คนที่บ้านรู้ทุกครั้ง ใช้ปุ่มส่งทริปในหน้าฉุกเฉินได้" },
  { icon: "landslide", text: "ขึ้นเขาช่วงฝนตกสะสม สังเกตน้ำขุ่นและเศษดินไหลลงถนน เป็นสัญญาณดินถล่ม" },
];

function useTip(first?: { icon: string; text: string } | null) {
  const list = first ? [first, ...TIPS] : TIPS;
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((x) => x + 1), 7000);
    return () => clearInterval(t);
  }, []);
  const n = i % list.length;
  return { tip: list[n], n, total: list.length, next: () => setI(n + 1), go: (k: number) => setI(k) };
}

// เคล็ดลับจากน้องกิเลน (compact = แถวเดียวข้างปุ่มในการ์ดที่มีทริป)
function TipCard({ tip, compact }: { tip: ReturnType<typeof useTip>; compact?: boolean }) {
  return (
    <div className={`tip-card ${compact ? "compact" : ""}`}>
      <span className="tip-icon">
        <Icon name={tip.tip.icon} size={18} />
      </span>
      <div className="grow" style={{ minWidth: 0 }}>
        {!compact && <p className="tiny bold" style={{ color: "var(--violet)" }}>เคล็ดลับจากน้องกิเลน</p>}
        <p key={tip.n} className="small tip-text">
          {tip.tip.text}
        </p>
        <div className="tip-dots">
          {Array.from({ length: tip.total }, (_, k) => (
            <button key={k} className={k === tip.n ? "on" : ""} onClick={() => tip.go(k)} aria-label={`เคล็ดลับข้อ ${k + 1}`} />
          ))}
        </div>
      </div>
    </div>
  );
}

// น้องกิเลนยืนให้กำลังใจ พร้อมคำพูดตามสถานการณ์
function Cheer({ text, corner }: { text: string; corner?: boolean }) {
  return (
    <div className={`cheer ${corner ? "corner" : ""}`}>
      <span className="cheer-bubble">{text}</span>
      <img className="qilin-cheer-anim" src="/assets/mascots/home-qilin-hero.webp" alt="น้องกิเลน" />
    </div>
  );
}

type Spot = { name: string; detail: string | null; lat: number; lng: number; kind_th: string };
const EXPLORE_KM = 20;

// ที่เที่ยวรอบตัว 20 กม. (GET /places/nearby) โหลดเฉพาะตอนยังไม่มีทริป
// ช่องใหม่ครั้งแรก api-backend อาจตอบ UPSTREAM_TIMEOUT แต่ยังโหลดต่อเบื้องหลัง ถามซ้ำ 1 ครั้งมักได้แล้ว
function useSpots(enabled: boolean, lat: number, lng: number) {
  const [state, setState] = useState<{ spots: Spot[] | null; error: string | null }>({ spots: null, error: null });
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    setState({ spots: null, error: null });
    const path = `/places/nearby?lat=${lat.toFixed(4)}&lng=${lng.toFixed(4)}&radius_km=${EXPLORE_KM}&kinds=attraction`;
    const load = () => api<{ places: Spot[] }>(path, { timeoutMs: 20000 });
    load()
      .catch((e) => (e instanceof ApiError && e.code === "UPSTREAM_TIMEOUT" ? new Promise((r) => setTimeout(r, 6000)).then(load) : Promise.reject(e)))
      .then((d) => live && setState({ spots: d.places, error: null }))
      .catch((e) => live && setState({ spots: null, error: e instanceof ApiError ? e.message : "ดึงที่เที่ยวรอบตัวไม่ได้" }));
    return () => {
      live = false;
    };
  }, [enabled, lat, lng]);
  return state;
}

const tripNo = (t: LiveTrip) => `Trip ${String(t.trip_no).padStart(2, "0")}`;
const TONE_BG = { ok: "var(--low-50)", warn: "var(--mid-50)", danger: "var(--high-50)", info: "var(--violet-50)" } as const;

// วงแหวนคะแนนความเสี่ยง 0-100
function RiskRing({ level, score }: { level: Risk; score: number | null }) {
  const color = RISK_COLOR[riskKey(level)];
  const pct = Math.max(0, Math.min(100, score ?? 0));
  const r = 34;
  const c = 2 * Math.PI * r;
  return (
    <div className="ring" style={{ color }}>
      <svg viewBox="0 0 84 84" width="84" height="84" aria-hidden>
        <circle cx="42" cy="42" r={r} fill="none" stroke="currentColor" strokeOpacity="0.15" strokeWidth="8" />
        <circle cx="42" cy="42" r={r} fill="none" stroke="currentColor" strokeWidth="8" strokeLinecap="round" strokeDasharray={`${(pct / 100) * c} ${c}`} transform="rotate(-90 42 42)" />
      </svg>
      <span>
        <b>{score ?? "-"}</b>
        <small>คะแนนเสี่ยง</small>
      </span>
    </div>
  );
}

function Home() {
  const empty = useSearchParams().get("empty") === "1";
  const { trips, nextTrip, hazards, area, email, emergency, planTrip, here: me, hereFallback, locate } = useApp();
  const [locateFailed, setLocateFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  // ลากเส้นแบ่งปรับขนาดการ์ด: ซ้าย/ขวา แถวบน/ล่าง และการ์ด 3 ใบล่าง (จำกัดขนาดขั้นต่ำป้องกันตัวหนังสือล้น)
  const cols = useSplit("home_cols", [1, 1], { cssVar: "--home-cols", min: 0.35, label: "การ์ดซ้ายขวา" });
  const rows = useSplit("home_rows", [1, 1], { axis: "y", cssVar: "--home-rows", min: 0.35, label: "แถวบนและแถวล่าง" });
  const bottom = useSplit("home_bottom", [1, 1, 1], { cssVar: "--home-bottom", min: 0.25, label: "การ์ดแถวล่าง" });
  const trip = empty ? null : nextTrip;
  // ยังไม่มีทริป = โหมดสำรวจรอบตัว
  const explore = !trip;
  const { spots, error: spotsError } = useSpots(explore, me.lat, me.lng);
  const [picked, setPicked] = useState<string | null>(null);
  const around = useMemo(
    () =>
      (spots ?? [])
        .map((p) => ({ ...p, dist: distanceKm(me, p), risk: placeRisk(p, area?.cells ?? [], hazards) }))
        .sort((a, b) => a.dist - b.dist),
    [spots, me, area, hazards],
  );
  const pickedSpot = around.find((p) => p.name === picked) ?? null;
  const plan = trip?.plan ?? null;
  const route = plan?.route_options.find((r) => r.is_recommended) ?? plan?.route_options[0];
  const segments = useMemo(() => (route && plan ? coloredSegments(route.geometry, plan.waypoints, hazards) : []), [route, plan, hazards]);
  // จุดที่ต้องระวังบนเส้นทาง (ช่วงสีส้ม/แดง ไม่นับซ้ำเหตุเดียวกัน) รุนแรงก่อน
  const watch = useMemo(() => {
    if (!route || !plan) return [];
    const seen = new Set<string>();
    return riskSegments(route.geometry, plan.waypoints, hazards)
      .filter((s) => s.level !== "LOW" && !seen.has(s.tip) && seen.add(s.tip))
      .sort((a, b) => Number(b.level === "HIGH") - Number(a.level === "HIGH"));
  }, [route, plan, hazards]);

  const upcoming = trips
    .filter((t) => t.trip_id !== trip?.trip_id && new Date(t.departure_time).getTime() > Date.now() - 12 * 3600_000)
    .sort((a, b) => new Date(a.departure_time).getTime() - new Date(b.departure_time).getTime());

  // สถานการณ์ภัยทั่วประเทศตอนนี้ นับเฉพาะระดับเฝ้าระวังขึ้นไป ไม่นับอากาศชั่วโมงนี้
  const serious = hazards.filter((h) => h.severity !== "LOW" && h.source !== "OPEN_METEO");
  const byType = (Object.keys(HAZARD_META) as HazardType[])
    .map((t) => ({ t, high: serious.filter((h) => h.hazard_type === t && h.severity === "HIGH").length, all: serious.filter((h) => h.hazard_type === t).length }))
    .filter((x) => x.all > 0)
    .sort((a, b) => b.high - a.high || b.all - a.all);

  const closest = useMemo(() => {
    const ref = route ? route.geometry.filter((_, i) => i % Math.max(1, Math.floor(route.geometry.length / 60)) === 0) : [me];
    return serious
      .map((h) => ({ h, d: Math.min(...ref.map((p) => distanceKm(p, h))) }))
      .sort((a, b) => a.d - b.d)
      .slice(0, 6);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route, me, hazards]);
  const aroundWx = (area?.cells ?? [])
    .map((c) => {
      const dy = c.lat - area!.center.lat;
      const dx = c.lng - area!.center.lng;
      if (Math.abs(dy) < 0.05 && Math.abs(dx) < 0.05) return { dir: "ตรงนี้", order: 0, forecast: c.forecast };
      const dir = (dy > 0.05 ? "เหนือ" : dy < -0.05 ? "ใต้" : "") + (dx > 0.05 ? "ตะวันออก" : dx < -0.05 ? "ตะวันตก" : "");
      return { dir: `ทิศ${dir}`, order: 1, forecast: c.forecast };
    })
    .sort((a, b) => a.order - b.order || b.forecast.rain_mm_per_h - a.forecast.rain_mm_per_h);
  const here = area?.cells.length
    ? area.cells.reduce((a, b) => (Math.hypot(b.lat - area.center.lat, b.lng - area.center.lng) < Math.hypot(a.lat - area.center.lat, a.lng - area.center.lng) ? b : a))
    : null;
  const name = email?.split("@")[0];
  const reco = plan ? RECO[plan.recommendation] : null;
  const today = new Date().toLocaleDateString("th-TH", { timeZone: "Asia/Bangkok", weekday: "long", day: "numeric", month: "long" });
  const hotline = emergency.FLOOD?.contacts?.[0] ?? { name_th: "สายด่วนนิรภัย ปภ.", phone: "1784" };
  const tip = useTip(
    here && here.forecast.rain_mm_per_h >= 1
      ? { icon: "rain", text: `ตอนนี้รอบตัวคุณ${here.forecast.condition_th} ${here.forecast.rain_mm_per_h} มม./ชม. ถ้าจะออกไปไหน พกร่มและขับช้าลงหน่อยนะ` }
      : null,
  );
  // คำให้กำลังใจตามสถานการณ์
  const cheer = !trip
    ? "ไปเที่ยวไหนดี น้องกิเลนช่วยเช็กให้!"
    : !plan
      ? "กดเช็กเส้นทางก่อนนะ จะได้อุ่นใจ"
      : plan.recommendation === "AVOID"
        ? "ช่วงนี้อันตราย ไว้ค่อยไปนะ ปลอดภัยไว้ก่อน"
        : plan.recommendation === "DELAY"
          ? "รออีกนิด ออกช้าลงจะปลอดภัยกว่า"
          : plan.risk_level === "MEDIUM"
            ? "ขับช้าๆ ระวังช่วงที่มีฝนหรือภัยนะ"
            : "ทางสะดวก เที่ยวให้สนุกนะ!";

  return (
    <>
      <Topbar
        title={`${greeting()}${name ? ` คุณ${name}` : ""}`}
        sub={`${today}${here ? ` · รอบตัวคุณ ${here.forecast.temp_c}° ${here.forecast.condition_th}` : ""}`}
        right={
          <Link href="/trips?new=1" className="btn">
            <Icon name="plus" size={18} />
            วางแผนทริป
          </Link>
        }
      />

      <div
        className="home2 split-box"
        style={{ ...cols.style, ...rows.style }}
        ref={(el) => {
          cols.ref.current = el;
          rows.ref.current = el;
        }}
      >
        {/* 1. คำตอบหลัก: ทริปถัดไปไปได้ไหม */}
        {trip && plan && route && reco ? (
          <section className="card hero2 has-plan" style={{ background: `linear-gradient(135deg, var(--surface-card) 45%, ${TONE_BG[reco.tone]})` }}>
            <span className="hero2-tag">
              <Icon name="calendar" size={14} />
              ทริปถัดไป · {tripNo(trip)} · {countdown(trip.departure_time)}
            </span>
            <div className="hero2-main">
              <RiskRing level={plan.risk_level} score={plan.risk_score} />
              <div style={{ minWidth: 0 }}>
                <h2 className="ellipsis font-serif" style={{ fontSize: "calc(26px * var(--fs))" }}>
                  {trip.title}
                </h2>
                <p className="small muted ellipsis">{[trip.origin, ...trip.stops, trip.destination].join(" › ")}</p>
                <p className={`hero2-verdict ${reco.tone}`}>{reco.title}</p>
                <p className="small hero2-summary">{plan.summary_th}</p>
              </div>
            </div>
            <div className="hero2-facts">
              <div>
                <span>ออกเดินทาง</span>
                <b>{thaiTime(trip.departure_time)}</b>
                <small>{thaiDate(trip.departure_time)}</small>
              </div>
              <div>
                <span>ถึงปลายทาง</span>
                <b>{thaiTime(plan.arrival_time)}</b>
                <small>{thaiDate(plan.arrival_time)}</small>
              </div>
              <div>
                <span>ระยะทาง</span>
                <b>{route.distance_km.toFixed(0)} กม.</b>
                <small>{duration(plan.duration_min)}</small>
              </div>
              <div>
                <span>จุดที่ต้องระวัง</span>
                <b style={{ color: watch.length ? RISK_COLOR[watch[0].level] : RISK_COLOR.LOW }}>{watch.length ? `${watch.length} จุด` : "ไม่มี"}</b>
                <small className="ellipsis" title={watch[0]?.tip}>
                  {watch[0]?.tip ?? "ตลอดเส้นทาง"}
                </small>
              </div>
            </div>
            <div className="hero2-actions">
              <Link href={`/trips?id=${trip.trip_id}`} className="btn">
                ดูแผนเต็ม
                <Icon name="chevron" size={16} />
              </Link>
              <button className="btn ghost" onClick={() => openChat(`${tripNo(trip)} ต้องระวังอะไรบ้าง`)}>
                <Icon name="chat" size={16} />
                ถามน้องกิเลน
              </button>
              <TipCard tip={tip} compact />
            </div>
            <Cheer text={cheer} corner />
          </section>
        ) : (
          <section className="card hero2" style={{ background: "linear-gradient(135deg, var(--surface-card) 40%, var(--lime-50))" }}>
            {trip ? (
              <>
                <span className="hero2-tag">
                  <Icon name="calendar" size={14} />
                  ทริปถัดไป · {tripNo(trip)} · {countdown(trip.departure_time)}
                </span>
                <h2 style={{ fontSize: "calc(24px * var(--fs))" }}>{trip.title}</h2>
                <p className="muted" style={{ maxWidth: 420 }}>
                  ยังไม่ได้เช็กเส้นทาง กดปุ่มเดียว น้องกิเลนจะหาเส้นทาง เช็กอากาศ ณ เวลาที่ไปถึง และจุดเสี่ยงภัยให้
                </p>
                <div className="row">
                  <button
                    className="btn"
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      await planTrip(trip.trip_id).catch(() => {});
                      setBusy(false);
                    }}
                  >
                    <Icon name="spark" size={18} />
                    {busy ? "กำลังเช็กเส้นทาง..." : "เช็กเส้นทางเลย"}
                  </button>
                </div>
              </>
            ) : (
              <>
                <span className="hero2-tag">
                  <Icon name="spark" size={14} />
                  ยังไม่มีทริปที่กำลังจะถึง
                </span>
                <h2 style={{ fontSize: "calc(26px * var(--fs))", maxWidth: 440 }}>จะไปไหนดี บอกน้องกิเลนได้เลย</h2>
                <p className="muted" style={{ maxWidth: 420 }}>
                  ยังไม่มีทริปก็ไม่เป็นไร ดูที่เที่ยวรอบตัวใน {EXPLORE_KM} กม. พร้อมความเสี่ยงและอากาศตอนนี้ได้ด้านล่าง ถูกใจที่ไหนกดวางแผนไปได้เลย
                </p>
                <div className="row">
                  <Link href="/trips?new=1" className="btn">
                    <Icon name="plus" size={18} />
                    วางแผนทริปแรก
                  </Link>
                  <button className="btn ghost" onClick={() => openChat("ช่วงนี้เที่ยวที่ไหนดี")}>
                    ให้น้องกิเลนแนะนำ
                  </button>
                </div>
              </>
            )}
            <div className="hero2-foot">
              <TipCard tip={tip} />
              <Cheer text={cheer} />
            </div>
          </section>
        )}

        {/* 2. แผนที่เส้นทาง (ไม่มีแผน = จุดภัยรุนแรงทั่วประเทศ) */}
        <section className="card hero-map">
          <div className="map fill-map">
            {route && plan ? (
              <Map
                routes={[{ id: route.route_id, points: route.geometry, color: RISK_COLOR[riskKey(route.risk_level)], active: true, segments }]}
                pins={plan.waypoints.map((w) => ({
                  id: w.waypoint_id,
                  lat: w.lat,
                  lng: w.lng,
                  color: RISK_COLOR[riskKey(w.risk_level)],
                  icon: w.kind === "DESTINATION" ? "flag" : w.kind === "ORIGIN" ? "car" : "pin",
                  tip: `${w.name} · ${thaiTime(w.eta)}`,
                }))}
                fit={route.geometry}
                flood
              />
            ) : (
              <Map
                zoom={10}
                center={me}
                me={me}
                circle={{ center: me, radiusKm: EXPLORE_KM, color: "#7a6af2" }}
                flyTo={pickedSpot ? { lat: pickedSpot.lat, lng: pickedSpot.lng } : null}
                pins={around.map((p, i) => ({
                  id: `${p.name}-${i}`,
                  lat: p.lat,
                  lng: p.lng,
                  color: RISK_COLOR[p.risk.level],
                  label: String(i + 1),
                  selected: p.name === picked,
                  tip: `${p.name} · ${p.dist.toFixed(1)} กม.`,
                  onClick: () => setPicked(p.name),
                }))}
                flood
              />
            )}
          </div>
          {explore && (
            <p className="route-legend" style={{ margin: "8px 2px 0" }}>
              <span>
                <span className="me-dot static" />
                {hereFallback ? "ยังไม่ได้ตำแหน่งจริง แสดงรอบกรุงเทพแทน" : "ตำแหน่งของคุณ"}
              </span>
              {hereFallback && (
                <button className="link-btn tiny" onClick={async () => setLocateFailed(!(await locate()))}>
                  {locateFailed ? "เบราว์เซอร์ไม่ให้ใช้ตำแหน่ง ลองอนุญาตแล้วกดอีกครั้ง" : "ใช้ตำแหน่งจริง"}
                </button>
              )}
              <span>
                <i style={{ background: "#7a6af2", height: 2 }} />
                รัศมี {EXPLORE_KM} กม.
              </span>
              <span>
                <i style={{ background: RISK_COLOR.LOW, width: 10, height: 10, borderRadius: 5 }} />
                <i style={{ background: RISK_COLOR.MEDIUM, width: 10, height: 10, borderRadius: 5 }} />
                <i style={{ background: RISK_COLOR.HIGH, width: 10, height: 10, borderRadius: 5 }} />
                ความเสี่ยงของที่เที่ยว
              </span>
            </p>
          )}
          {route && (
            <p className="route-legend" style={{ margin: "8px 2px 0" }}>
              <span>
                <i style={{ background: RISK_COLOR.LOW }} />
                ปกติ
              </span>
              <span>
                <i style={{ background: RISK_COLOR.MEDIUM }} />
                เฝ้าระวัง
              </span>
              <span>
                <i style={{ background: RISK_COLOR.HIGH }} />
                อันตราย
              </span>
              <span>
                <i className="sq" />
                น้ำท่วมจากดาวเทียม
              </span>
            </p>
          )}
        </section>

        <div className="home2-row split-box" style={bottom.style} ref={(el) => void (bottom.ref.current = el)}>
          {/* 3. มีทริป = ทริปถัดๆ ไป + สถานะแต่ละจุดของทริปที่ใกล้ที่สุด / ไม่มีทริป = ที่เที่ยวรอบตัว */}
          <section className="card dash-card">
            {!explore && upcoming.length > 0 && (
              <>
                <div className="sec-head">
                  <span>
                    <Icon name="route" size={15} /> ทริปถัดๆ ไป
                  </span>
                  <Link href="/trips" className="link-btn tiny">
                    ทั้งหมด
                  </Link>
                </div>
                <div className="stack" style={{ gap: 6, marginBottom: 12, gridTemplateColumns: "minmax(0, 1fr)" }}>
                  {upcoming.slice(0, 2).map((t) => (
                    <Link key={t.trip_id} href={`/trips?id=${t.trip_id}`} className="mini-row">
                      <span className="grow" style={{ minWidth: 0 }}>
                        <span className="small bold ellipsis" style={{ display: "block" }}>
                          {t.title}
                        </span>
                        <span className="tiny muted">
                          {tripNo(t)} · {thaiDateTime(t.departure_time)}
                        </span>
                      </span>
                      {t.plan ? <span className={`risk ${riskKey(t.plan.risk_level)} nobreak`}>{RISK_TH[riskKey(t.plan.risk_level)]}</span> : <span className="tiny muted nobreak">ยังไม่เช็ก</span>}
                    </Link>
                  ))}
                </div>
              </>
            )}
            {trip && (
              <>
                <div className="sec-head">
                  <span>
                    <Icon name="pin" size={15} /> สถานะแต่ละจุดของ {tripNo(trip)}
                  </span>
                  <Link href={`/trips?id=${trip.trip_id}`} className="link-btn tiny">
                    ดูแผนเต็ม
                  </Link>
                </div>
                <div className="dash-scroll stack" style={{ gap: 6 }}>
                  {!plan && <p className="small muted">ยังไม่ได้เช็กเส้นทาง กด &quot;เช็กเส้นทางเลย&quot; ด้านบน แล้วจะเห็นอากาศตอนไปถึงแต่ละจุด</p>}
                  {plan?.waypoints.map((w) => (
                    <div key={w.waypoint_id} className="mini-row">
                      <span className="card-icon" style={{ width: 32, height: 32, background: `${RISK_COLOR[riskKey(w.risk_level)]}1a`, color: RISK_COLOR[riskKey(w.risk_level)] }}>
                        <Icon name={w.kind === "DESTINATION" ? "flag" : w.kind === "ORIGIN" ? "car" : "pin"} size={16} />
                      </span>
                      <span className="grow" style={{ minWidth: 0 }}>
                        <span className="small bold ellipsis" style={{ display: "block" }} title={w.name}>
                          {w.name}
                        </span>
                        <span className="tiny muted ellipsis" style={{ display: "block" }}>
                          ถึง {thaiTime(w.eta)} · {w.forecast ? `${w.forecast.condition_th} ฝน ${w.forecast.rain_mm_per_h} มม. · ${Math.round(w.forecast.temp_c)}°` : "ยังไม่มีข้อมูลอากาศ"}
                        </span>
                      </span>
                      <span className={`risk ${riskKey(w.risk_level)} nobreak`}>{RISK_TH[riskKey(w.risk_level)]}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
            {explore && (
              <>
            <div className="sec-head">
              <span>
                <Icon name="compass" size={15} /> ที่เที่ยวรอบตัว {EXPLORE_KM} กม.
              </span>
              {spots && <span className="tiny muted">{around.length} ที่ · ใกล้ไปไกล</span>}
            </div>
            <div className="dash-scroll stack" style={{ gap: 6 }}>
              {!spots && !spotsError && <p className="small muted">น้องกิเลนกำลังหาที่เที่ยว อาจใช้เวลาสักครู่...</p>}
              {spotsError && <p className="small muted">{spotsError}</p>}
              {spots && around.length === 0 && <p className="small muted">ไม่เจอที่เที่ยวในรัศมี {EXPLORE_KM} กม.</p>}
              {around.map((p, i) => (
                <div key={`${p.name}-${i}`} className={`mini-row spot ${p.name === picked ? "on" : ""}`} onClick={() => explore && setPicked(p.name)}>
                  <span className="badge" style={{ background: RISK_COLOR[p.risk.level], flex: "none" }}>
                    {i + 1}
                  </span>
                  <span className="grow" style={{ minWidth: 0 }}>
                    <span className="small bold ellipsis" style={{ display: "block" }} title={p.name}>
                      {p.name}
                    </span>
                    <span className="tiny muted row nowrap" style={{ gap: 6 }}>
                      {p.kind_th} · {p.dist.toFixed(1)} กม.
                      {p.risk.forecast && (
                        <span className="row nowrap" style={{ gap: 3 }} title={p.risk.forecast.condition_th}>
                          · <Icon name={weatherIcon(p.risk.forecast)} size={13} />
                          {Math.round(p.risk.forecast.temp_c)}°
                        </span>
                      )}
                    </span>
                  </span>
                  <span className={`risk ${p.risk.level} nobreak`} title={p.risk.tip}>
                    {RISK_TH[p.risk.level]}
                  </span>
                  <Link
                    href={`/trips?new=1&to=${p.lat.toFixed(5)},${p.lng.toFixed(5)}&name=${encodeURIComponent(p.name)}`}
                    className="spot-go"
                    title="วางแผนไปที่นี่"
                    aria-label={`วางแผนไป ${p.name}`}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Icon name="route" size={15} />
                  </Link>
                </div>
              ))}
            </div>
              </>
            )}
          </section>

          {/* 4. สถานการณ์ภัย: สรุปทั่วประเทศ + จุดที่ใกล้เส้นทาง/ใกล้คุณที่สุด */}
          <section className="card dash-card">
            <div className="sec-head">
              <span>
                <Icon name="alert" size={15} /> สถานการณ์ภัยทั่วประเทศ
              </span>
              <Link href="/map" className="link-btn tiny">
                ดูแผนที่
              </Link>
            </div>
            <div className="type-chips">
              {byType.length === 0 && <span className="tiny muted">ตอนนี้ไม่มีภัยที่ต้องเฝ้าระวัง</span>}
              {byType.map(({ t, high, all }) => (
                <Link key={t} href="/map" className={`type-chip ${high ? "high" : ""}`} title={t === "FLOOD" ? "จากดาวเทียม GISTDA" : undefined}>
                  <Icon name={HAZARD_META[t].icon} size={15} />
                  {HAZARD_META[t].label} <b>{all}</b>
                  {high > 0 && <small>รุนแรง {high}</small>}
                </Link>
              ))}
            </div>
            <div className="sec-head" style={{ marginTop: 12 }}>
              <span>
                <Icon name="pin" size={15} /> {route ? `ใกล้เส้นทาง ${trip ? tripNo(trip) : ""}` : "ใกล้คุณที่สุด"}
              </span>
            </div>
            <div className="dash-scroll stack" style={{ gap: 6 }}>
              {closest.length === 0 && <p className="small muted">ไม่มีจุดเสี่ยงใกล้ๆ</p>}
              {closest.map(({ h, d }) => (
                <Link key={h.hazard_id} href={`/map?focus=${h.hazard_id}`} className="mini-row">
                  <span className="card-icon" style={{ width: 30, height: 30, background: `${RISK_COLOR[h.severity]}1a`, color: RISK_COLOR[h.severity] }}>
                    <Icon name={HAZARD_META[h.hazard_type].icon} size={16} />
                  </span>
                  <span className="grow" style={{ minWidth: 0 }}>
                    <span className="small bold ellipsis" style={{ display: "block" }} title={h.title_th}>
                      {h.title_th}
                    </span>
                    <span className="tiny muted">
                      {h.province ? `${h.province} · ` : ""}ห่าง{route ? "เส้นทาง" : "คุณ"} {d.toFixed(0)} กม.
                    </span>
                  </span>
                  <span className={`risk ${h.severity} nobreak`}>{RISK_TH[h.severity]}</span>
                </Link>
              ))}
            </div>
          </section>

          {/* 5. อากาศรอบตัวตอนนี้ (อากาศตามเส้นทางอยู่การ์ดที่ 3) + ทางลัด */}
          <section className="card dash-card">
            <div className="row nowrap" style={{ gap: 12, marginBottom: 10 }}>
              <span className="card-icon sun" style={{ width: 44, height: 44, borderRadius: 14 }}>
                <Icon name={here ? weatherIcon(here.forecast) : "cloud"} size={24} />
              </span>
              <div style={{ minWidth: 0 }}>
                <p className="tiny muted">รอบตัวคุณตอนนี้{area ? ` · ${thaiTime(area.updated_at)}` : ""}</p>
                {here ? (
                  <p className="row nowrap" style={{ gap: 8 }}>
                    <b style={{ fontSize: "calc(22px * var(--fs))", lineHeight: 1.1 }}>{here.forecast.temp_c}°</b>
                    <span className="small muted ellipsis">
                      {here.forecast.condition_th} · ลม {here.forecast.wind_kmh} กม./ชม.
                    </span>
                  </p>
                ) : (
                  <p className="small muted">กำลังโหลด...</p>
                )}
              </div>
            </div>
            <div className="sec-head">
              <span>
                <Icon name="rain" size={15} /> ฝนรอบตัว (รัศมี ~25 กม.)
              </span>
            </div>
            <div className="dash-scroll wx-list">
              {aroundWx.map((c) => (
                    <div key={c.dir} className="wx-row">
                      <span className="wx-time">{c.dir}</span>
                      <span className="grow ellipsis small">{c.forecast.condition_th}</span>
                      <span className="row nowrap tiny muted" style={{ gap: 4 }}>
                        <Icon name={weatherIcon(c.forecast)} size={15} />
                        {c.forecast.rain_mm_per_h} มม. · {Math.round(c.forecast.temp_c)}°
                      </span>
                    </div>
                  ))}
            </div>
            <div className="quick mini">
              <Link href="/trips?new=1" title="วางแผนทริป">
                <Icon name="plus" size={17} />
                ทริปใหม่
              </Link>
              <button onClick={() => openChat()} title="ถามน้องกิเลน">
                <Icon name="chat" size={17} />
                น้องกิเลน
              </button>
              <Link href="/emergency" title="เบอร์ฉุกเฉินและวิธีรับมือ">
                <Icon name="shield" size={17} />
                รับมือภัย
              </Link>
              <a href={`tel:${hotline.phone}`} className="sos" title={hotline.name_th}>
                <Icon name="phone" size={17} />
                {hotline.phone}
              </a>
            </div>
          </section>
          {bottom.handles}
        </div>
        {cols.handles}
        {rows.handles}
      </div>
    </>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Home />
    </Suspense>
  );
}
