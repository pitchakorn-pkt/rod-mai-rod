"use client";

// ข้อมูลจริงของทั้งเว็บ ดึงจาก api-backend ครั้งเดียวแล้วแชร์ทุกหน้า
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, getToken } from "./api";
import { EMERGENCY as SAMPLE_EMERGENCY, HAZARD_META, type AreaCell, type Emergency, type Hazard, type HazardType, type LatLng, type NearbyPlace, type Plan, type Risk, type Trip } from "./data";

type ApiPlace = LatLng & { name: string };
type ApiTrip = {
  trip_id: string;
  trip_no: number;
  origin: ApiPlace;
  destination: ApiPlace;
  departure_time: string;
  waypoints: ApiPlace[];
  plan_status: Trip["plan_status"];
  plan: Plan | null;
};
export type Area = { center: LatLng; cells: AreaCell[]; updated_at: string };
export type NewTrip = { title: string; origin: ApiPlace; destination: ApiPlace; stops: ApiPlace[]; departure: string };
export type Alert = { icon: string; tone: "sun" | "red" | "aqua"; text: string; href: string };

const BANGKOK: LatLng = { lat: 13.7563, lng: 100.5018 };
// คอมพิวเตอร์หาตำแหน่งจาก Wi-Fi อาจใช้เกิน 4 วิ ให้เวลาถึง 15 วิ
const GEO_OPTIONS: PositionOptions = { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 };
const THAILAND = "min_lat=5.6&min_lng=97.3&max_lat=20.5&max_lng=105.7";
const TITLES_KEY = "rmr_redesign_titles";

// API ยังไม่มีชื่อทริป เก็บชื่อที่ผู้ใช้ตั้งไว้ในเครื่อง
function titles(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(TITLES_KEY) ?? "{}");
  } catch {
    return {};
  }
}
function saveTitle(id: string, title: string) {
  try {
    const all = titles();
    if (title) all[id] = title;
    else delete all[id];
    localStorage.setItem(TITLES_KEY, JSON.stringify(all));
  } catch {}
}

function toTrip(t: ApiTrip, names: Record<string, string>): Trip & { raw: ApiTrip } {
  return {
    trip_id: t.trip_id,
    trip_no: t.trip_no,
    title: names[t.trip_id] ?? `ไป${t.destination.name}`,
    origin: t.origin.name,
    destination: t.destination.name,
    stops: t.waypoints.map((w) => w.name),
    departure_time: t.departure_time,
    plan_status: t.plan_status,
    plan: t.plan,
    departures: [],
    raw: t,
  };
}
export type LiveTrip = ReturnType<typeof toTrip>;

type Store = {
  ready: boolean;
  email: string | null;
  displayName: string | null;
  setDisplayName: (name: string) => Promise<void>;
  changePassword: (current: string, next: string) => Promise<void>;
  trips: LiveTrip[];
  tripsError: string | null;
  nextTrip: LiveTrip | null;
  hazards: Hazard[];
  hazardsError: string | null;
  floodWindow: string | null; // ชุดน้ำท่วม GISTDA ที่ระบบใช้อยู่ 3days / 7days
  emergency: Record<HazardType, Emergency>;
  here: LatLng;
  hereFallback: boolean; // true = ยังไม่ได้ตำแหน่งจริง ใช้กรุงเทพแทน
  locate: () => Promise<LatLng | null>;
  area: Area | null;
  nearby: NearbyPlace[] | null;
  nearbyError: string | null;
  alerts: Alert[];
  reloadTrips: () => Promise<void>;
  createTrip: (t: NewTrip) => Promise<{ trip: LiveTrip; planError: string | null }>;
  planTrip: (id: string) => Promise<void>;
  deleteTrip: (id: string) => Promise<void>;
  updateTrip: (id: string, t: NewTrip) => Promise<string | null>;
  shiftTrip: (id: string, hours: number) => Promise<void>;
};

const Ctx = createContext<Store | null>(null);

export function useApp() {
  const s = useContext(Ctx);
  if (!s) throw new Error("useApp นอก AppProvider");
  return s;
}

