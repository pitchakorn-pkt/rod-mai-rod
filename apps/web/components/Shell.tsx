"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import Icon from "./Icon";
import ChatDrawer from "./ChatDrawer";
import ChatFab from "./ChatFab";
import { getToken, setToken } from "@/lib/api";
import { useApp } from "@/lib/store";
import { applyMapStyle } from "@/lib/mapStyle";
import { THEMES, applyTheme, getTheme, type Theme } from "@/lib/theme";
import { TEXT_SIZES, applyTextScale, getTextScale, resetSplits } from "@/lib/layout";
import { useChat } from "@/lib/chat";

const PUBLIC_PATHS = ["/login", "/privacy", "/terms"];

const NAV = [
  { href: "/", label: "หน้าหลัก", icon: "home" },
  { href: "/trips", label: "ทริปของฉัน", short: "ทริป", icon: "route" },
  { href: "/map", label: "แผนที่ความเสี่ยง", short: "แผนที่", icon: "map" },
  { href: "/emergency", label: "ฉุกเฉิน", icon: "sos" },
  { href: "/assistant", label: "คุยกับน้องกิเลน", short: "น้องกิเลน", icon: "chat" },
];

// เปิดแชทน้องกิเลนจากที่ไหนก็ได้ openChat("ข้อความ") จะส่งข้อความนั้นให้ทันที
// อยู่หน้า /assistant แล้ว = ส่งในหน้านั้นเลย ไม่เปิดแชทลอยซ้อน
export function openChat(text?: string) {
  window.dispatchEvent(new CustomEvent("open-chat", { detail: text }));
}

const SIDEBAR_KEY = "rmr_redesign_sidebar";

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  // พื้นหลังแยกตามหน้า: CSS เลือกรูปจาก html[data-page] (globals.css)
  useEffect(() => {
    document.documentElement.dataset.page = path.split("/")[1] || "home";
  }, [path]);
  const router = useRouter();
  const { ready, trips } = useApp();
  const [chatOpen, setChatOpen] = useState(false);
  // พับแถบเมนูซ้ายเหลือแต่ไอคอน จำไว้ในเครื่อง (CSS อ่านจาก html[data-sidebar])
  const [mini, setMini] = useState(false);
  useEffect(() => {
    try {
      setMini(localStorage.getItem(SIDEBAR_KEY) === "mini");
    } catch {}
  }, []);
  useEffect(() => {
    document.documentElement.dataset.sidebar = mini ? "mini" : "full";
  }, [mini]);
  function toggleSidebar() {
    setMini(!mini);
    try {
      localStorage.setItem(SIDEBAR_KEY, mini ? "full" : "mini");
    } catch {}
  }
  const { send } = useChat();
  const onAssistant = path.startsWith("/assistant");

  useEffect(() => {
    applyMapStyle();
    applyTheme();
    applyTextScale();
  }, []);
  useEffect(() => {
    const on = (e: Event) => {
      const seed = (e as CustomEvent<string | undefined>).detail;
      if (!location.pathname.startsWith("/assistant")) setChatOpen(true);
      if (seed) send(seed);
    };
    window.addEventListener("open-chat", on);
    return () => window.removeEventListener("open-chat", on);
  }, [send]);
  // ไปหน้าเต็มแล้ว ปิดแชทลอย
  useEffect(() => {
    if (onAssistant) setChatOpen(false);
  }, [onAssistant]);

  // ยังไม่ login พาไปหน้า login (หน้านโยบาย/เงื่อนไขเปิดได้โดยไม่ login เพราะ Google ลิงก์มาที่หน้าเหล่านี้)
  const isPublic = PUBLIC_PATHS.some((p) => path.startsWith(p));
  const [authed, setAuthed] = useState(false);
  useEffect(() => {
    setAuthed(!!getToken());
    if (!isPublic && !getToken()) router.replace("/login");
  }, [path, router, isPublic]);

  if (isPublic) return <>{children}</>;
  if (!authed || !ready)
    return (
      <div style={{ display: "grid", placeItems: "center", minHeight: "100vh" }}>
        <div className="stack" style={{ justifyItems: "center" }}>
          <img className="qilin-welcome-anim" src="/assets/shared/qilin-avatar.webp" alt="" style={{ width: 88, borderRadius: 24, boxShadow: "var(--shadow-lg)" }} />
          <p className="muted" style={{ fontWeight: 600 }}>น้องกิเลนกำลังโหลดข้อมูล...</p>
        </div>
      </div>
    );
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));

  return (
    <div className="app">
      <aside className="sidebar">
        <Link href="/" className="logo">
          <img src="/assets/shared/qilin-avatar.webp" alt="รอดไม่รอด" />
          <span className="nav-text">
            <b>รอดไม่รอด</b>
            <small>วางแผนเดินทางปลอดภัย</small>
          </span>
        </Link>
        <button
          className="sidebar-toggle"
          onClick={toggleSidebar}
          aria-label={mini ? "ขยายเมนู" : "พับเมนู"}
          aria-expanded={!mini}
          title={mini ? "ขยายเมนู" : "พับเมนู"}
        >
          <Icon name={mini ? "chevron" : "back"} size={16} />
        </button>
        {NAV.map((n) => (
          <Link key={n.href} href={n.href} className={`nav-link ${active(n.href) ? "active" : ""}`} title={mini ? n.label : undefined}>
            <Icon name={n.icon} />
            <span className="nav-text">{n.label}</span>
            {n.href === "/trips" && trips.length > 0 && <span className="badge" style={{ background: "var(--violet)" }}>{trips.length}</span>}
          </Link>
        ))}
        <div className="sidebar-mascot">
          <p>ออกเดินทางเมื่อไหร่ ให้น้องกิเลนช่วยเช็กก่อนนะ</p>
          <img className="qilin-mascot-anim" src="/assets/mascots/risk-qilin-navigation.webp" alt="น้องกิเลน" />
        </div>
      </aside>

      <main className="main">{children}</main>

      <nav className="bottom-nav" aria-label="เมนูหลัก">
        {NAV.map((n) => (
          <Link key={n.href} href={n.href} className={active(n.href) ? "active" : ""}>
            <Icon name={n.icon} size={22} />
            {"short" in n ? n.short : n.label}
          </Link>
        ))}
      </nav>

      {/* ปุ่มวงกลมน้องกิเลน ลอยทุกหน้า (ยกเว้นหน้าคุยเต็มหน้า) */}
      {!chatOpen && !onAssistant && (
        <ChatFab onOpen={() => setChatOpen(true)} />
      )}
      {chatOpen && <ChatDrawer onClose={() => setChatOpen(false)} />}
    </div>
  );
}

