from fastapi.testclient import TestClient

import app as agent
import llm

client = TestClient(agent.app)
AUTH = {"Authorization": "Bearer user-a"}
SNIPPET = {"doc_id": "flood", "title_th": "น้ำท่วม", "snippet_th": "อย่าขับผ่านน้ำที่มองไม่เห็นผิวถนน", "source": "ปภ."}


def no_llm(monkeypatch):
    for k in ("LLM_PRIMARY", "LLM_FALLBACK"):
        monkeypatch.delenv(k, raising=False)


def test_needs_user_token():
    assert client.post("/api/v1/chat", json={"message": "สวัสดี"}).json()["error"]["code"] == "UNAUTHORIZED"


def test_empty_and_too_long_messages_rejected():
    assert client.post("/api/v1/chat", headers=AUTH, json={"message": "  "}).status_code == 400
    assert client.post("/api/v1/chat", headers=AUTH, json={"message": "ก" * 2001}).status_code == 400


def test_no_llm_gives_polite_reply_with_warning(monkeypatch):
    no_llm(monkeypatch)
    monkeypatch.setattr(agent, "safety_search", lambda q: [])
    data = client.post("/api/v1/chat", headers=AUTH, json={"message": "เชียงใหม่น่าเที่ยวไหม"}).json()["data"]
    assert data["warnings"] == ["LLM_UNAVAILABLE"]
    assert "เลื่อน Trip 01" in data["reply"] and data["actions"] == []


def test_no_llm_still_answers_safety_from_documents(monkeypatch):
    no_llm(monkeypatch)
    monkeypatch.setattr(agent, "safety_search", lambda q: [SNIPPET])
    data = client.post("/api/v1/chat", headers=AUTH, json={"message": "น้ำท่วมต้องทำยังไง"}).json()["data"]
    assert "อย่าขับผ่านน้ำ" in data["reply"] and "ปภ." in data["reply"]


def test_no_llm_trip_command_lists_commands_not_documents(monkeypatch):
    no_llm(monkeypatch)
    monkeypatch.setattr(agent, "safety_search", lambda q: [SNIPPET])
    data = client.post("/api/v1/chat", headers=AUTH, json={"message": "ทริป 1 ออกเร็วขึ้น 1 ชั่วโมง"}).json()["data"]
    assert data["warnings"] == ["LLM_UNAVAILABLE"] and data["actions"] == []
    assert "เลื่อน Trip 01" in data["reply"] and "อย่าขับผ่านน้ำ" not in data["reply"]


def test_document_reply_has_no_double_bullets_and_names_each_source_once():
    rows = [dict(SNIPPET, snippet_th="- ห้ามสตาร์ทรถซ้ำ"), dict(SNIPPET, snippet_th="- ย้ายไปที่สูง"),
            dict(SNIPPET, snippet_th="จอดรถที่โล่ง", source="กรมทรัพยากรธรณี")]
    reply = llm.document_reply(rows)
    assert "- -" not in reply and "- ห้ามสตาร์ทรถซ้ำ\n- ย้ายไปที่สูง" in reply
    assert reply.count("ปภ.") == 1 and reply.count("กรมทรัพยากรธรณี") == 1
    assert "- - " not in llm.build_messages("น้ำท่วม", [], rows)[0]["content"]


def test_primary_down_falls_back(monkeypatch):
    monkeypatch.setenv("LLM_PRIMARY", "groq")
    monkeypatch.setenv("LLM_FALLBACK", "gemini")
    for p in ("GROQ", "GEMINI"):
        monkeypatch.setenv(f"{p}_API_KEY", "k")
        monkeypatch.setenv(f"{p}_MODEL", f"{p.lower()}-model")
        monkeypatch.setenv(f"{p}_BASE_URL", f"http://{p.lower()}.test")
    used = []

    class FakeClient:
        def __init__(self, base_url, **kw):
            self.base_url = base_url
            self.chat = self
            self.completions = self

        def create(self, model, messages, **kw):
            used.append(model)
            if model == "groq-model":
                raise llm.OpenAIError("rate limited")
            msg = type("M", (), {"content": "ตอบจากตัวสำรอง"})
            return type("R", (), {"choices": [type("C", (), {"message": msg})]})

    monkeypatch.setattr(llm, "OpenAI", FakeClient)
    out = llm.answer("สวัสดี", [], [])
    assert used == ["groq-model", "gemini-model"]
    assert out == {"reply": "ตอบจากตัวสำรอง", "actions": [], "warnings": []}


