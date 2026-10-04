"use client";

// แผนที่ตัวเดียวของทั้งเว็บ ใช้ผ่าน components/Map (ปิด SSR)
import "leaflet/dist/leaflet.css";
import { useEffect, useMemo, useState } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Circle, CircleMarker, MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap, useMapEvents } from "react-leaflet";
import { divIcon, latLngBounds, type DivIcon } from "leaflet";
import Icon from "./Icon";
import type { LatLng } from "@/lib/data";
import { useApp } from "@/lib/store";

// segments = ระบายสีแต่ละช่วงของเส้นทางตามระดับความเสี่ยง (lib/segments.ts) ไม่ใส่ = สีเดียวทั้งเส้น
export type MapRoute = { id: string; points: LatLng[]; color: string; active?: boolean; onClick?: () => void; segments?: { points: LatLng[]; color: string; tip?: string }[] };
export type MapPin = {
  id: string;
  lat: number;
  lng: number;
  color: string;
  icon?: string; // ไอคอนในวงกลม
  label?: string; // ป้ายข้อความ
  tip?: string; // ข้อความตอนชี้
  radiusKm?: number; // วงรัศมีผลกระทบ ใส่เฉพาะภัยวงกว้าง (ฝน ลม พายุ แผ่นดินไหว)
  strong?: boolean; // วงเข้มขึ้นสำหรับระดับสูง
  radiusColor?: string; // สีวง แยกจากสีหมุด (สีหมุด = ระดับความเสี่ยง, สีวง = ชนิดภัย) ไม่ใส่ = สีหมุด
  selected?: boolean;
  keep?: boolean; // ไม่รวมกลุ่มกับหมุดอื่น เช่น ต้นทาง จุดแวะ ปลายทาง
  onClick?: () => void;
};
export type MapDot = { id: string; lat: number; lng: number; color: string; tip?: string };

type Props = {
  center?: LatLng;
  zoom?: number;
  routes?: MapRoute[];
  pins?: MapPin[];
  dots?: MapDot[];
  fit?: LatLng[];
  onClick?: (p: LatLng) => void;
  flyTo?: (LatLng & { zoom?: number }) | null;
  flood?: boolean | string; // true = ชุดที่ระบบใช้อยู่ หรือส่งชื่อชุด เช่น "7days" (GISTDA ยังไม่มีข้อมูล = ไม่แสดง)
  me?: LatLng | null; // ตำแหน่งของผู้ใช้ (จุดฟ้ากะพริบ)
  circle?: { center: LatLng; radiusKm: number; color: string } | null; // วงรัศมี เช่น ที่เที่ยวใน 20 กม. // ชั้นพื้นที่น้ำท่วมจากดาวเทียม GISTDA 3 วันล่าสุด (ผ่าน api-backend key อยู่ฝั่ง server)
  areas?: { id: string; lat: number; lng: number; radiusKm: number; color: string; tip?: string }[]; // วงพื้นที่ เช่น ฝนตามเส้นทาง
};

// ไอคอนหน้าตาเดียวกันสร้างครั้งเดียว (หมุดน้ำท่วมหลายร้อยจุดใช้แบบซ้ำกันไม่กี่แบบ)
const iconCache = new Map<string, DivIcon>();
function pinIcon(p: MapPin) {
  const key = `${p.color}|${p.icon}|${p.label}|${!!p.selected}|${!!p.strong}`;
  let icon = iconCache.get(key);
  if (!icon) iconCache.set(key, (icon = buildPinIcon(p)));
  return icon;
}

// หมุดเยอะ: รวมหมุดที่อยู่ใกล้กันบนจอเป็นวงเดียวพร้อมจำนวน สีตามหมุดที่รุนแรงสุดในกลุ่ม
// วาดเฉพาะหมุดในกรอบที่มองเห็น ซูมเข้าถึง CLUSTER_UNTIL_ZOOM แล้วแยกเป็นหมุดเดี่ยวทั้งหมด
const CLUSTER_PX = 56;
const CLUSTER_UNTIL_ZOOM = 12;
const CLUSTER_MIN_PINS = 40;

function clusterIcon(count: number, color: string) {
  const key = `cluster|${count}|${color}`;
  let icon = iconCache.get(key);
  if (!icon) {
    const size = count < 10 ? 34 : count < 100 ? 40 : 48;
    icon = divIcon({ className: "", iconSize: [size, size], html: `<span class="pin-cluster" style="--c:${color};width:${size}px;height:${size}px">${count}</span>` });
    iconCache.set(key, icon);
  }
  return icon;
}

