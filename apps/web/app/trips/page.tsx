"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import Map from "@/components/Map";
import Icon from "@/components/Icon";
import PlanTrip from "@/components/PlanTrip";
import { Topbar, openChat } from "@/components/Shell";
import { CardHead, RecoBanner, RiskChip } from "@/components/ui";
import { Checklist, DepartureAdvisor, StopList, tripSuggestions } from "@/components/trip";
import { HAZARD_META, RECO, RISK_COLOR, RISK_TH, duration, riskKey, thaiDate, thaiDateTime, thaiTime, type Forecast, type Hazard, type LatLng } from "@/lib/data";
import { useApp, type LiveTrip, type NewTrip } from "@/lib/store";
import { api } from "@/lib/api";
import { coloredSegments, distanceKm } from "@/lib/segments";
import { useSplit } from "@/lib/layout";

// ---------- ฝนและภัยตามเส้นทาง ----------
const RAIN_MIN_MM = 2; // ฝนเบาขึ้นไป (CONTRACT: RAIN เริ่ม 2 มม./ชม.)
const HAZARD_NEAR_KM = 20;
const ON_ROUTE_KM = 2;
const rainColor = (mm: number) => (mm > 35 ? "#1d3fb8" : mm >= 10 ? "#3b82f6" : "#7cc4ff");
type RoutePoint = { lat: number; lng: number; forecast: Forecast | null };