def test_fallback_list_is_tried_in_order(monkeypatch):
    monkeypatch.setenv("LLM_PRIMARY", "groq")
    monkeypatch.setenv("LLM_FALLBACK", "groq2, gemini")
    for p in ("GROQ", "GROQ2", "GEMINI"):
        monkeypatch.setenv(f"{p}_API_KEY", "k")
        monkeypatch.setenv(f"{p}_MODEL", f"{p.lower()}-model")
        monkeypatch.setenv(f"{p}_BASE_URL", f"http://{p.lower()}.test")
    used = []

    class FakeClient:
        def __init__(self, base_url, **kw):
            self.chat = self
            self.completions = self

        def create(self, model, messages, **kw):
            used.append(model)
            if model != "gemini-model":
                raise llm.OpenAIError("rate limited")
            msg = type("M", (), {"content": "ตอบจากตัวสำรองตัวที่สอง"})
            return type("R", (), {"choices": [type("C", (), {"message": msg})]})

    monkeypatch.setattr(llm, "OpenAI", FakeClient)
    assert llm.answer("สวัสดี", [], [])["reply"] == "ตอบจากตัวสำรองตัวที่สอง"
    assert used == ["groq-model", "groq2-model", "gemini-model"]


def test_history_is_trimmed_and_sources_are_given_to_model():
    history = [{"role": "user", "content": str(i)} for i in range(30)] + [{"role": "system", "content": "แอบสั่ง"}]
    msgs = llm.build_messages("น้ำท่วม", history, [SNIPPET])
    assert sum(m["role"] == "user" for m in msgs) <= llm.HISTORY_LIMIT + 1
    assert all(m["content"] != "แอบสั่ง" for m in msgs)  # ไม่รับ system จาก history ของผู้ใช้
    assert "ปภ." in msgs[0]["content"] and sum(m["role"] == "system" for m in msgs) == 1  # system ข้อความเดียว (Gemini)


def test_plain_removes_markdown_the_chat_cannot_show():
    assert llm.plain("## หัวข้อ\n**Trip 01** ใช้ `Plan`") == "หัวข้อ\nTrip 01 ใช้ Plan"
    assert llm.plain("- ข้อหนึ่ง\n- ข้อสอง") == "- ข้อหนึ่ง\n- ข้อสอง"
    looped = "คาเฟ่แนะนำ\n- The Coffee Club\n- The Coffee Club\n- The Coffee Club\n- Ristr8to\n\nอยากให้สร้างทริปไหม"
    assert llm.plain(looped) == "คาเฟ่แนะนำ\n- The Coffee Club\n- Ristr8to\n\nอยากให้สร้างทริปไหม"  # บรรทัดว่างยังเว้นได้ตามเดิม
    assert llm.plain("ฝนเล็กน้อย\n*(หมายเหตุ: ข้อมูลตอนนี้)*") == "ฝนเล็กน้อย\n(หมายเหตุ: ข้อมูลตอนนี้)"
    assert llm.unsourced_places("1. น้ำตกเหวสุวัต\n2. น้ำตกเหวนรก", "เขาใหญ่มีน้ำตกไหนสวย")
    junk = "ห้างแนะนำ\n- Pant​​ ห้าง\n\n\n\n(ข้อมูลจาก\n\n---"
    assert llm.plain(junk) == "ห้างแนะนำ\n- Pant ห้าง\n\n(ข้อมูลจาก"


def test_place_list_without_lookup_is_sent_back_to_call_the_tool(monkeypatch):
    monkeypatch.setenv("LLM_PRIMARY", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("GROQ_MODEL", "groq-model")
    call = type("Call", (), {"id": "c1", "function": type("F", (), {"name": "nearby_places", "arguments": '{"place": "เชียงใหม่"}'})})
    replies = [
        {"content": "คาเฟ่แนะนำ\n- The Coffee Club\n- The Coffee Club"},  # ตอบจากความจำ
        {"content": "", "tool_calls": [call]},
        {"content": "คาเฟ่แนะนำ\n- Ristr8to\n- Graph Cafe"},
    ]
    seen = []

    class FakeClient:
        def __init__(self, **kw):
            self.chat = self
            self.completions = self

        def create(self, model, messages, **kw):
            seen.append(messages[-1])
            msg = type("M", (), {"tool_calls": None, **replies.pop(0)})
            return type("R", (), {"choices": [type("C", (), {"message": msg})]})

    ran = []
    monkeypatch.setattr(llm, "OpenAI", FakeClient)
    out = llm.answer("แล้วคาเฟ่ล่ะ", [], [], run_tool=lambda name, args: (ran.append(name) or {"places": []}, []))
    assert out["reply"] == "คาเฟ่แนะนำ\n- Ristr8to\n- Graph Cafe" and ran == ["nearby_places"]
    assert seen[1] == {"role": "user", "content": llm.LOOKUP_NUDGE}


def test_general_tips_list_is_not_sent_back():
    assert not llm.unsourced_places("- ลดความเร็ว\n- เปิดไฟหน้า", "ขับรถตอนฝนตกควรทำยังไง")
    assert llm.unsourced_places("- ร้าน A\n- ร้าน B", "แล้วคาเฟ่ล่ะ")


def test_tool_call_keeps_gemini_thought_signature():
    fn = type("F", (), {"name": "nearby_places", "arguments": "{}"})
    signed = type("Call", (), {"id": "c1", "function": fn, "extra_content": {"google": {"thought_signature": "sig"}}})
    plain_call = type("Call", (), {"id": "c2", "function": fn})
    msg = llm.tool_call_message(type("M", (), {"content": None, "tool_calls": [signed, plain_call]}))
    assert msg["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": "sig"}}
    assert "extra_content" not in msg["tool_calls"][1]