function PinLayer({ pins }: { pins: MapPin[] }) {
  const map = useMap();
  const [view, setView] = useState(() => ({ zoom: map.getZoom(), bounds: map.getBounds() }));
  useMapEvents({ moveend: () => setView({ zoom: map.getZoom(), bounds: map.getBounds() }) });

  const groups = useMemo(() => {
    const box = view.bounds.pad(0.25);
    const visible = pins.filter((p) => p.selected || box.contains([p.lat, p.lng]));
    if (view.zoom >= CLUSTER_UNTIL_ZOOM || visible.length <= CLUSTER_MIN_PINS) return visible.map((p) => [p]);
    const cells = new Map<string, MapPin[]>();
    const out: MapPin[][] = [];
    for (const p of visible) {
      if (p.selected || p.label || p.keep) {
        out.push([p]); // หมุดที่เลือกและหมุดมีป้ายชื่อไม่รวมกลุ่ม
        continue;
      }
      const pt = map.project([p.lat, p.lng], view.zoom);
      const key = `${Math.floor(pt.x / CLUSTER_PX)}:${Math.floor(pt.y / CLUSTER_PX)}`;
      const cell = cells.get(key);
      if (cell) cell.push(p);
      else cells.set(key, [p]);
    }
    return [...out, ...cells.values()];
  }, [pins, view, map]);

  return (
    <>
      {groups.map((g) => {
        if (g.length === 1) {
          const p = g[0];
          return (
            <Marker key={p.id} position={[p.lat, p.lng]} icon={pinIcon(p)} zIndexOffset={p.selected ? 1000 : 0} eventHandlers={{ click: () => p.onClick?.() }}>
              {p.tip && <Tooltip direction="top" offset={[0, -14]}>{p.tip}</Tooltip>}
            </Marker>
          );
        }
        const top = g.find((p) => p.strong) ?? g[0];
        const lat = g.reduce((s, p) => s + p.lat, 0) / g.length;
        const lng = g.reduce((s, p) => s + p.lng, 0) / g.length;
        return (
          <Marker
            key={`c-${g[0].id}-${g.length}`}
            position={[lat, lng]}
            icon={clusterIcon(g.length, top.color)}
            eventHandlers={{ click: () => map.flyToBounds(latLngBounds(g.map((p) => [p.lat, p.lng])), { padding: [60, 60], maxZoom: CLUSTER_UNTIL_ZOOM, duration: 0.5 }) }}
          >
            <Tooltip direction="top">{g.length} จุด · กดเพื่อซูมดู</Tooltip>
          </Marker>
        );
      })}
    </>
  );
}

function buildPinIcon(p: MapPin) {
  const isSelected = !!p.selected;
  const isStrong = !!p.strong;

  if (p.label) {
    const html = `
      <div class="pin-beacon-wrap${isSelected ? " selected" : ""}">
        <div class="pin-sonar-ground" style="--c:${p.color}"></div>
        <div class="pin-label-cool" style="--c:${p.color}">
          ${p.icon ? renderToStaticMarkup(<Icon name={p.icon} size={14} stroke={2.4} />) : ""}
          <span class="label-text">${p.label}</span>
        </div>
        <div class="pin-anchor-dot" style="--c:${p.color}"></div>
      </div>
    `;
    return divIcon({ className: "pin-div-icon", iconSize: [0, 0], iconAnchor: [0, 0], html });
  }

  const iconMarkup = renderToStaticMarkup(<Icon name={p.icon ?? "pin"} size={isSelected ? 16 : 13} stroke={2.4} />);
  const html = `
    <div class="pin-beacon-wrap${isSelected ? " selected" : ""}${isStrong ? " strong" : ""}">
      <div class="pin-sonar-ground" style="--c:${p.color}"></div>
      <div class="pin-cyber-badge" style="--c:${p.color}">
        <div class="pin-cyber-inner">
          ${iconMarkup}
        </div>
        <div class="pin-cyber-tip" style="--c:${p.color}"></div>
      </div>
      <div class="pin-anchor-dot" style="--c:${p.color}"></div>
    </div>
  `;
  return divIcon({ className: "pin-div-icon", iconSize: [0, 0], iconAnchor: [0, 0], html });
}

