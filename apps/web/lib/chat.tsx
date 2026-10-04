"use client";

// บทสนทนากับน้องกิเลนของทั้งเว็บ ใช้ร่วมกันระหว่างแชทลอย (ChatDrawer) กับหน้า /assistant
// เก็บประวัติไว้ในเครื่อง (localStorage) แยกตามบัญชี ปิดเบราว์เซอร์แล้วยังอยู่
// API ยังไม่มีที่เก็บประวัติแชท ถ้าทำจริงควรย้ายไปเก็บใน api-backend จะได้เห็นทุกเครื่อง
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { useApp } from "./store";

export type ChatAction = { type: string; trip_no?: number; trip_id?: string };
export type Msg = { role: "me" | "bot"; text: string; at: string; actions?: ChatAction[]; error?: boolean };
export type Conversation = { id: string; title: string; at: string; msgs: Msg[] };
type ChatReply = { reply: string; actions?: ChatAction[]; warnings?: string[] };

export const ACTION_TH: Record<string, string> = { TRIP_CREATED: "สร้าง", TRIP_UPDATED: "แก้", TRIP_DELETED: "ลบ" };
// แนบสิ่งที่ระบบทำจริงไปกับข้อความใน history น้องกิเลนจะได้รู้ว่าคำตอบก่อนหน้าสร้าง/แก้ทริปสำเร็จจริงไหม
const actionNote = (m: Msg) =>
  m.actions?.length ? `\n(ระบบ: ${m.actions.map((a) => `${ACTION_TH[a.type]} Trip ${String(a.trip_no ?? "").padStart(2, "0")} สำเร็จ`).join(", ")})` : "";
const HISTORY_LIMIT = 10; // ข้อความก่อนหน้าที่ส่งให้ assistant-agent
const KEEP = 30; // เก็บประวัติบทสนทนาเก่าไว้สูงสุด
const TIMEOUT_MS = 60_000;
const newId = () => Math.random().toString(36).slice(2, 10);
const greeting = (): Msg => ({ role: "bot", text: "สวัสดีครับ น้องกิเลนเอง วันนี้จะไปไหนดี ให้ช่วยเช็กอะไรบอกได้เลย", at: new Date().toISOString() });
const fresh = (): Conversation => ({ id: newId(), title: "บทสนทนาใหม่", at: new Date().toISOString(), msgs: [greeting()] });
const hasTalk = (c: Conversation) => c.msgs.some((m) => m.role === "me");
const titleOf = (c: Conversation) => {
  const first = c.msgs.find((m) => m.role === "me")?.text ?? "บทสนทนาใหม่";
  return first.length > 40 ? `${first.slice(0, 40)}...` : first;
};

type Store = { current: Conversation; archive: Conversation[] };
type Chat = {
  msgs: Msg[];
  busy: boolean;
  currentId: string;
  history: Conversation[]; // บทสนทนาทั้งหมดที่มีข้อความ (ปัจจุบันอยู่บนสุด) ใหม่ไปเก่า
  send: (text: string) => Promise<void>;
  cancel: () => void;
  reset: () => void;
  open: (id: string) => void;
  remove: (id: string) => void;
};
const Ctx = createContext<Chat | null>(null);

