// สไตล์แผนที่ทั้งเว็บ: ใช้แผนที่ Esri (ชื่อภาษาอังกฤษทั้งแผนที่ ไม่ต้องมี key) แล้วแต่งสีด้วย CSS filter (globals.css .base-tiles)
// จำที่ผู้ใช้เลือกไว้ในเครื่อง
export type MapStyle = "soft" | "original" | "dark";
const KEY = "rmr_redesign_map_style";
export const MAP_STYLES: { id: MapStyle; label: string }[] = [
  { id: "soft", label: "นุ่มตา" },
  { id: "original", label: "สีปกติ" },
  { id: "dark", label: "กลางคืน" },
];

export function getMapStyle(): MapStyle {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "soft" || v === "original" || v === "dark") return v;
  } catch {}
  return "soft";
}

export function applyMapStyle(s: MapStyle = getMapStyle()) {
  document.documentElement.dataset.map = s;
  try {
    localStorage.setItem(KEY, s);
  } catch {}
}
