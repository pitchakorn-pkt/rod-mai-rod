"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import Map from "@/components/Map";
import Icon from "@/components/Icon";
import { Topbar } from "@/components/Shell";
import { RiskChip } from "@/components/ui";
import { HAZARD_META, RISK_COLOR, RISK_TH, thaiDateTime, type Hazard, type HazardType, type LatLng } from "@/lib/data";
import { api } from "@/lib/api";
import { MAP_STYLES, applyMapStyle, getMapStyle, type MapStyle } from "@/lib/mapStyle";
import { useApp } from "@/lib/store";
import { distanceKm } from "@/lib/segments";

const TYPES = Object.keys(HAZARD_META) as HazardType[];
const LAYERS_KEY = "rmr_redesign_layers";
const NEAR_KM = 20;
// สีวงรัศมีตามชนิดภัย ไม่ใช้สีเขียว/ส้ม/แดง เพราะวงสีเขียวกลืนกับแผนที่
const RADIUS_COLOR: Partial<Record<HazardType, string>> = { RAIN: "#2f6fe4", HEAVY_RAIN: "#1d4ed8", STRONG_WIND: "#8b5cf6", STORM: "#6d28d9", EARTHQUAKE: "#a16207" };
const WIDE_AREA = new Set(Object.keys(RADIUS_COLOR) as HazardType[]);
const SEV_RANK = { HIGH: 0, MEDIUM: 1, LOW: 2 } as const;

type Place = LatLng & { name: string; detail?: string | null };

