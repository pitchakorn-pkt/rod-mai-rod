import type { Metadata } from "next";
import "./globals.css";
import Shell from "@/components/Shell";
import { AppProvider } from "@/lib/store";
import { ChatProvider } from "@/lib/chat";

export const metadata: Metadata = {
  title: "รอดไม่รอด · ระบบวางแผนเดินทางปลอดภัย",
  description: "ระบบวิเคราะห์สภาพอากาศและจุดเสี่ยงภัยตลอดเส้นทางแบบเรียลไทม์ พร้อมน้องกิเลน AI ผู้ช่วยเดินทาง",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="th">
      <body>
        <AppProvider>
          <ChatProvider>
            <Shell>{children}</Shell>
          </ChatProvider>
        </AppProvider>
      </body>
    </html>
  );
}