function Fit({ points }: { points?: LatLng[] }) {
  const map = useMap();
  const key = JSON.stringify(points?.length ? [points[0], points[points.length - 1], points.length] : []);
  useEffect(() => {
    if (!points || points.length < 2) return;
    // รอแผนที่พร้อมก่อน และไม่ใช้แอนิเมชัน ไม่งั้นตอนเปลี่ยนทริปซูมแล้วแต่ภาพแผนที่ไม่โหลดตามระดับซูมใหม่
    map.whenReady(() => {
      map.invalidateSize();
      map.fitBounds(points.map((p) => [p.lat, p.lng]), { padding: [36, 36], animate: false });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, map]);
  return null;
}

function Fly({ to }: { to?: (LatLng & { zoom?: number }) | null }) {
  const map = useMap();
  useEffect(() => {
    if (to) map.flyTo([to.lat, to.lng], to.zoom ?? Math.max(map.getZoom(), 8), { duration: 0.6 });
  }, [to, map]);
  return null;
}

// กล่องแผนที่เปลี่ยนขนาดหลังวาดแล้ว (เปลี่ยนทริป ป้ายเตือนโผล่/หาย) Leaflet ไม่รู้ตัว โหลดภาพแผนที่ไม่ครบ ให้วัดขนาดใหม่
function AutoResize() {
  const map = useMap();
  useEffect(() => {
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(map.getContainer());
    return () => ro.disconnect();
  }, [map]);
  return null;
}

function Clicks({ onClick }: { onClick?: (p: LatLng) => void }) {
  useMapEvents({ click: (e) => onClick?.({ lat: e.latlng.lat, lng: e.latlng.lng }) });
  return null;
}


export default function MapView({ center = { lat: 13.7563, lng: 100.5018 }, zoom = 6, routes = [], pins = [], dots = [], fit, onClick, flyTo, flood, me, circle, areas = [] }: Props) {
  const { floodWindow } = useApp();
  const floodLayer = typeof flood === "string" ? flood : flood ? floodWindow : null;
  const ordered = [...routes].sort((a, b) => Number(!!a.active) - Number(!!b.active));
  return (
    <MapContainer center={[center.lat, center.lng]} zoom={zoom} style={{ height: "100%", width: "100%" }} zoomControl={false} attributionControl>
      {/* Esri ชื่อทุกประเทศเป็นภาษาอังกฤษภาษาเดียว (OpenStreetMap ใช้ภาษาท้องถิ่น ไทย พม่า จีน ปนกัน) ไม่ต้องใช้ key */}
      <TileLayer url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}" attribution="Tiles &copy; Esri" maxNativeZoom={19} className="base-tiles" />
      {floodLayer && <TileLayer key={floodLayer} url={`/api/v1/maps/flood/${floodLayer}/{z}/{x}/{y}`} opacity={0.9} zIndex={2} attribution="น้ำท่วม &copy; GISTDA" />}
      {ordered.map((r) => (
        <Polyline
          key={`${r.id}-halo`}
          positions={r.points.map((p) => [p.lat, p.lng])}
          pathOptions={{ color: "#fff", weight: r.active ? 11 : 7, opacity: r.active ? 0.95 : 0.6 }}
        />
      ))}
      {ordered.map((r) =>
        r.active && r.segments?.length ? (
          r.segments.map((g, i) => (
            <Polyline
              key={`${r.id}-${i}-${g.color}`}
              positions={g.points.map((p) => [p.lat, p.lng])}
              pathOptions={{ color: g.color, weight: 6, opacity: 1, lineCap: "round" }}
              eventHandlers={{ click: () => r.onClick?.() }}
            >
              {g.tip && <Tooltip sticky>{g.tip}</Tooltip>}
            </Polyline>
          ))
        ) : (
          <Polyline
            key={r.id}
            positions={r.points.map((p) => [p.lat, p.lng])}
            pathOptions={{ color: r.color, weight: r.active ? 6 : 4, opacity: r.active ? 1 : 0.45, dashArray: r.active ? undefined : "8 8" }}
            eventHandlers={{ click: () => r.onClick?.() }}
          />
        ),
      )}
      {areas.map((a) => (
        <Circle key={a.id} center={[a.lat, a.lng]} radius={a.radiusKm * 1000} pathOptions={{ color: a.color, weight: 1.5, opacity: 0.9, fillColor: a.color, fillOpacity: 0.28 }}>
          {a.tip && <Tooltip sticky>{a.tip}</Tooltip>}
        </Circle>
      ))}
      {circle && (
        <Circle center={[circle.center.lat, circle.center.lng]} radius={circle.radiusKm * 1000} pathOptions={{ color: circle.color, weight: 2, dashArray: "6 6", fillColor: circle.color, fillOpacity: 0.06 }} />
      )}
      {me && <Marker position={[me.lat, me.lng]} icon={divIcon({ className: "", iconSize: undefined, html: '<span class="me-dot"></span>' })} zIndexOffset={1000} />}
      {dots.map((d) => (
        <CircleMarker key={d.id} center={[d.lat, d.lng]} radius={9} pathOptions={{ color: "#fff", weight: 2, fillColor: d.color, fillOpacity: 0.9 }}>
          {d.tip && <Tooltip>{d.tip}</Tooltip>}
        </CircleMarker>
      ))}
      {pins.filter((p) => p.radiusKm).map((p) => (
        <Circle key={`${p.id}-radius`} center={[p.lat, p.lng]} radius={p.radiusKm! * 1000} pathOptions={{ color: p.radiusColor ?? p.color, weight: 2, opacity: 0.85, dashArray: "5 6", fillColor: p.radiusColor ?? p.color, fillOpacity: p.strong ? 0.2 : 0.1 }} />
      ))}
      <PinLayer pins={pins} />
      <AutoResize />
      <Fit points={fit} />
      <Fly to={flyTo} />
      <Clicks onClick={onClick} />
    </MapContainer>
  );
}
