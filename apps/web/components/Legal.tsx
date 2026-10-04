// โครงหน้านโยบายความเป็นส่วนตัว / เงื่อนไขการใช้งาน เปิดได้โดยไม่ต้อง login (Google ลิงก์มาจากหน้าต่าง login)
export const UPDATED = "4 ตุลาคม 2569";
export const CONTACT_EMAIL = "pitchakorn.pkt@gmail.com"; // อีเมลผู้ดูแลโปรเจกต์ (บัญชี GitHub เจ้าของ repo)

export default function Legal({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <main className="legal">
      <a className="legal-back" href="/login">
        <img src="/assets/shared/qilin-avatar.webp" alt="" />
        รอดไม่รอด
      </a>
      <article className="legal-card">
        <h1>{title}</h1>
        <p className="legal-updated">ปรับปรุงล่าสุด {UPDATED}</p>
        {children}
      </article>
    </main>
  );
}