const SEV = { HIGH: 0, MEDIUM: 1, LOW: 2 } as const;

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [email, setEmail] = useState<string | null>(null);
  const [displayName, setDisplayNameState] = useState<string | null>(null);
  const [trips, setTrips] = useState<LiveTrip[]>([]);
  const [tripsError, setTripsError] = useState<string | null>(null);
  const [hazards, setHazards] = useState<Hazard[]>([]);
  const [hazardsError, setHazardsError] = useState<string | null>(null);
  const [floodWindow, setFloodWindow] = useState<string | null>(null);
  const [emergency, setEmergency] = useState<Record<HazardType, Emergency>>(SAMPLE_EMERGENCY);
  const [here, setHere] = useState<LatLng>(BANGKOK);
  const [hereFallback, setHereFallback] = useState(true);
  const [area, setArea] = useState<Area | null>(null);
  const [nearby, setNearby] = useState<NearbyPlace[] | null>(null);
  const [nearbyError, setNearbyError] = useState<string | null>(null);

  const loadAround = useCallback((p: LatLng, real = false) => {
    setHere(p);
    setHereFallback(!real);
    api<Area>(`/weather/area?lat=${p.lat}&lng=${p.lng}`).then(setArea).catch(() => {});
  }, []);

  // ขอตำแหน่งจริงใหม่ (ปุ่ม "ตำแหน่งฉัน") ไม่ได้ = null ให้หน้าเว็บบอกผู้ใช้
  const locate = useCallback(
    () =>
      new Promise<LatLng | null>((resolve) => {
        if (!navigator.geolocation) return resolve(null);
        navigator.geolocation.getCurrentPosition(
          (pos) => {
            const p = { lat: pos.coords.latitude, lng: pos.coords.longitude };
            loadAround(p, true);
            resolve(p);
          },
          () => resolve(null),
          GEO_OPTIONS,
        );
      }),
    [loadAround],
  );

  const reloadTrips = useCallback(async () => {
    try {
      const list = await api<ApiTrip[]>("/trips");
      const names = titles();
      setTrips(list.map((t) => toTrip(t, names)));
      setTripsError(null);
    } catch (e) {
      setTripsError((e as Error).message);
    }
  }, []);

  // login แล้วค่อยโหลด หน้า login ไม่ต้องโหลดอะไร
  const token = typeof window === "undefined" ? null : getToken();
  useEffect(() => {
    if (!token) {
      setReady(true);
      return;
    }
    api<{ email: string; display_name: string | null }>("/me")
      .then((u) => {
        setEmail(u.email);
        setDisplayNameState(u.display_name);
      })
      .catch(() => {});
    reloadTrips().finally(() => setReady(true));
    api<{ hazards: Hazard[]; flood_window?: string | null }>(`/hazards?${THAILAND}`)
      .then((d) => {
        setHazards([...d.hazards].sort((a, b) => SEV[a.severity] - SEV[b.severity]));
        setFloodWindow(d.flood_window ?? null);
      })
      .catch((e) => setHazardsError(e.message));
    (Object.keys(HAZARD_META) as HazardType[]).forEach((t) =>
      api<Emergency>(`/safety/emergency?hazard_type=${t}`)
        .then((g) => setEmergency((m) => ({ ...m, [t]: g })))
        .catch(() => {}),
    );
    // ขอตำแหน่งจริง ระหว่างรอใช้กรุงเทพไปก่อนหลัง 4 วิ (หน้าเว็บจะได้ไม่ว่าง) ได้ตำแหน่งจริงเมื่อไหร่ก็ใช้ตำแหน่งจริงแทน
    const fallback = setTimeout(() => loadAround(BANGKOK), 4000);
    locate().then((p) => {
      clearTimeout(fallback);
      if (!p) loadAround(BANGKOK);
    });
    return () => clearTimeout(fallback);
  }, [token, reloadTrips, loadAround, locate]);

  // โปรไฟล์: ชื่อที่ให้น้องกิเลนเรียก และเปลี่ยนรหัสผ่าน (PATCH /me, POST /me/password)
  const setDisplayName = useCallback(async (name: string) => {
    const u = await api<{ display_name: string | null }>("/me", { method: "PATCH", body: { display_name: name } });
    setDisplayNameState(u.display_name);
  }, []);
  const changePassword = useCallback(async (current: string, next: string) => {
    await api("/me/password", { method: "POST", body: { current_password: current, new_password: next } });
  }, []);

  const planTrip = useCallback(
    async (id: string) => {
      await api(`/trips/${id}/plan`, { method: "POST" });
      await reloadTrips();
    },
    [reloadTrips],
  );

  const planOrReason = (id: string) =>
    api(`/trips/${id}/plan`, { method: "POST" }).then(
      () => null,
      (e: Error) => `บันทึกทริปแล้ว แต่วางแผนไม่สำเร็จ: ${e.message}`,
    );

  const createTrip = useCallback(
    async (t: NewTrip) => {
      const made = await api<ApiTrip>("/trips", {
        method: "POST",
        body: { origin: t.origin, destination: t.destination, departure_time: t.departure, waypoints: t.stops },
      });
      if (t.title) saveTitle(made.trip_id, t.title);
      // ทริปบันทึกแล้วแม้วางแผนไม่สำเร็จ ส่งเหตุผลกลับไปให้หน้าทริปบอกผู้ใช้ (เช่น ระบบหาเส้นทางช้า)
      const planError = await planOrReason(made.trip_id);
      await reloadTrips();
      return { trip: toTrip(made, titles()), planError };
    },
    [reloadTrips],
  );

  // แก้ทุกอย่างของทริปแล้ววางแผนใหม่ทันที (PATCH ทำให้แผนเดิมเป็น STALE อยู่แล้ว)
  const updateTrip = useCallback(
    async (id: string, t: NewTrip) => {
      await api(`/trips/${id}`, {
        method: "PATCH",
        body: { origin: t.origin, destination: t.destination, departure_time: t.departure, waypoints: t.stops },
      });
      saveTitle(id, t.title);
      const planError = await planOrReason(id);
      await reloadTrips();
      return planError;
    },
    [reloadTrips],
  );

  const deleteTrip = useCallback(
    async (id: string) => {
      await api(`/trips/${id}`, { method: "DELETE" });
      await reloadTrips();
    },
    [reloadTrips],
  );

  const shiftTrip = useCallback(
    async (id: string, hours: number) => {
      const t = trips.find((x) => x.trip_id === id);
      if (!t) return;
      const at = new Date(new Date(t.departure_time).getTime() + hours * 3600_000).toISOString().replace(/\.\d{3}Z$/, "Z");
      await api(`/trips/${id}`, { method: "PATCH", body: { departure_time: at } });
      await planTrip(id);
    },
    [trips, planTrip],
  );

  const nextTrip = useMemo(
    () => trips.find((t) => new Date(t.departure_time).getTime() > Date.now() - 12 * 3600_000) ?? null,
    [trips],
  );

  // การแจ้งเตือนสร้างจากข้อมูลจริง: ทริปเสี่ยง, แผนเก่า, น้ำท่วมจากดาวเทียม
  const alerts = useMemo(() => {
    const out: Alert[] = [];
    for (const t of trips) {
      const no = `Trip ${String(t.trip_no).padStart(2, "0")}`;
      if (t.plan_status === "STALE") out.push({ icon: "alert", tone: "aqua", text: `${no} แผนเก่าแล้ว กดวางแผนใหม่เพื่อดูความเสี่ยงล่าสุด`, href: `/trips?id=${t.trip_id}` });
      else if (t.plan && (t.plan.risk_level === "HIGH" || t.plan.risk_level === "MEDIUM"))
        out.push({ icon: t.plan.risk_level === "HIGH" ? "alert" : "rain", tone: t.plan.risk_level === "HIGH" ? "red" : "sun", text: `${no}: ${t.plan.summary_th}`, href: `/trips?id=${t.trip_id}` });
    }
    const flood = hazards.filter((h) => h.source === "GISTDA" && h.severity === "HIGH").length;
    if (flood) out.push({ icon: "flood", tone: "red", text: `ดาวเทียม GISTDA พบน้ำท่วมระดับรุนแรง ${flood} ตำบล`, href: "/map" });
    return out;
  }, [trips, hazards]);

  const value: Store = {
    ready,
    email,
    displayName,
    setDisplayName,
    changePassword,
    trips,
    tripsError,
    nextTrip,
    hazards,
    hazardsError,
    floodWindow,
    emergency,
    here,
    hereFallback,
    locate,
    area,
    nearby,
    nearbyError,
    alerts,
    reloadTrips,
    createTrip,
    planTrip,
    deleteTrip,
    updateTrip,
    shiftTrip,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

// ---------- ออกเวลาไหนดี ----------
// ถ้าเลื่อนเวลาออก +3/+6 ชม. ความเสี่ยงเป็นเท่าไร (GET /trips/{id}/departures)
export type Departure = { offset_h: number; risk_level: Risk; risk_score: number | null; recommendation: Plan["recommendation"] };
const depCache: Record<string, Promise<Departure[]>> = {};

export function loadDepartures(t: LiveTrip): Promise<Departure[]> {
  if (!t.plan) return Promise.resolve([]);
  const key = `${t.trip_id}|${t.departure_time}|${t.plan.arrival_time}`;
  const now: Departure = { offset_h: 0, risk_level: t.plan.risk_level, risk_score: t.plan.risk_score, recommendation: t.plan.recommendation };
  depCache[key] ??= api<{ departures: Departure[] }>(`/trips/${t.trip_id}/departures`, { timeoutMs: 100000 })
    .then((d) => [now, ...d.departures])
    .catch(() => {
      delete depCache[key]; // ไม่จำครั้งที่พัง เปิดทริปนี้อีกครั้งจะลองใหม่
      return [now];
    });
  return depCache[key];
}
