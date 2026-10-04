"use client";

import { useEffect, useRef, useState } from "react";
import Icon from "@/components/Icon";
import { api, setToken } from "@/lib/api";

const POINTS = [
  { icon: "clock", text: "อากาศ ณ เวลาที่ไปถึงแต่ละจุด" },
  { icon: "route", text: "เทียบเส้นทางและเวลาออกที่ปลอดภัย" },
  { icon: "chat", text: "คุยกับน้องกิเลนเพื่อแก้ทริป" },
];

// ภาพหน้าจอจริงของเว็บ (public/assets/showcase ถ่ายจากระบบจริง ซ่อนชื่อบัญชีแล้ว) หมุนโชว์ในหน้าต่างจำลอง
const SHOTS = [
  { key: "home", label: "หน้าหลัก", path: "/" },
  { key: "trips", label: "ทริปของฉัน", path: "/trips" },
  { key: "map", label: "แผนที่ความเสี่ยง", path: "/map" },
  { key: "chat", label: "คุยกับน้องกิเลน", path: "/assistant" },
  { key: "emergency", label: "ฉุกเฉิน", path: "/emergency" },
];
const SHOT_MS = 4500;

function Showcase({ idle = false }: { idle?: boolean }) {
  const [i, setI] = useState(0);
  const [hover, setPaused] = useState(false);
  const paused = hover || idle; // อยู่ใบหลังไม่ต้องหมุนภาพ
  useEffect(() => {
    if (paused || window.matchMedia("(prefers-reduced-motion: reduce)").matches)
      return;
    const t = setTimeout(() => setI((i + 1) % SHOTS.length), SHOT_MS);
    return () => clearTimeout(t);
  }, [i, paused]);
  return (
    <div
      className="sc"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      <div className="sc-stage">
        <div className="sc-glow" />
        <div className="sc-window">
          <div className="sc-bar">
            <i />
            <i />
            <i />
            <span className="sc-url">
              <Icon name="lock" size={11} /> rodmairod.app{SHOTS[i].path}
            </span>
          </div>
          <div className="sc-screen">
            {SHOTS.map((s, k) => (
              <img
                key={s.key}
                className={k === i ? "on" : ""}
                src={`/assets/showcase/${s.key}.webp`}
                alt={`ตัวอย่างหน้า${s.label}`}
                loading={k === 0 ? "eager" : "lazy"}
              />
            ))}
          </div>
        </div>
      </div>
      <div className="sc-tabs" role="tablist" aria-label="ตัวอย่างหน้าเว็บ">
        {SHOTS.map((s, k) => (
          <button
            key={s.key}
            role="tab"
            aria-selected={k === i}
            className={k === i ? "on" : ""}
            onClick={() => setI(k)}
          >
            {s.label}
            {k === i && !paused && (
              <span
                key={i}
                className="sc-progress"
                style={{ animationDuration: `${SHOT_MS}ms` }}
              />
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

// ความแข็งแรงรหัสผ่านแบบง่าย (ความยาว + ชนิดตัวอักษร) ใช้ตอนสมัคร
function strength(pw: string) {
  if (!pw) return 0;
  const kinds = [/[a-z฀-๿]/, /[A-Z]/, /\d/, /[^\w฀-๿]/].filter((r) =>
    r.test(pw),
  ).length;
  return Math.min(
    4,
    (pw.length >= 6 ? 1 : 0) +
      (pw.length >= 10 ? 1 : 0) +
      Math.max(0, kinds - 1),
  );
}
const STRENGTH = ["", "พอใช้", "ดี", "ดีมาก", "แข็งแรงมาก"];

// ปุ่ม Sign in with Google (สคริปต์ทางการของ Google) ได้ ID token แล้วส่งให้ api-backend ตรวจ
// api-backend ไม่ได้ตั้ง GOOGLE_CLIENT_ID = ไม่แสดงปุ่ม (login แบบอีเมลใช้ได้ตามเดิม)
type GoogleId = {
  initialize: (o: { client_id: string; callback: (r: { credential: string }) => void }) => void;
  renderButton: (el: HTMLElement, o: Record<string, unknown>) => void;
};
declare global {
  interface Window {
    google?: { accounts: { id: GoogleId } };
  }
}
const GSI_SRC = "https://accounts.google.com/gsi/client";

function GoogleButton({ busy, onCredential }: { busy: boolean; onCredential: (credential: string) => void }) {
  const [clientId, setClientId] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const done = useRef(onCredential);
  done.current = onCredential;
  useEffect(() => {
    api<{ google_client_id: string | null }>("/auth/config")
      .then((c) => setClientId(c.google_client_id))
      .catch(() => {});
  }, []);
  useEffect(() => {
    if (!clientId) return;
    const draw = () => {
      const g = window.google?.accounts.id;
      if (!g || !box.current) return;
      g.initialize({ client_id: clientId, callback: (r) => done.current(r.credential) });
      g.renderButton(box.current, {
        theme: document.documentElement.dataset.theme === "glass" ? "outline" : "filled_black",
        size: "large",
        shape: "pill",
        text: "continue_with",
        locale: "th",
        width: Math.min(400, box.current.offsetWidth),
      });
    };
    if (window.google?.accounts) return draw();
    let script = document.querySelector<HTMLScriptElement>(`script[src="${GSI_SRC}"]`);
    if (!script) {
      script = document.createElement("script");
      script.src = GSI_SRC;
      script.async = true;
      document.head.appendChild(script);
    }
    script.addEventListener("load", draw);
    return () => script?.removeEventListener("load", draw);
  }, [clientId]);
  if (!clientId) return null;
  return (
    <div className="lc-google">
      <div className="lc-or">
        <span>หรือ</span>
      </div>
      <div ref={box} className="lc-gbtn" aria-disabled={busy} />
      <p className="lc-legal">
        การใช้งานถือว่ายอมรับ <a href="/terms">เงื่อนไขการใช้งาน</a> และ <a href="/privacy">นโยบายความเป็นส่วนตัว</a>
      </p>
    </div>
  );
}

function LoginCard({
  mode,
  setMode,
  busy,
  error,
  onSubmit,
  onGoogle,
}: {
  mode: "login" | "register";
  setMode: (m: "login" | "register") => void;
  busy: boolean;
  error: string | null;
  onSubmit: (email: string, password: string) => void;
  onGoogle: (credential: string) => void;
}) {
  const [showPw, setShowPw] = useState(false);
  const [pw, setPw] = useState("");
  const level = strength(pw);
  const login = mode === "login";
  return (
    <div className="lc">
      <div className="lc-in">
        <div className="lc-head">
          <span className="lc-avatar">
            <img src="/assets/shared/qilin-avatar.webp" alt="น้องกิเลน" />
          </span>
          <p className="lc-kicker">
            {login ? "ยินดีต้อนรับกลับ" : "เริ่มต้นใช้งานฟรี"}
          </p>
          <h2 className="font-serif">
            {login ? "เข้าสู่ระบบ" : "สร้างบัญชีใหม่"}
          </h2>
          <p className="lc-sub">
            {login
              ? "ดูทริปและแผนเดินทางที่คุณบันทึกไว้"
              : "ใช้อีเมลเดียวก็เริ่มวางแผนทริปแรกได้เลย"}
          </p>
        </div>

        <div className={`lc-tabs ${login ? "" : "right"}`} role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={login}
            onClick={() => setMode("login")}
          >
            เข้าสู่ระบบ
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={!login}
            onClick={() => setMode("register")}
          >
            สมัครสมาชิก
          </button>
        </div>

        <form
          className="lc-form"
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            onSubmit(String(f.get("email")), String(f.get("password")));
          }}
        >
          <div className="lc-field">
            <span className="lc-ico">
              <Icon name="mail" size={17} />
            </span>
            <input
              id="em"
              name="email"
              type="email"
              autoComplete="email"
              placeholder=" "
              required
            />
            <label htmlFor="em">อีเมล</label>
          </div>
          <div className="lc-field">
            <span className="lc-ico">
              <Icon name="lock" size={17} />
            </span>
            <input
              id="pw"
              name="password"
              type={showPw ? "text" : "password"}
              autoComplete={login ? "current-password" : "new-password"}
              placeholder=" "
              minLength={6}
              required
              value={pw}
              onChange={(e) => setPw(e.target.value)}
            />
            <label htmlFor="pw">รหัสผ่าน (อย่างน้อย 6 ตัว)</label>
            <button
              type="button"
              className="lc-eye"
              onClick={() => setShowPw(!showPw)}
              aria-label={showPw ? "ซ่อนรหัสผ่าน" : "แสดงรหัสผ่าน"}
              title={showPw ? "ซ่อนรหัสผ่าน" : "แสดงรหัสผ่าน"}
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden
              >
                <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" />
                <circle cx="12" cy="12" r="3" />
                {showPw && <path d="M4 4l16 16" />}
              </svg>
            </button>
          </div>
          {!login && (
            <div className="lc-meter" aria-live="polite">
              {[1, 2, 3, 4].map((n) => (
                <i key={n} className={n <= level ? `on l${level}` : ""} />
              ))}
              <span>
                {pw
                  ? `ความแข็งแรง: ${STRENGTH[level] || "สั้นไป"}`
                  : "ใช้ตัวอักษรผสมตัวเลขจะปลอดภัยกว่า"}
              </span>
            </div>
          )}
          {error && (
            <div className="lc-error" role="alert">
              <Icon name="alert" size={16} />
              {error}
            </div>
          )}
          <button className="btn block lc-submit" disabled={busy}>
            <span>
              {busy
                ? login
                  ? "กำลังเข้าสู่ระบบ..."
                  : "กำลังสมัคร..."
                : login
                  ? "เข้าสู่ระบบ"
                  : "สมัครและเข้าสู่ระบบ"}
            </span>
            {!busy && <Icon name="chevron" size={18} />}
          </button>
        </form>
        <GoogleButton busy={busy} onCredential={onGoogle} />

        <div className="lc-foot">
          <span>
            <Icon name="lock" size={13} /> รหัสผ่านเข้ารหัส
          </span>
          <span>
            <Icon name="star" size={13} /> ใช้ฟรี
          </span>
          <span>
            <Icon name="cloud" size={13} /> อากาศจริงรายชั่วโมง
          </span>
        </div>
      </div>
    </div>
  );
}

export default function Login() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [front, setFront] = useState<"show" | "login">("login");

  async function submit(email: string, password: string) {
    setBusy(true);
    setError(null);
    try {
      if (mode === "register")
        await api("/auth/register", {
          method: "POST",
          body: { email, password },
        });
      const { token } = await api<{ token: string }>("/auth/login", {
        method: "POST",
        body: { email, password },
      });
      setToken(token);
      location.href = "/";
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  async function google(credential: string) {
    setBusy(true);
    setError(null);
    try {
      const { token } = await api<{ token: string }>("/auth/google", { method: "POST", body: { credential } });
      setToken(token);
      location.href = "/";
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="lp">
      <header className="lp-top">
        <div className="logo" style={{ padding: 0 }}>
          <img src="/assets/shared/qilin-avatar.webp" alt="" />
          <span>
            <b>รอดไม่รอด</b>
            <small>ระบบวางแผนเดินทางปลอดภัย</small>
          </span>
        </div>
        <div className="lp-sources">
          <span>
            <i className="ap-dot" /> น้ำท่วมจากดาวเทียม GISTDA
          </span>
          <span>
            <Icon name="cloud" size={14} /> พยากรณ์รายชั่วโมง
          </span>
        </div>
      </header>

      <main className={`lp-main deck front-${front}`}>
        <div className="lp-head">
          <span className="hero2-tag">ระบบวิเคราะห์ความปลอดภัยอัจฉริยะ</span>
          <h1 className="font-serif">
            ทุกเส้นทาง รอดได้ <em>ถ้าเข้าใจและวางแผนดี</em>
          </h1>
          <p className="muted">
            เช็กอากาศ ณ เวลาที่รถไปถึงจริง น้ำท่วมจากดาวเทียม
            และจุดเสี่ยงภัยตลอดเส้นทาง พร้อมน้องกิเลน AI ผู้ช่วยส่วนตัว
          </p>
        </div>

        {/* การ์ดสองใบซ้อนกันแบบ 3 มิติ กดใบหลังเพื่อยกขึ้นมาข้างหน้า */}
        <div className="deck-stage">
          <section
            className="deck-panel deck-show"
            aria-label="ตัวอย่างหน้าเว็บ"
          >
            <div className="deck-body" inert={front !== "show"}>
              <Showcase idle={front !== "show"} />
            </div>
            {front !== "show" && (
              <button
                type="button"
                className="deck-cover"
                onClick={() => setFront("show")}
                aria-label="ยกตัวอย่างหน้าเว็บขึ้นมาดู"
              >
                <span className="deck-hint">
                  <Icon name="map" size={15} /> คลิกเพื่อดูตัวอย่างเว็บ
                </span>
              </button>
            )}
          </section>

          <section className="deck-panel deck-login" aria-label="เข้าสู่ระบบ">
            <div className="deck-body lp-side" inert={front !== "login"}>
              <section className="lp-form">
                <LoginCard
                  mode={mode}
                  setMode={setMode}
                  busy={busy}
                  error={error}
                  onSubmit={submit}
                  onGoogle={google}
                />
              </section>
              <div className="auth-points">
                {POINTS.map((p) => (
                  <div key={p.text} className="auth-point">
                    <span className="ap-icon">
                      <Icon name={p.icon} size={16} />
                    </span>
                    {p.text}
                  </div>
                ))}
              </div>
            </div>
            {front !== "login" && (
              <button
                type="button"
                className="deck-cover"
                onClick={() => setFront("login")}
                aria-label="ยกการ์ดเข้าสู่ระบบขึ้นมา"
              >
                <span className="deck-hint">
                  <Icon name="lock" size={15} /> คลิกเพื่อเข้าสู่ระบบ
                </span>
              </button>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}