// ช่องค้นหาบนแผนที่: ค้นทั้งสถานที่ (GET /places/search) และหมุดภัยที่มีอยู่แล้ว (ชื่อ/จังหวัด)
function MapSearch({ hazards, onPlace, onHazard }: { hazards: Hazard[]; onPlace: (p: Place) => void; onHazard: (h: Hazard) => void }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [places, setPlaces] = useState<Place[]>([]);
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [hi, setHi] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const t = q.trim();

  // รอพิมพ์เสร็จ 350 มิลลิวินาทีค่อยค้นสถานที่
  useEffect(() => {
    if (t.length < 2) {
      setPlaces([]);
      setState("idle");
      return;
    }
    setState("loading");
    let live = true;
    const timer = setTimeout(() => {
      api<{ places: Place[] }>(`/places/search?q=${encodeURIComponent(t)}`)
        .then((d) => live && (setPlaces(d.places), setState("done")))
        .catch(() => live && (setPlaces([]), setState("error")));
    }, 350);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [t]);
  // คลิกข้างนอกแล้วปิดรายการ
  useEffect(() => {
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const hz =
    t.length < 2
      ? []
      : hazards
          .filter((h) => h.title_th.includes(t) || h.province?.includes(t) || HAZARD_META[h.hazard_type].label.includes(t))
          .sort((a, b) => SEV_RANK[a.severity] - SEV_RANK[b.severity])
          .slice(0, 5);
  const items: ({ kind: "place"; p: Place } | { kind: "hazard"; h: Hazard })[] = [
    ...places.map((p) => ({ kind: "place" as const, p })),
    ...hz.map((h) => ({ kind: "hazard" as const, h })),
  ];
  function pick(i: number) {
    const it = items[i];
    if (!it) return;
    if (it.kind === "place") onPlace(it.p);
    else onHazard(it.h);
    setQ(it.kind === "place" ? it.p.name : it.h.title_th);
    setOpen(false);
  }

  return (
    <div className="map-search" ref={box}>
      <div className="input-icon">
        <Icon name="search" size={18} />
        <input
          className="input"
          value={q}
          placeholder="ค้นหาสถานที่ หรือจุดเสี่ยงภัย"
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
            setHi(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") setHi((h) => Math.min(h + 1, items.length - 1));
            if (e.key === "ArrowUp") setHi((h) => Math.max(h - 1, 0));
            if (e.key === "Enter") pick(hi);
            if (e.key === "Escape") setOpen(false);
          }}
          aria-label="ค้นหาบนแผนที่"
        />
        {q && (
          <button className="map-search-clear" onClick={() => (setQ(""), setOpen(false))} aria-label="ล้างคำค้น">
            <Icon name="x" size={15} />
          </button>
        )}
      </div>
      {open && t.length >= 2 && (
        <div className="suggest map-suggest">
          {places.length > 0 && <p className="tiny muted suggest-head">สถานที่</p>}
          {places.map((p, i) => (
            <button key={`p-${p.name}-${i}`} className={i === hi ? "on" : ""} onMouseDown={(e) => (e.preventDefault(), pick(i))}>
              <Icon name="pin" size={18} />
              <span>
                <span className="bold">{p.name}</span>
                {p.detail && (
                  <>
                    <br />
                    <span className="tiny muted">{p.detail}</span>
                  </>
                )}
              </span>
            </button>
          ))}
          {hz.length > 0 && <p className="tiny muted suggest-head">จุดเสี่ยงภัย</p>}
          {hz.map((h, j) => (
            <button key={h.hazard_id} className={places.length + j === hi ? "on" : ""} onMouseDown={(e) => (e.preventDefault(), pick(places.length + j))}>
              <span style={{ color: RISK_COLOR[h.severity], display: "grid" }}>
                <Icon name={HAZARD_META[h.hazard_type].icon} size={18} />
              </span>
              <span>
                <span className="bold">{h.title_th}</span>
                <br />
                <span className="tiny muted">
                  ความเสี่ยง{RISK_TH[h.severity]}
                  {h.province ? ` · ${h.province}` : ""}
                </span>
              </span>
            </button>
          ))}
          {state === "loading" && items.length === 0 && <p className="small muted" style={{ padding: 10 }}>กำลังค้นหา...</p>}
          {state === "error" && hz.length === 0 && <p className="small muted" style={{ padding: 10 }}>ค้นหาสถานที่ไม่ได้ตอนนี้ ลองใหม่อีกครั้ง</p>}
          {state === "done" && items.length === 0 && <p className="small muted" style={{ padding: 10 }}>ไม่เจอ ลองพิมพ์ชื่ออื่น</p>}
        </div>
      )}
    </div>
  );
}
const SOURCE_TH: Record<string, string> = { GISTDA: "ภาพถ่ายดาวเทียม GISTDA (สทอภ.)", DOH: "กรมทางหลวง (ศูนย์บริหารงานอุบัติภัย)", OPEN_METEO: "พยากรณ์อากาศชั่วโมงนี้", GDACS: "GDACS", USGS: "USGS", DERIVED: "ประเมินโดยระบบ ไม่ใช่ประกาศทางการ" };

function RiskMap() {
  const focus = useSearchParams().get("focus");
  const [on, setOn] = useState<Record<string, boolean>>(Object.fromEntries(TYPES.map((t) => [t, true])));
  const [sev, setSev] = useState<"all" | "high">("all");
  const [showFlood, setShowFlood] = useState(true);
  const [mapStyle, setMapStyle] = useState<MapStyle>("soft");
  useEffect(() => setMapStyle(getMapStyle()), []);
  const { hazards: HAZARDS, hazardsError, floodWindow, emergency: EMERGENCY, nextTrip, here, locate } = useApp();
  const [selId, setSelId] = useState<string | null>(focus);
  const [showGuide, setShowGuide] = useState(false);
  // จุดที่แผนที่จะบินไป (ตำแหน่งฉัน / ผลค้นหา / หมุดที่เลือก)
  const [fly, setFly] = useState<(LatLng & { zoom?: number }) | null>(null);
  const [found, setFound] = useState<Place | null>(null);
  // แผงชั้นข้อมูลพับได้ทุกขนาดจอ จำสถานะล่าสุดไว้ในเครื่อง ครั้งแรกจอเล็กเริ่มแบบพับ
  const [layersOpen, setLayersOpenState] = useState(true);
  useEffect(() => {
    let saved: string | null = null;
    try {
      saved = localStorage.getItem(LAYERS_KEY);
    } catch {}
    setLayersOpenState(saved ? saved === "open" : !window.matchMedia("(max-width: 860px)").matches);
  }, []);
  function setLayersOpen(open: boolean) {
    setLayersOpenState(open);
    try {
      localStorage.setItem(LAYERS_KEY, open ? "open" : "closed");
    } catch {}
  }
  const hiddenLayers = TYPES.filter((t) => !on[t]).length + (showFlood ? 0 : 1) + (sev === "high" ? 1 : 0);

  const counts = useMemo(() => Object.fromEntries(TYPES.map((t) => [t, HAZARDS.filter((h) => h.hazard_type === t).length])), [HAZARDS]);
  const shown = HAZARDS.filter((h) => on[h.hazard_type] && (sev === "all" || h.severity !== "LOW"));
  const sel = HAZARDS.find((h) => h.hazard_id === selId) ?? null;
  useEffect(() => {
    if (sel) setFly({ lat: sel.lat, lng: sel.lng });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selId, !!sel]);
  // ภัยรอบจุดที่ค้นเจอ (น้ำท่วม 10 กม. ภัยอื่น 20 กม. เหมือน risk-decision)
  const foundNear = useMemo(() => {
    if (!found) return [];
    return HAZARDS.map((h) => ({ h, d: distanceKm(found, h) }))
      .filter(({ h, d }) => d <= (h.hazard_type === "FLOOD" ? 10 : NEAR_KM))
      .sort((a, b) => SEV_RANK[a.h.severity] - SEV_RANK[b.h.severity] || a.d - b.d);
  }, [found, HAZARDS]);
  const foundLevel = foundNear[0]?.h.severity ?? "LOW";

  return (
    <>
      <Topbar title="แผนที่ความเสี่ยง" sub={hazardsError ? `โหลดหมุดภัยไม่ได้: ${hazardsError}` : "ฝน ลมแรง น้ำท่วมจากดาวเทียม ดินถล่ม และแผ่นดินไหวทั่วประเทศไทย"} />
      <div className="mapfull">
        <div className="map">
          <Map
            zoom={6}
            center={{ lat: 13.2, lng: 101 }}
            flyTo={fly}
            // เปิดชั้นภาพเมื่อรู้ชุดข้อมูลแล้วเท่านั้น (ระบบเพิ่งเปิด GISTDA ยังโหลดไม่เสร็จ หรือไม่มี key = null)
            flood={showFlood && floodWindow ? floodWindow : false}
            pins={[
              ...(found ? [{ id: "found", lat: found.lat, lng: found.lng, color: "#38bdf8", icon: "pin", label: found.name, tip: found.name, selected: true }] : []),
              ...shown.map((h) => ({
              id: h.hazard_id,
              lat: h.lat,
              lng: h.lng,
              color: RISK_COLOR[h.severity],
              icon: HAZARD_META[h.hazard_type].icon,
              // น้ำท่วม/ดินถล่มเป็นภัยเฉพาะจุด ไม่วาดวง ภัยวงกว้างวาดรัศมี 20 กม. ตามที่ risk-decision ใช้นับ
              radiusKm: WIDE_AREA.has(h.hazard_type) ? NEAR_KM : undefined,
              strong: h.severity === "HIGH",
              radiusColor: RADIUS_COLOR[h.hazard_type],
              selected: h.hazard_id === selId,
              tip: h.title_th,
              onClick: () => {
                setSelId(h.hazard_id);
                setShowGuide(false);
                setFound(null);
              },
            })),
            ]}
          />
        </div>

        {!layersOpen && (
          <button className="btn ghost layers-toggle" onClick={() => setLayersOpen(true)} aria-expanded={false}>
            <Icon name="layers" size={18} />
            ชั้นข้อมูล · {shown.length} จุด
            {hiddenLayers > 0 && <span className="badge" style={{ background: "var(--mid)" }}>กรอง {hiddenLayers}</span>}
          </button>
        )}
        {layersOpen && (
        <div className="panel layers">
          <button className="layers-head" onClick={() => setLayersOpen(false)} aria-expanded aria-label="พับชั้นข้อมูล">
            <span className="row bold" style={{ gap: 8 }}>
              <Icon name="layers" /> ชั้นข้อมูล
            </span>
            <span className="row" style={{ gap: 6 }}>
              <span className="tiny muted">{shown.length} จุด</span>
              <span className="layers-fold" title="พับ">
                <Icon name="chevron" size={16} />
              </span>
            </span>
          </button>
          {/* แตะได้ทั้งแถว ไม่ต้องเล็งสวิตช์เล็กๆ บนมือถือ */}
          {TYPES.map((t) => (
            <button key={t} className="layer" aria-pressed={on[t]} onClick={() => setOn({ ...on, [t]: !on[t] })}>
              <span className="card-icon" style={{ width: 32, height: 32, borderRadius: 10 }}>
                <Icon name={HAZARD_META[t].icon} size={17} />
              </span>
              <span className="grow small">{HAZARD_META[t].label}</span>
              <span className="tiny muted">{counts[t]}</span>
              <span className={`switch ${on[t] ? "on" : ""}`} aria-hidden />
            </button>
          ))}
          <button className="layer layer-wide" aria-pressed={showFlood} onClick={() => setShowFlood(!showFlood)}>
            <span className="card-icon" style={{ width: 32, height: 32, borderRadius: 10, background: "#3d6fd6", color: "#fff" }}>
              <Icon name="flood" size={17} />
            </span>
            <span className="grow small">
              พื้นที่น้ำท่วมจากดาวเทียม
              <br />
              <span className="tiny muted">{floodWindow ? `GISTDA ${floodWindow === "7days" ? "7" : "3"} วันล่าสุด` : "GISTDA ยังไม่มีข้อมูล"}</span>
            </span>
            <span className={`switch ${showFlood ? "on" : ""}`} aria-hidden />
          </button>
          <p className="label" style={{ margin: "12px 0 6px" }}>สีแผนที่</p>
          <div className="seg" style={{ width: "100%" }}>
            {MAP_STYLES.map((m) => (
              <button
                key={m.id}
                className={mapStyle === m.id ? "on" : ""}
                style={{ flex: 1 }}
                onClick={() => {
                  setMapStyle(m.id);
                  applyMapStyle(m.id);
                }}
              >
                {m.label}
              </button>
            ))}
          </div>
          <div className="seg" style={{ marginTop: 10, width: "100%" }}>
            <button className={sev === "all" ? "on" : ""} style={{ flex: 1 }} onClick={() => setSev("all")}>ทุกระดับ</button>
            <button className={sev === "high" ? "on" : ""} style={{ flex: 1 }} onClick={() => setSev("high")}>เฉพาะที่เสี่ยง</button>
          </div>
        </div>
        )}

        <div className="map-fab locate-fab">
          <button className="icon-btn" aria-label="ตำแหน่งของฉัน" onClick={async () => setFly({ ...((await locate()) ?? here), zoom: 11 })}>
            <Icon name="locate" />
          </button>
        </div>

        <MapSearch
          hazards={HAZARDS}
          onPlace={(p) => {
            setFound(p);
            setSelId(null);
            setFly({ lat: p.lat, lng: p.lng, zoom: 10 });
          }}
          onHazard={(h) => {
            setFound(null);
            setSelId(h.hazard_id);
            setShowGuide(false);
            setFly({ lat: h.lat, lng: h.lng, zoom: 11 });
          }}
        />

        {found && !sel && (
          <div className="panel detail">
            <div className="row nowrap" style={{ alignItems: "flex-start" }}>
              <span className="card-icon" style={{ width: 52, height: 52, borderRadius: 16, background: `${RISK_COLOR[foundLevel]}1f`, color: RISK_COLOR[foundLevel] }}>
                <Icon name="pin" size={26} />
              </span>
              <div className="grow" style={{ minWidth: 0 }}>
                <h3>{found.name}</h3>
                {found.detail && <p className="tiny muted">{found.detail}</p>}
                <div className="row" style={{ gap: 6, marginTop: 4 }}>
                  <span className={`risk ${foundLevel}`}>ความเสี่ยง{RISK_TH[foundLevel]}</span>
                  <span className="tiny muted">{foundNear.length ? `ภัยรอบจุดนี้ ${foundNear.length} จุด` : "ไม่มีภัยรอบจุดนี้"}</span>
                </div>
              </div>
              <button className="icon-btn" style={{ width: 34, height: 34 }} onClick={() => setFound(null)} aria-label="ปิด">
                <Icon name="x" size={16} />
              </button>
            </div>
            <div className="stack" style={{ gap: 6, margin: "12px 0", gridTemplateColumns: "minmax(0, 1fr)" }}>
              {foundNear.slice(0, 5).map(({ h, d }) => (
                <button key={h.hazard_id} className="mini-row" style={{ textAlign: "left", cursor: "pointer" }} onClick={() => setSelId(h.hazard_id)}>
                  <span className="card-icon" style={{ width: 30, height: 30, background: `${RISK_COLOR[h.severity]}1a`, color: RISK_COLOR[h.severity] }}>
                    <Icon name={HAZARD_META[h.hazard_type].icon} size={16} />
                  </span>
                  <span className="grow" style={{ minWidth: 0 }}>
                    <span className="small bold ellipsis" style={{ display: "block" }}>{h.title_th}</span>
                    <span className="tiny muted">ห่าง {d.toFixed(1)} กม.</span>
                  </span>
                </button>
              ))}
              {foundNear.length === 0 && <p className="small muted">ในรัศมี {NEAR_KM} กม. ไม่มีหมุดภัยตอนนี้ (น้ำท่วมนับ 10 กม.)</p>}
            </div>
            <Link href={`/trips?new=1&to=${found.lat.toFixed(5)},${found.lng.toFixed(5)}&name=${encodeURIComponent(found.name)}`} className="btn sm block">
              <Icon name="route" size={16} />
              วางแผนทริปไปที่นี่
            </Link>
          </div>
        )}

        <div className="panel legend">
          <span><i style={{ background: RISK_COLOR.LOW }} />ต่ำ</span>
          <span><i style={{ background: RISK_COLOR.MEDIUM }} />ปานกลาง</span>
          <span><i style={{ background: RISK_COLOR.HIGH }} />สูง</span>
          <span className="legend-sep" />
          <span><i className="ring-key" style={{ borderColor: RADIUS_COLOR.RAIN }} />วงฝน</span>
          <span><i className="ring-key" style={{ borderColor: RADIUS_COLOR.STRONG_WIND }} />วงลม/พายุ</span>
        </div>

        {sel && (
          <div className="panel detail">
            <div className="row nowrap" style={{ alignItems: "flex-start" }}>
              <span className="card-icon" style={{ width: 52, height: 52, borderRadius: 16, background: `${RISK_COLOR[sel.severity]}1f`, color: RISK_COLOR[sel.severity] }}>
                <Icon name={HAZARD_META[sel.hazard_type].icon} size={26} />
              </span>
              <div className="grow">
                <h3>{sel.title_th}</h3>
                <div className="row" style={{ gap: 6, marginTop: 4 }}>
                  <RiskChip level={sel.severity} />
                  <span className="tiny muted">{HAZARD_META[sel.hazard_type].label}{sel.province ? ` · ${sel.province}` : ""}</span>
                </div>
              </div>
              <button className="icon-btn" style={{ width: 34, height: 34 }} onClick={() => setSelId(null)} aria-label="ปิด">
                <Icon name="x" size={16} />
              </button>
            </div>
            <p className="row tiny muted" style={{ gap: 6, margin: "12px 0" }}>
              <Icon name="clock" size={14} /> อัปเดต {thaiDateTime(sel.updated_at)} · {SOURCE_TH[sel.source] ?? sel.source}
            </p>
            {sel.source === "DOH" && (
              <div className="notice" style={{ marginBottom: 12 }}>
                <Icon name="info" size={18} />
                <span className="small">เหตุบนทางหลวงที่กรมทางหลวงรายงานและยังไม่จบ สอบถามสภาพถนนล่าสุดได้ที่สายด่วนกรมทางหลวง 1586</span>
              </div>
            )}
            {sel.source === "GISTDA" && (
              <div className="notice" style={{ marginBottom: 12 }}>
                <Icon name="info" size={18} />
                <span className="small">พื้นที่น้ำท่วมที่ตรวจพบจากดาวเทียมเรดาร์ ใช้ได้แม้ฟ้าปิด ถ้าเส้นทางผ่านตำบลนี้ควรเช็กเส้นทางเลี่ยง</span>
              </div>
            )}
            <div className="grid-2" style={{ gap: 8 }}>
              <button className="btn ghost sm" onClick={() => setShowGuide(!showGuide)}>
                <Icon name="shield" size={16} />
                วิธีรับมือ
              </button>
              <Link href={nextTrip ? `/trips?id=${nextTrip.trip_id}` : "/trips?new=1"} className="btn sm">
                <Icon name="route" size={16} />
                เลี่ยงจุดนี้
              </Link>
            </div>
            {showGuide && (
              <div style={{ marginTop: 14 }}>
                <ol className="steps">
                  {(EMERGENCY[sel.hazard_type]?.steps_th ?? []).map((s) => (
                    <li key={s} className="small">{s}</li>
                  ))}
                </ol>
                <a href="tel:1784" className="btn danger block sm" style={{ marginTop: 12 }}>
                  <Icon name="phone" size={16} />
                  โทรสายด่วน ปภ. 1784
                </a>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}

export default function Page() {
  return (
    <Suspense>
      <RiskMap />
    </Suspense>
  );
}