// ปุ่มเลือกธีม อยู่แถบบนทุกหน้า ใช้ได้ทั้งคอมและมือถือ
function ThemePicker() {
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>("dark");
  const [scale, setScale] = useState(1);
  const [resetDone, setResetDone] = useState(false);
  useEffect(() => {
    setTheme(getTheme());
    setScale(getTextScale());
  }, []);
  const current = THEMES.find((t) => t.id === theme)!;
  return (
    <div className="topbar-pop">
      <button className="icon-btn" onClick={() => setOpen(!open)} aria-label="ธีมและขนาดตัวอักษร" aria-expanded={open} title="ธีม ขนาดตัวอักษร และขนาดการ์ด">
        <span className="theme-dot" style={{ backgroundImage: current.swatch }} />
      </button>
      {open && (
        <div className="theme-menu card" role="menu">
          {THEMES.map((t) => (
            <button
              key={t.id}
              role="menuitemradio"
              aria-checked={t.id === theme}
              className={`theme-opt ${t.id === theme ? "on" : ""}`}
              onClick={() => {
                applyTheme(t.id);
                setTheme(t.id);
                setOpen(false);
              }}
            >
              <span className="theme-dot" style={{ backgroundImage: t.swatch }} />
              {t.label}
              {t.id === theme && <Icon name="check" size={15} />}
            </button>
          ))}
          <p className="tiny muted theme-sec">ขนาดตัวอักษร</p>
          <div className="text-sizes" role="radiogroup" aria-label="ขนาดตัวอักษร">
            {TEXT_SIZES.map((t) => (
              <button
                key={t.scale}
                role="radio"
                aria-checked={t.scale === scale}
                className={`text-size ${t.scale === scale ? "on" : ""}`}
                title={t.label}
                style={{ fontSize: 13 * t.scale }}
                onClick={() => {
                  applyTextScale(t.scale);
                  setScale(t.scale);
                }}
              >
                ก
              </button>
            ))}
          </div>
          <button
            className="theme-opt reset"
            title="การ์ดที่ลากขยายหรือย่อไว้ในทุกหน้าจะกลับเป็นขนาดเดิม"
            onClick={() => {
              resetSplits();
              setResetDone(true);
              setTimeout(() => setResetDone(false), 1500);
            }}
          >
            <Icon name={resetDone ? "check" : "layers"} size={15} />
            {resetDone ? "คืนขนาดแล้ว" : "คืนขนาดการ์ดเดิม"}
          </button>
        </div>
      )}
    </div>
  );
}