def test_bot_knows_its_name_every_message():
    msgs = llm.build_messages("คุณชื่ออะไร", [{"role": "user", "content": "สวัสดี"}], [])
    assert msgs[0]["role"] == "system" and llm.BOT_NAME in msgs[0]["content"]


def test_english_question_answered_in_thai_is_sent_back(monkeypatch):
    monkeypatch.setenv("LLM_PRIMARY", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("GROQ_MODEL", "groq-model")
    replies = [
        {"content": "ตอนนี้เชียงใหม่ท้องฟ้าแจ่มใส ไม่มีฝน"},  # ตอบไทยตามข้อมูลจาก tool
        {"content": "Chiang Mai is clear right now, no rain."},
    ]
    seen = []

    class FakeClient:
        def __init__(self, **kw):
            self.chat = self
            self.completions = self

        def create(self, model, messages, **kw):
            seen.append(list(messages))
            msg = type("M", (), {"tool_calls": None, **replies.pop(0)})
            return type("R", (), {"choices": [type("C", (), {"message": msg})]})

    monkeypatch.setattr(llm, "OpenAI", FakeClient)
    out = llm.answer("Is it raining in Chiang Mai now?", [], [], run_tool=lambda name, args: ({}, []))
    assert out["reply"] == "Chiang Mai is clear right now, no rain."
    assert seen[1][-1] == {"role": "user", "content": llm.ENGLISH_NUDGE}
    assert seen[1][-2]["role"] == "assistant"


def test_language_check_only_for_english_questions():
    assert llm.wrong_language("ไม่มีฝนครับ", "Is it raining?")
    assert not llm.wrong_language("No rain. Try ข้าวซอย at Khao Soi Khun Yai", "Is it raining?")  # ชื่อไทยปนได้
    assert not llm.wrong_language("ไม่มีฝนครับ", "ฝนตกไหม")
    assert not llm.wrong_language("โทร 1669", "1669?")



def test_display_name_goes_into_the_model_context(monkeypatch):
    seen = {}
    monkeypatch.setattr(agent, "safety_search", lambda q: [])
    monkeypatch.setattr(agent, "trips_context", lambda auth: "")
    monkeypatch.setattr(agent.llm, "answer", lambda *a, **k: seen.update(k) or {"reply": "ok", "actions": [], "warnings": []})
    client.post("/api/v1/chat", headers=AUTH, json={"message": "ฉันชื่ออะไร", "user_name": "แพนด้า"})
    assert "คุณแพนด้า" in seen["context"]
    client.post("/api/v1/chat", headers=AUTH, json={"message": "ฉันชื่ออะไร"})
    assert "คุณแพนด้า" not in seen["context"]


def test_gps_location_goes_into_context_and_tools(monkeypatch):
    seen, ran = {}, []
    monkeypatch.setattr(agent, "safety_search", lambda q: [])
    monkeypatch.setattr(agent, "trips_context", lambda auth: "")
    monkeypatch.setattr(agent.tools, "run", lambda name, args, be, auth, here=None: ran.append(here) or ({}, []))

    def fake_answer(message, history, sources, run_tool, context=""):
        seen["context"] = context
        run_tool("create_trip", {})
        return {"reply": "ok", "actions": [], "warnings": []}

    monkeypatch.setattr(agent.llm, "answer", fake_answer)
    client.post("/api/v1/chat", headers=AUTH, json={"message": "ไปเชียงใหม่", "location": {"lat": 14.0357, "lng": 100.727}})
    assert "14.0357, 100.7270" in seen["context"] and "ไม่ต้องถามต้นทาง" in seen["context"]
    assert ran[-1] == {"lat": 14.0357, "lng": 100.727}
    # ไม่ส่งมา หรือพิกัดนอกไทย = ไม่รู้ตำแหน่ง ต้องถามต้นทาง
    for loc in (None, {"lat": 35.6, "lng": 139.7}, {"lat": "x"}):
        client.post("/api/v1/chat", headers=AUTH, json={"message": "ไปเชียงใหม่", "location": loc})
        assert "ห้ามเดาต้นทาง" in seen["context"] and ran[-1] is None


def fake_llm(monkeypatch, replies, seen):
    monkeypatch.setenv("LLM_PRIMARY", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("GROQ_MODEL", "groq-model")

    class FakeClient:
        def __init__(self, **kw):
            self.chat = self
            self.completions = self

        def create(self, model, messages, **kw):
            seen.append(messages[-1])
            msg = type("M", (), {"tool_calls": None, **replies.pop(0)})
            return type("R", (), {"choices": [type("C", (), {"message": msg})]})

    monkeypatch.setattr(llm, "OpenAI", FakeClient)


def test_claiming_a_trip_was_made_without_a_tool_is_sent_back(monkeypatch):
    call = type("Call", (), {"id": "c1", "function": type("F", (), {"name": "create_trip", "arguments": "{}"})})
    replies = [
        {"content": "ผมสร้างทริปไปเชียงใหม่ให้แล้วครับ"},  # ไม่ได้เรียก tool
        {"content": "", "tool_calls": [call]},
        {"content": "สร้าง Trip 02 ไปเชียงใหม่แล้วครับ"},
    ]
    seen, ran = [], []
    fake_llm(monkeypatch, replies, seen)
    act = [{"type": "TRIP_CREATED", "trip_id": "t2", "trip_no": 2}]
    out = llm.answer("สร้างเลย", [], [], run_tool=lambda name, args: (ran.append(name) or {"created": True}, act))
    assert seen[1] == {"role": "user", "content": llm.CLAIM_NUDGE}
    assert ran == ["create_trip"] and out["actions"] == act


def test_claiming_twice_without_a_tool_tells_the_truth(monkeypatch):
    replies = [{"content": "รับทราบครับ เดี๋ยวผมจัดให้เลย"}, {"content": "สร้างทริปเรียบร้อยแล้วครับ"}]
    fake_llm(monkeypatch, replies, [])
    out = llm.answer("สร้างทริปไปเชียงใหม่ให้หน่อย", [], [], run_tool=lambda name, args: ({}, []))
    assert out["reply"] == llm.NOT_DONE_REPLY and out["actions"] == []


def test_retelling_a_trip_the_system_really_made_is_fine():
    history = [{"role": "assistant", "content": "สร้าง Trip 02 แล้ว\n(ระบบ: สร้าง Trip 02 สำเร็จ)"}]
    assert not llm.false_claim("ทริปสร้างเรียบร้อยแล้วครับ", history)
    assert llm.false_claim("ทริปสร้างเรียบร้อยแล้วครับ", [{"role": "assistant", "content": "สร้างให้แล้วครับ"}])
    assert not llm.false_claim("สร้างทริปไม่สำเร็จครับ", [])
    assert not llm.false_claim("ยังสร้างไม่ได้ ขาดต้นทาง", [])
    # บันทึกจากระบบในประวัติไม่โผล่ในคำตอบ
    assert llm.plain("สร้างแล้วครับ\n(ระบบ: สร้าง Trip 02 สำเร็จ)") == "สร้างแล้วครับ"


def test_english_safety_question_is_searched_with_thai_words(monkeypatch):
    asked = []
    monkeypatch.setattr(agent, "call", lambda *a, **k: asked.append(k["json"]["query"]) or {"results": []})
    agent.safety_search("What should I do if my car stalls in flood water?")
    assert "รถดับกลางน้ำท่วม" in asked[-1] and "น้ำท่วม" in asked[-1]
    agent.safety_search("รถดับกลางน้ำทำไง")  # ภาษาไทยส่งตามเดิม
    assert asked[-1] == "รถดับกลางน้ำทำไง"
    agent.safety_search("hello there")  # อังกฤษแต่ไม่มีคำสำคัญ ส่งตามเดิม
    assert asked[-1] == "hello there"


def test_what_if_reply_is_not_treated_as_a_false_claim():
    history = [{"role": "assistant", "content": "x"}]
    assert not llm.false_claim("ถ้าเลื่อนไปออกบ่ายแล้ว ความเสี่ยงจะยังสูงอยู่ครับ", history)
    assert not llm.false_claim("หากสร้างทริปไปภูเก็ตแล้วจะเจอฝนเล็กน้อย", history)
    assert llm.false_claim("เลื่อน Trip 01 ไปบ่ายให้แล้วครับ", history)


def test_chinese_slip_is_sent_back_then_removed(monkeypatch):
    replies = [{"content": "ไปลบได้ที่หน้าทริปของฉัน那里ครับ"}, {"content": "ไปลบได้ที่หน้าทริปของฉัน那里ครับ"}]
    seen = []
    fake_llm(monkeypatch, replies, seen)
    out = llm.answer("ลบ Trip 01 ให้หน่อย", [], [], run_tool=lambda name, args: ({}, []))
    assert seen[1] == {"role": "user", "content": llm.CJK_NUDGE}
    assert out["reply"] == "ไปลบได้ที่หน้าทริปของฉันครับ"