export function useChat() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useChat นอก ChatProvider");
  return c;
}

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const { reloadTrips, email, here, hereFallback } = useApp();
  // ตำแหน่งจริงจาก GPS ให้ใช้เป็นต้นทางได้ ยังไม่ได้ตำแหน่งจริง (ใช้กรุงเทพแทนอยู่) ไม่ส่ง
  const location = useRef<{ lat: number; lng: number } | null>(null);
  location.current = hereFallback ? null : here;
  const [store, setStore] = useState<Store>({ current: fresh(), archive: [] });
  const [busy, setBusy] = useState(false);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const latest = useRef(store);
  latest.current = store;
  const abort = useRef<AbortController | null>(null);
  const key = email ? `rmr_redesign_chat_${email}` : null;

  // โหลดประวัติของบัญชีนี้ (รอรู้อีเมลก่อน ไม่ปนกันระหว่างบัญชี)
  useEffect(() => {
    if (!key) return;
    try {
      const saved = localStorage.getItem(key);
      // มาสคอตเปลี่ยนชื่อเป็นน้องกิเลน ข้อความทักทายในประวัติเก่ายังเป็นชื่อเดิม
      setStore(saved ? JSON.parse(saved.replaceAll("น้องแต้ม", "น้องกิเลน")) : { current: fresh(), archive: [] });
    } catch {
      setStore({ current: fresh(), archive: [] });
    }
    setLoadedFor(key);
  }, [key]);
  useEffect(() => {
    if (!key || loadedFor !== key) return;
    try {
      localStorage.setItem(key, JSON.stringify(store));
    } catch {}
  }, [store, key, loadedFor]);

  const update = (fn: (c: Conversation) => Conversation) =>
    setStore((s) => {
      const c = fn(s.current);
      return { ...s, current: { ...c, title: titleOf(c), at: new Date().toISOString() } };
    });

  const send = useCallback(
    async (text: string) => {
      const t = text.trim();
      if (!t || busy) return;
      // history ตาม CONTRACT: ข้อความก่อนหน้า ไม่รวมข้อความทักทายแรกและข้อความที่ส่งไม่สำเร็จ
      const history = latest.current.current.msgs
        .slice(1)
        .filter((m) => !m.error)
        .slice(-HISTORY_LIMIT)
        .map((m) => ({ role: m.role === "me" ? "user" : "assistant", content: m.text + actionNote(m) }));
      const convId = latest.current.current.id;
      update((c) => ({ ...c, msgs: [...c.msgs, { role: "me", text: t, at: new Date().toISOString() }] }));
      setBusy(true);
      const ctrl = new AbortController();
      abort.current = ctrl;
      // คำตอบกลับมาตอนผู้ใช้เปลี่ยนไปบทสนทนาอื่นแล้ว ให้ใส่กลับบทสนทนาเดิม
      const reply = (m: Msg) =>
        setStore((s) => {
          if (s.current.id === convId) return { ...s, current: { ...s.current, msgs: [...s.current.msgs, m], at: m.at } };
          return { ...s, archive: s.archive.map((c) => (c.id === convId ? { ...c, msgs: [...c.msgs, m] } : c)) };
        });
      try {
        const r = await api<ChatReply>("/assistant/chat", { method: "POST", body: { message: t, history, location: location.current }, timeoutMs: TIMEOUT_MS, signal: ctrl.signal });
        const actions = (r.actions ?? []).filter((a) => a.type in ACTION_TH);
        reply({ role: "bot", text: r.reply, at: new Date().toISOString(), actions });
        if (actions.length) reloadTrips();
      } catch (e) {
        const msg = (e as Error).message;
        reply({ role: "bot", text: ctrl.signal.aborted ? "ยกเลิกคำถามนี้แล้ว ถามใหม่ได้เลย" : `ขอโทษครับ ตอนนี้ตอบไม่ได้ (${msg}) ลองส่งใหม่อีกครั้งนะ`, at: new Date().toISOString(), error: true });
      } finally {
        abort.current = null;
        setBusy(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [busy, reloadTrips],
  );

  const cancel = useCallback(() => abort.current?.abort(), []);

  // เริ่มคุยใหม่: เก็บบทสนทนาเดิม (ถ้ามีข้อความ) เข้าประวัติ
  const reset = useCallback(() => {
    setStore((s) => (hasTalk(s.current) ? { current: fresh(), archive: [s.current, ...s.archive].slice(0, KEEP) } : s));
  }, []);

  const open = useCallback((id: string) => {
    setStore((s) => {
      const target = s.archive.find((c) => c.id === id);
      if (!target) return s;
      const rest = s.archive.filter((c) => c.id !== id);
      return { current: target, archive: (hasTalk(s.current) ? [s.current, ...rest] : rest).slice(0, KEEP) };
    });
  }, []);

  const remove = useCallback((id: string) => {
    setStore((s) => (s.current.id === id ? { ...s, current: fresh() } : { ...s, archive: s.archive.filter((c) => c.id !== id) }));
  }, []);

  const history = [...(hasTalk(store.current) ? [store.current] : []), ...store.archive].sort((a, b) => b.at.localeCompare(a.at));

  return (
    <Ctx.Provider value={{ msgs: store.current.msgs, busy, currentId: store.current.id, history, send, cancel, reset, open, remove }}>{children}</Ctx.Provider>
  );
}

// คำถามแนะนำตามทริปจริงของผู้ใช้
export function chatSuggestions(tripNo: string | null) {
  const no = tripNo ?? "ทริปถัดไป";
  return [
    { icon: "clock", title: "อากาศตามเส้นทาง", q: `${no} อากาศเป็นยังไง` },
    { icon: "edit", title: "เลื่อนเวลาออก", q: `เลื่อน ${no} ออกไป 3 ชั่วโมง` },
    { icon: "flood", title: "รับมือน้ำท่วม", q: "น้ำท่วมระหว่างทางต้องทำยังไง" },
    { icon: "alert", title: "ภัยช่วงนี้", q: "ช่วงนี้ที่ไหนน้ำท่วมบ้าง" },
  ];
}

const TZ = { timeZone: "Asia/Bangkok" } as const;
export const chatTime = (iso: string) => new Date(iso).toLocaleTimeString("th-TH", { ...TZ, hour: "2-digit", minute: "2-digit" }) + " น.";

// "วันนี้ 14:20" / "เมื่อวาน" / "24 ก.ย."
export function chatWhen(iso: string) {
  const d = new Date(iso);
  const day = (x: Date) => x.toLocaleDateString("en-CA", TZ);
  const today = new Date();
  const yest = new Date(Date.now() - 86_400_000);
  if (day(d) === day(today)) return `วันนี้ ${chatTime(iso)}`;
  if (day(d) === day(yest)) return "เมื่อวาน";
  return d.toLocaleDateString("th-TH", { ...TZ, day: "numeric", month: "short" });
}