export function Topbar({ title, sub, right }: { title: string; sub?: string; right?: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const { alerts } = useApp();
  return (
    <header className="topbar">
      <div className="title">
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {right}
      <ThemePicker />
      <div className="topbar-pop">
        <button className="icon-btn" onClick={() => setOpen(!open)} aria-label="การแจ้งเตือน">
          <Icon name="bell" />
          {alerts.length > 0 && <span className="dot" />}
        </button>
        {open && (
          <div className="card notif-menu">
            <p className="bold" style={{ padding: "4px 6px 10px" }}>การแจ้งเตือน</p>
            <div className="stack" style={{ gap: 4 }}>
              {alerts.length === 0 && <p className="small muted" style={{ padding: "0 6px 6px" }}>ยังไม่มีเรื่องที่ต้องระวัง</p>}
              {alerts.map((a) => (
                <Link key={a.text} href={a.href} onClick={() => setOpen(false)} className="row nowrap" style={{ alignItems: "flex-start", padding: 8, borderRadius: 12 }}>
                  <span className={`card-icon ${a.tone}`} style={{ width: 34, height: 34 }}>
                    <Icon name={a.icon} size={17} />
                  </span>
                  <div className="grow">
                    <p className="small">{a.text}</p>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}
      </div>
      <ProfileMenu />
    </header>
  );
}

// รูปขวาบน: ตั้งชื่อให้น้องกิเลนเรียก เปลี่ยนรหัสผ่าน ออกจากระบบ
function ProfileMenu() {
  const { email, displayName, setDisplayName, changePassword } = useApp();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [nameMsg, setNameMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pw, setPw] = useState({ current: "", next: "", again: "" });
  const [pwOpen, setPwOpen] = useState(false);
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  // เปิดเมนูใหม่ทุกครั้ง เริ่มจากชื่อปัจจุบัน ไม่ค้างข้อความเก่า (ไม่ผูกกับ displayName ไม่งั้นบันทึกแล้วข้อความหาย)
  useEffect(() => {
    if (!open) return;
    setName(displayName ?? "");
    setNameMsg(null);
    setPwMsg(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  async function saveName(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await setDisplayName(name);
      setNameMsg({ ok: true, text: name.trim() ? "บันทึกแล้ว น้องกิเลนจะเรียกชื่อนี้" : "ลบชื่อแล้ว" });
    } catch (err) {
      setNameMsg({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }
  async function savePassword(e: React.FormEvent) {
    e.preventDefault();
    if (pw.next !== pw.again) return setPwMsg({ ok: false, text: "รหัสผ่านใหม่สองช่องไม่ตรงกัน" });
    setBusy(true);
    try {
      await changePassword(pw.current, pw.next);
      setPw({ current: "", next: "", again: "" });
      setPwMsg({ ok: true, text: "เปลี่ยนรหัสผ่านแล้ว" });
    } catch (err) {
      setPwMsg({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="topbar-pop" ref={box}>
      <button className="avatar-btn" onClick={() => setOpen(!open)} aria-label="บัญชีของฉัน" aria-expanded={open} title="บัญชีของฉัน">
        <img className="avatar" src="/assets/shared/qilin-avatar.webp" alt="" />
      </button>
      {open && (
        <div className="card profile-menu" role="dialog" aria-label="บัญชีของฉัน">
          <div className="row nowrap" style={{ gap: 10, marginBottom: 12 }}>
            <img className="avatar" src="/assets/shared/qilin-avatar.webp" alt="" />
            <div style={{ minWidth: 0 }}>
              <p className="bold ellipsis">{displayName || email?.split("@")[0]}</p>
              <p className="tiny muted ellipsis">{email}</p>
            </div>
          </div>
          <form className="stack" style={{ gap: 6 }} onSubmit={saveName}>
            <label className="label" htmlFor="profile-name">
              ชื่อที่ให้น้องกิเลนเรียก
            </label>
            <div className="row nowrap" style={{ gap: 6 }}>
              <input id="profile-name" className="input" value={name} maxLength={40} placeholder="เช่น แพนด้า" onChange={(e) => setName(e.target.value)} />
              <button className="btn sm" disabled={busy || name.trim() === (displayName ?? "")}>
                บันทึก
              </button>
            </div>
            {nameMsg && <p className={`tiny ${nameMsg.ok ? "ok-text" : "error-text"}`}>{nameMsg.text}</p>}
          </form>
          <button className="theme-opt" style={{ marginTop: 10 }} onClick={() => setPwOpen(!pwOpen)} aria-expanded={pwOpen}>
            <Icon name="lock" size={16} />
            เปลี่ยนรหัสผ่าน
          </button>
          {pwOpen && (
            <form className="stack" style={{ gap: 6, marginTop: 6 }} onSubmit={savePassword}>
              <input className="input" type="password" autoComplete="current-password" placeholder="รหัสผ่านเดิม" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} required />
              <input className="input" type="password" autoComplete="new-password" placeholder="รหัสผ่านใหม่ (อย่างน้อย 6 ตัว)" minLength={6} value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} required />
              <input className="input" type="password" autoComplete="new-password" placeholder="พิมพ์รหัสผ่านใหม่อีกครั้ง" minLength={6} value={pw.again} onChange={(e) => setPw({ ...pw, again: e.target.value })} required />
              <button className="btn sm" disabled={busy}>
                {busy ? "กำลังบันทึก..." : "เปลี่ยนรหัสผ่าน"}
              </button>
              {pwMsg && <p className={`tiny ${pwMsg.ok ? "ok-text" : "error-text"}`}>{pwMsg.text}</p>}
            </form>
          )}
          <button
            className="theme-opt"
            onClick={() => {
              setToken(null);
              location.href = "/login";
            }}
          >
            <Icon name="logout" size={16} />
            ออกจากระบบ
          </button>
        </div>
      )}
    </div>
  );
}