// พยากรณ์ฝน ณ เวลาที่รถผ่านแต่ละจุดของเส้นทาง (POST /forecast/route)
function useRouteRain(geometry: LatLng[] | undefined, departure: string | undefined, minutes: number | undefined) {
  const [state, setState] = useState<{ points: RoutePoint[]; outOfRange: boolean } | null>(null);
  // โหลดทริปใหม่ทุกครั้ง geometry เป็น array ใหม่แม้เส้นเดิม ใช้ key ที่บอกว่าเส้น/เวลาเปลี่ยนจริงแทน ไม่งั้นยิงซ้ำทุกครั้ง
  const geo = useRef(geometry);
  geo.current = geometry;
  const last = geometry?.[geometry.length - 1];
  const key = geometry?.length ? `${departure}|${minutes}|${geometry.length}|${geometry[0].lat},${geometry[0].lng}|${last?.lat},${last?.lng}` : "";
  useEffect(() => {
    const geometry = geo.current;
    if (!key || !geometry?.length || !departure || !minutes) return;
    let live = true;
    setState(null);
    api<{ points: RoutePoint[]; warnings: string[] }>("/forecast/route", {
      method: "POST",
      body: { geometry, departure_time: departure, duration_min: minutes },
      timeoutMs: 30000,
    })
      .then((d) => live && setState({ points: d.points ?? [], outOfRange: (d.warnings ?? []).includes("FORECAST_OUT_OF_RANGE") }))
      .catch(() => live && setState({ points: [], outOfRange: false }));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state;
}

// หมุดภัยห่างเส้นทางไม่เกิน 20 กม. (ไม่นับฝนชั่วโมงนี้ เพราะเส้นทางดูฝนตอนผ่านแล้ว)
function hazardsNearRoute(hazards: Hazard[], geometry: LatLng[]) {
  const step = Math.max(1, Math.floor(geometry.length / 80));
  const pts = geometry.filter((_, i) => i % step === 0);
  return hazards
    .filter((h) => h.source !== "OPEN_METEO")
    .map((h) => ({ h, d: Math.min(...pts.map((p) => distanceKm(p, h))) }))
    .filter((x) => x.d <= HAZARD_NEAR_KM);
}

const STATUS = {
  FRESH: null,
  STALE: { text: "แผนเก่า", tone: "var(--mid)" },
  NONE: { text: "ยังไม่วางแผน", tone: "var(--none)" },
} as const;

const tripNo = (t: LiveTrip) => `Trip ${String(t.trip_no).padStart(2, "0")}`;

// ค่าเริ่มต้นของฟอร์มแก้ทริป ชื่อที่ตั้งอัตโนมัติ (ไป...) ไม่ใส่ในช่อง
const toForm = (t: LiveTrip): NewTrip => ({
  title: t.title === `ไป${t.destination}` ? "" : t.title,
  origin: t.raw.origin,
  destination: t.raw.destination,
  stops: t.raw.waypoints,
  departure: t.departure_time,
});

const isPast = (t: LiveTrip) => new Date(t.departure_time).getTime() < Date.now() - 12 * 3600_000;

// แถบทริปแนวนอนด้านบน ทริปเยอะเกินจอเลื่อนได้ด้วยปุ่มลูกศร ล้อเมาส์ หรือลาก
// เรียงทริปที่กำลังจะถึงก่อน (ใกล้สุดก่อน) ทริปที่ผ่านไปแล้วต่อท้ายแบบจางลง
function TripStrip({ trips, sel, onSel, onEdit }: { trips: LiveTrip[]; sel: string; onSel: (id: string) => void; onEdit: (t: LiveTrip) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [edge, setEdge] = useState({ left: false, right: false });

  function measure() {
    const el = ref.current;
    if (!el) return;
    setEdge({ left: el.scrollLeft > 4, right: el.scrollLeft + el.clientWidth < el.scrollWidth - 4 });
  }
  useEffect(() => {
    measure();
    const el = ref.current;
    if (!el) return;
    // ล้อเมาส์แนวตั้งเลื่อนแถบแนวนอน
    const wheel = (e: WheelEvent) => {
      if (Math.abs(e.deltaY) <= Math.abs(e.deltaX) || el.scrollWidth <= el.clientWidth) return;
      e.preventDefault();
      el.scrollLeft += e.deltaY;
    };
    el.addEventListener("wheel", wheel, { passive: false });
    window.addEventListener("resize", measure);
    return () => {
      el.removeEventListener("wheel", wheel);
      window.removeEventListener("resize", measure);
    };
  }, [trips.length]);
  // ทริปที่เลือกต้องมองเห็นเสมอ
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>(".trip-card.on")?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  }, [sel]);
  const page = (dir: 1 | -1) => ref.current?.scrollBy({ left: dir * (ref.current.clientWidth - 120), behavior: "smooth" });

  const firstPast = trips.findIndex(isPast);
  return (
    <div className={`strip-wrap ${edge.left ? "fade-l" : ""} ${edge.right ? "fade-r" : ""}`}>
      {edge.left && (
        <button className="strip-arrow l" onClick={() => page(-1)} aria-label="ทริปก่อนหน้า">
          <Icon name="back" size={18} />
        </button>
      )}
      <div className="trip-strip" ref={ref} onScroll={measure}>
        {trips.map((t, i) => {
          const st = STATUS[t.plan_status];
          const past = isPast(t);
          return (
            <div key={t.trip_id} className="strip-item">
              {i === firstPast && <span className="strip-sep">ผ่านไปแล้ว</span>}
              <button className={`trip-card ${t.trip_id === sel ? "on" : ""} ${past ? "past" : ""}`} onClick={() => onSel(t.trip_id)}>
                <div className="row between nowrap">
                  <span className="tiny muted">{tripNo(t)}</span>
                  {past ? (
                    <span className="tiny muted">จบแล้ว</span>
                  ) : st ? (
                    <span className="tiny bold" style={{ color: st.tone }}>
                      {st.text}
                    </span>
                  ) : (
                    <RiskChip level={t.plan?.risk_level} />
                  )}
                </div>
                <span className="bold ellipsis">{t.title}</span>
                <span className="row tiny muted nowrap" style={{ gap: 6 }}>
                  <Icon name="calendar" size={14} />
                  {thaiDateTime(t.departure_time)}
                </span>
              </button>
              <button className="card-edit" onClick={() => onEdit(t)} aria-label={`แก้ไข ${tripNo(t)}`} title="แก้ไขทริป">
                <Icon name="edit" size={14} />
              </button>
            </div>
          );
        })}
      </div>
      {edge.right && (
        <button className="strip-arrow r" onClick={() => page(1)} aria-label="ทริปถัดไป">
          <Icon name="chevron" size={18} />
        </button>
      )}
    </div>
  );
}

// ลิงก์เส้นทาง Google Maps: ต้นทาง ปลายทาง และจุดแวะตามลำดับ ใช้พิกัดให้หมุดตรงกับที่ตั้งไว้ (Google รับจุดแวะไม่เกิน 9 จุด)
function googleMapsUrl(t: LiveTrip["raw"]) {
  const at = (p: { lat: number; lng: number }) => `${p.lat},${p.lng}`;
  const q = new URLSearchParams({ api: "1", origin: at(t.origin), destination: at(t.destination), travelmode: "driving" });
  if (t.waypoints.length) q.set("waypoints", t.waypoints.slice(0, 9).map(at).join("|"));
  return `https://www.google.com/maps/dir/?${q}`;
}

function TripDetail({ trip, onDeleted, onEdit, note }: { trip: LiveTrip; onDeleted: () => void; onEdit: () => void; note?: string | null }) {
  const plan = trip.plan;
  const { planTrip, deleteTrip, shiftTrip, hazards } = useApp();
  const [routeId, setRouteId] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [shared, setShared] = useState(false);
  const cols = useSplit("trip_cols", [1.45, 1, 0.95], { cssVar: "--trip-cols", min: 0.25, label: "คอลัมน์ทริป" });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(note ?? null);
  useEffect(() => {
    if (note) setError(note);
  }, [note]);
  const no = tripNo(trip);

  async function run(label: string, job: () => Promise<void>) {
    setBusy(label);
    setError(null);
    try {
      await job();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  const mapsUrl = googleMapsUrl(trip.raw);
  function share() {
    const text = [`${trip.title} (${no})`, `${trip.origin} → ${trip.destination}`, `ออก ${thaiDateTime(trip.departure_time)}`];
    if (plan) text.push(`ความเสี่ยง${RISK_TH[riskKey(plan.risk_level)]} · ${RECO[plan.recommendation].title}`, plan.summary_th);
    // มือถือเปิดเมนูแชร์ของเครื่อง (LINE ฯลฯ) คอมคัดลอกข้อความพร้อมลิงก์ Google Maps
    if (navigator.share) {
      navigator.share({ title: trip.title, text: text.join("\n"), url: mapsUrl }).catch(() => {});
      return;
    }
    text.push(`ดูเส้นทางใน Google Maps: ${mapsUrl}`);
    navigator.clipboard?.writeText(text.join("\n")).catch(() => {});
    setShared(true);
    setTimeout(() => setShared(false), 2000);
  }
  const route = plan?.route_options.find((r) => r.route_id === routeId) ?? plan?.route_options.find((r) => r.is_recommended);
  const segments = useMemo(() => (route && plan ? coloredSegments(route.geometry, plan.waypoints, hazards) : []), [route, plan, hazards]);
  const suggest = useMemo(() => tripSuggestions(plan, segments.map((g) => g.tip ?? "")), [plan, segments]);
  const [showRain, setShowRain] = useState(true);
  const [showHazards, setShowHazards] = useState(true);
  const rain = useRouteRain(route?.geometry, plan?.departure_time, route?.duration_min);
  const rainAreas = (rain?.points ?? [])
    .filter((p) => p.forecast && p.forecast.rain_mm_per_h >= RAIN_MIN_MM)
    .map((p, i) => ({
      id: `rain-${i}`,
      lat: p.lat,
      lng: p.lng,
      radiusKm: 7,
      color: rainColor(p.forecast!.rain_mm_per_h),
      tip: `${p.forecast!.condition_th} ${p.forecast!.rain_mm_per_h} มม./ชม. · ผ่านประมาณ ${thaiTime(p.forecast!.time)}`,
    }));
  const nearHazards = useMemo(() => (route ? hazardsNearRoute(hazards, route.geometry) : []), [hazards, route]);

  const title = (
    <div style={{ minWidth: 0 }}>
      <p className="tiny muted">{no} · ออก {thaiDateTime(trip.departure_time)}</p>
      <h2 className="ellipsis">{trip.title}</h2>
      <p className="small ellipsis" style={{ color: "var(--ink-2)" }}>
        {[trip.origin, ...trip.stops, trip.destination].join(" › ")}
      </p>
    </div>
  );
  const actions = (
    <div className="row nowrap" style={{ gap: 6 }}>
      <button className="btn sm ghost" onClick={onEdit} title="แก้ไขทริป">
        <Icon name="edit" size={16} />
        <span className="btn-label">แก้ไข</span>
      </button>
      <a className="btn sm ghost" href={mapsUrl} target="_blank" rel="noreferrer" title="เปิดเส้นทางและทุกจุดแวะใน Google Maps">
        <Icon name="map" size={16} />
        <span className="btn-label">Google Maps</span>
      </a>
      <button className="btn sm ghost" onClick={share} aria-label="แชร์" title="แชร์ทริปพร้อมลิงก์ Google Maps">
        <Icon name={shared ? "check" : "share"} size={16} />
        {shared ? "คัดลอกแล้ว" : ""}
      </button>
      <button className="btn sm ghost" onClick={() => setConfirm(true)} aria-label="ลบทริป">
        <Icon name="trash" size={16} />
      </button>
    </div>
  );
  const notices = (
    <>
      {confirm && (
        <div className="banner danger" style={{ marginBottom: 10 }}>
          <span className="b-icon">
            <Icon name="trash" size={18} />
          </span>
          <p className="grow small">
            ลบ <b>{trip.title}</b> ใช่ไหม ลบแล้วกู้คืนไม่ได้
          </p>
          <button className="btn sm danger" disabled={!!busy} onClick={() => run("delete", async () => { await deleteTrip(trip.trip_id); onDeleted(); })}>
            {busy === "delete" ? "กำลังลบ..." : "ลบทริป"}
          </button>
          <button className="btn sm ghost" onClick={() => setConfirm(false)}>
            ยกเลิก
          </button>
        </div>
      )}
      {trip.plan_status === "STALE" && (
        <div className="notice" style={{ marginBottom: 10 }}>
          <Icon name="alert" size={18} />
          <span className="grow">ทริปถูกแก้หลังวางแผน ข้อมูลความเสี่ยงอาจไม่ตรงแล้ว</span>
          <button className="btn sm" disabled={!!busy} onClick={() => run("plan", () => planTrip(trip.trip_id))}>
            {busy === "plan" ? "กำลังวางแผน..." : "วางแผนใหม่"}
          </button>
        </div>
      )}
      {busy === "shift" && (
        <div className="notice" style={{ marginBottom: 10 }}>
          <Icon name="clock" size={18} />
          <span className="grow">กำลังเลื่อนเวลาออกและวางแผนใหม่...</span>
        </div>
      )}
      {error && (
        <div className="banner danger" style={{ marginBottom: 10 }}>
          <span className="b-icon">
            <Icon name="alert" size={18} />
          </span>
          <p className="grow small">{error}</p>
        </div>
      )}
    </>
  );

  if (!plan)
    return (
      <div className="stack-lg">
        <section className="card">
          <div className="row between trip-head" style={{ alignItems: "flex-start", marginBottom: 10 }}>
            {title}
            {actions}
          </div>
          {notices}
        </section>
        <section className="card" style={{ textAlign: "center", padding: 40 }}>
          <img className="qilin-welcome-anim" src="/assets/mascots/trips-qilin-hero.webp" alt="" style={{ width: 120, margin: "0 auto 8px" }} />
          <h2 style={{ marginTop: 8 }}>ยังไม่ได้วางแผนเส้นทาง</h2>
          <p className="muted" style={{ margin: "6px 0 16px" }}>กดวางแผน แล้วน้องกิเลนจะหาเส้นทาง เช็กอากาศ ณ เวลาที่ไปถึง และจุดเสี่ยงภัยให้</p>
          <button className="btn" disabled={!!busy} onClick={() => run("plan", () => planTrip(trip.trip_id))}>
            <Icon name="spark" size={18} />
            {busy === "plan" ? "น้องกิเลนกำลังเช็กเส้นทางและอากาศ..." : "วางแผนเส้นทาง"}
          </button>
        </section>
      </div>
    );

  return (
    <div className="trip-grid split-box" style={cols.style} ref={(el) => void (cols.ref.current = el)}>
      {/* ซ้าย: เส้นทาง */}
      <div className="stack-lg">
        <section className="card o-map dash-card grow">
          <div className="row between trip-head" style={{ alignItems: "flex-start", marginBottom: 10, gap: 12 }}>
            {title}
            <div className="row" style={{ justifyContent: "flex-end", gap: 6 }}>
              <RiskChip level={plan.risk_level} score={plan.risk_score} />
              {actions}
            </div>
          </div>
          {notices}
          <div className="map fill-map">
            <Map
              routes={plan.route_options.map((r) => ({ id: r.route_id, points: r.geometry, color: RISK_COLOR[riskKey(r.risk_level)], active: r.route_id === route?.route_id, onClick: () => setRouteId(r.route_id), segments: r.route_id === route?.route_id ? segments : undefined }))}
              pins={[
                ...(showHazards
                  ? nearHazards.map(({ h, d }) => ({
                      id: h.hazard_id,
                      lat: h.lat,
                      lng: h.lng,
                      color: RISK_COLOR[h.severity],
                      icon: HAZARD_META[h.hazard_type].icon,
                      strong: d <= ON_ROUTE_KM, // ทับเส้นทาง เด่นกว่า
                      tip: `${h.title_th} · ${d <= ON_ROUTE_KM ? "อยู่บนเส้นทาง" : `ห่างเส้นทาง ${d.toFixed(0)} กม.`}`,
                    }))
                  : []),
                ...plan.waypoints.map((w) => ({ id: w.waypoint_id, lat: w.lat, lng: w.lng, color: RISK_COLOR[riskKey(w.risk_level)], icon: w.kind === "DESTINATION" ? "flag" : w.kind === "ORIGIN" ? "car" : "pin", tip: `${w.name} · ${thaiTime(w.eta)}`, keep: true })),
              ]}
              areas={showRain ? rainAreas : []}
              fit={plan.route_options.flatMap((r) => r.geometry)}
              flood
            />
          </div>
          <div className="route-layers">
            <button className={`chip sm ${showRain ? "on" : ""}`} aria-pressed={showRain} onClick={() => setShowRain(!showRain)}>
              <Icon name="rain" size={13} />
              ฝนตอนผ่าน {rain ? `${rainAreas.length} จุด` : "..."}
            </button>
            <button className={`chip sm ${showHazards ? "on" : ""}`} aria-pressed={showHazards} onClick={() => setShowHazards(!showHazards)}>
              <Icon name="alert" size={13} />
              ภัยใกล้เส้นทาง {nearHazards.length} จุด
            </button>
            {rain?.outOfRange && <span className="tiny muted">บางช่วงไกลเกินช่วงพยากรณ์</span>}
          </div>
          <p className="route-legend">
            <span><i style={{ background: RISK_COLOR.LOW }} />ปกติ</span>
            <span><i style={{ background: RISK_COLOR.MEDIUM }} />เฝ้าระวัง</span>
            <span><i style={{ background: RISK_COLOR.HIGH }} />อันตราย</span>
            <span><i className="sq" style={{ background: rainColor(5), opacity: 0.7 }} />วงฝนตอนผ่าน</span>
            <span><i className="sq" />น้ำท่วมจากดาวเทียม</span>
          </p>
          <div className="route-opts">
            {plan.route_options.map((r, i) => (
              <button key={r.route_id} className={`route-opt ${r.route_id === route?.route_id ? "on" : ""}`} onClick={() => setRouteId(r.route_id)}>
                <div className="row between nowrap">
                  <span className="bold nobreak">
                    เส้นทางที่ {i + 1}
                    {r.is_recommended && (
                      <span className="tiny" style={{ color: "var(--violet)", marginLeft: 6 }}>
                        แนะนำ
                      </span>
                    )}
                  </span>
                  <span className="tiny muted nobreak">{duration(r.duration_min)} · {r.distance_km.toFixed(0)} กม.</span>
                </div>
                <span>
                  <RiskChip level={r.risk_level} score={r.risk_score} />
                </span>
              </button>
            ))}
          </div>
        </section>
      </div>

      {/* กลาง: สรุปและเวลาออก */}
      <div className="stack-lg">
        <section className="card o-summary">
          <div className="trip-stats">
            <div className="stat">
              <span>ออก</span>
              <b>{thaiTime(plan.departure_time)}</b>
              <span>{thaiDate(plan.departure_time)}</span>
            </div>
            <div className="stat">
              <span>ถึง</span>
              <b>{thaiTime(plan.arrival_time)}</b>
              <span>{thaiDate(plan.arrival_time)}</span>
            </div>
            <div className="stat">
              <span>ใช้เวลา</span>
              <b>{route ? duration(route.duration_min) : "-"}</b>
              <span>{route?.distance_km.toFixed(0)} กม.</span>
            </div>
          </div>
          <RecoBanner reco={plan.recommendation} summary={plan.summary_th} />
        </section>

        <section className="card o-depart dash-card grow">
          <CardHead icon="spark" tone="sun" title="ออกเวลาไหนดี" sub="กดช่วงเวลาเพื่อเลื่อนทริปทันที" />
          <div className="dash-scroll depart-rows">
            <DepartureAdvisor trip={trip} busy={!!busy} onPick={(h) => h && run("shift", () => shiftTrip(trip.trip_id, h))} />
          </div>
        </section>
      </div>

      {/* ขวา: จุดบนเส้นทางและเช็กลิสต์ */}
      <div className="stack-lg">
        <section className="card o-stops dash-card grow">
          <CardHead icon="pin" title="จุดบนเส้นทาง" sub="อากาศตอนไปถึงแต่ละจุด" />
          <div className="dash-scroll">
            <StopList waypoints={plan.waypoints} />
          </div>
        </section>
        <section className="card o-check dash-card grow">
          <CardHead icon="checklist" tone="aqua" title="เช็กลิสต์ของทริปนี้" sub="เพิ่ม ลบ หรือดับเบิลคลิกเพื่อแก้ได้" />
          <div className="checklist-host">
            <Checklist tripId={trip.trip_id} suggest={suggest} />
          </div>
        </section>
      </div>
      {cols.handles}
    </div>
  );
}

function Trips() {
  const params = useSearchParams();
  const { trips, tripsError, createTrip, updateTrip } = useApp();
  const [editingTrip, setEditingTrip] = useState<LiveTrip | null>(null);
  // บันทึกทริปแล้วแต่วางแผนไม่สำเร็จ บอกเหตุผลที่ทริปนั้น
  const [planNote, setPlanNote] = useState<{ id: string; text: string } | null>(null);
  const [sel, setSelState] = useState(params.get("id") ?? "");
  // จำทริปที่เลือกไว้ใน URL รีเฟรชแล้วยังอยู่ทริปเดิม
  function setSel(id: string) {
    setSelState(id);
    const url = new URL(location.href);
    if (id) url.searchParams.set("id", id);
    else url.searchParams.delete("id");
    url.searchParams.delete("new");
    history.replaceState(null, "", url);
  }
  const [planning, setPlanning] = useState(params.get("new") === "1");
  // URL เปลี่ยนตอนอยู่หน้านี้อยู่แล้ว (กดการแจ้งเตือน / ลิงก์ "วางแผนไปที่นี่") useState ข้างบนไม่อ่านซ้ำ ต้องตามเอง
  const idParam = params.get("id");
  const newParam = params.get("new");
  useEffect(() => {
    if (idParam) setSelState(idParam);
  }, [idParam]);
  useEffect(() => {
    if (newParam === "1") setPlanning(true);
  }, [newParam]);
  // มาจากปุ่ม "วางแผนไปที่นี่" ของที่เที่ยวรอบตัว
  const to = params.get("to")?.split(",").map(Number);
  const preset = to?.length === 2 && to.every(Number.isFinite) ? { lat: to[0], lng: to[1], name: params.get("name") || "ปลายทาง" } : undefined;
  const shown = useMemo(() => {
    const t = (x: LiveTrip) => new Date(x.departure_time).getTime();
    const upcoming = trips.filter((x) => !isPast(x)).sort((a, b) => t(a) - t(b));
    const past = trips.filter(isPast).sort((a, b) => t(b) - t(a));
    return [...upcoming, ...past];
  }, [trips]);
  const trip = trips.find((t) => t.trip_id === sel) ?? shown[0];

  return (
    <>
      <Topbar
        title="ทริปของฉัน"
        sub="วางแผน เทียบเส้นทาง และเช็กความเสี่ยงก่อนออกเดินทาง"
        right={
          <button className="btn" onClick={() => setPlanning(true)}>
            <Icon name="plus" size={18} />
            ทริปใหม่
          </button>
        }
      />
      <div className="trip-page">
      <div className="trips-top">
        <TripStrip trips={shown} sel={trip?.trip_id ?? ""} onSel={setSel} onEdit={setEditingTrip} />
      </div>
      <div className="trip-body">
        {trip ? (
          <TripDetail key={trip.trip_id} trip={trip} note={planNote?.id === trip.trip_id ? planNote.text : null} onDeleted={() => setSel("")} onEdit={() => setEditingTrip(trip)} />
        ) : (
          <section className="card" style={{ textAlign: "center", padding: 40 }}>
            <img className="qilin-welcome-anim" src="/assets/mascots/trips-qilin-hero.webp" alt="" style={{ width: 120, margin: "0 auto 8px" }} />
            <h2 style={{ marginTop: 8 }}>{tripsError ? "โหลดทริปไม่ได้" : "ยังไม่มีทริป"}</h2>
            <p className="muted" style={{ margin: "6px 0 16px" }}>{tripsError ?? "เริ่มวางแผนทริปแรกได้เลย"}</p>
            {!tripsError && (
              <button className="btn" onClick={() => setPlanning(true)}>
                <Icon name="plus" size={18} />
                วางแผนทริปแรก
              </button>
            )}
          </section>
        )}
      </div>
      </div>
      {editingTrip && (
        <PlanTrip
          initial={toForm(editingTrip)}
          onClose={() => setEditingTrip(null)}
          onCreate={async (t) => {
            const planError = await updateTrip(editingTrip.trip_id, t);
            setPlanNote(planError ? { id: editingTrip.trip_id, text: planError } : null);
            setSel(editingTrip.trip_id);
            setEditingTrip(null);
          }}
        />
      )}
      {planning && (
        <PlanTrip
          presetDestination={preset}
          onClose={() => setPlanning(false)}
          onCreate={async (t) => {
            const { trip: made, planError } = await createTrip(t);
            setPlanNote(planError ? { id: made.trip_id, text: planError } : null);
            setSel(made.trip_id);
            setPlanning(false);
          }}
        />
      )}
    </>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Trips />
    </Suspense>
  );
}
