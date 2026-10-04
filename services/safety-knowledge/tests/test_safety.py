import pytest
from fastapi.testclient import TestClient

from app import CONTACTS, HAZARD_TYPES, app, load_docs

client = TestClient(app)


def test_every_doc_has_title_source_and_known_hazards():
    for doc in load_docs():
        assert doc["title_th"] and doc["source"], doc["doc_id"]
        assert doc["lines"], doc["doc_id"]
        assert set(doc["hazard_types"]) <= HAZARD_TYPES, doc["doc_id"]


def test_search_filters_by_hazard_type():
    res = client.post("/api/v1/safety/search", json={"query": "น้ำ", "hazard_types": ["FLOOD"]}).json()
    assert res["error"] is None
    assert res["data"]["results"]
    flood_docs = {d["doc_id"] for d in load_docs() if "FLOOD" in d["hazard_types"]}
    assert all(r["doc_id"] in flood_docs for r in res["data"]["results"])


def test_empty_query_is_validation_error():
    res = client.post("/api/v1/safety/search", json={"query": "  "})
    assert res.status_code == 400


def test_emergency_always_has_contacts():
    data = client.get("/api/v1/safety/emergency", params={"hazard_type": "FLOOD"}).json()["data"]
    assert data["steps_th"] and data["contacts"] == CONTACTS


def test_unknown_hazard_type_is_rejected():
    res = client.get("/api/v1/safety/emergency", params={"hazard_type": "ZOMBIE"})
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_emergency_covers_all_7_hazard_types():
    for hazard in HAZARD_TYPES:
        res = client.get("/api/v1/safety/emergency", params={"hazard_type": hazard})
        assert res.status_code == 200
        data = res.json()["data"]
        assert len(data["steps_th"]) >= 2, f"Missing or short emergency steps for {hazard}"


@pytest.mark.parametrize(
    "query, expected_doc_id",
    [
        ("น้ำท่วมต้องทำยังไง", "flood"),
        ("ขับรถตอนฝนตกหนักควรทำไง", "heavy_rain"),
        ("แผ่นดินไหวระหว่างขับรถ", "earthquake"),
    ],
)
def test_search_thai_unspaced_queries(query, expected_doc_id):
    res = client.post("/api/v1/safety/search", json={"query": query})
    assert res.status_code == 200
    results = res.json()["data"]["results"]
    assert len(results) > 0, f"Query '{query}' returned no results"
    assert results[0]["doc_id"] == expected_doc_id, f"Expected {expected_doc_id} for query '{query}'"


@pytest.mark.parametrize("unrelated_query", ["สวัสดีครับ", "ร้านกาแฟอร่อยแถวนี้"])
def test_unrelated_queries_return_empty_results(unrelated_query):
    res = client.post("/api/v1/safety/search", json={"query": unrelated_query})
    assert res.status_code == 200
    assert res.json()["data"]["results"] == []
    
def test_title_scoring_ranks_strong_wind_first():
    res = client.post("/api/v1/safety/search", json={"query": "ลมแรงมากขับรถยังไงดี"})
    assert res.status_code == 200
    results = res.json()["data"]["results"]
    assert len(results) > 0
    assert results[0]["doc_id"] == "strong_wind"
    
def test_unrelated_query_returns_empty_results():
    res = client.post("/api/v1/safety/search", json={"query": "สูตรต้มยำกุ้ง"})
    assert res.status_code == 200
    results = res.json()["data"]["results"]
    assert results == []


@pytest.mark.parametrize(
    "query, expected_doc_id",
    [
        ("ไฟฟ้าดูดตอนน้ำท่วมต้องระวังอะไร", "flood_electric"),
        ("ต้องอพยพหนีน้ำท่วมเตรียมอะไรบ้าง", "flood_prepare"),
        ("ถนนปิดเพราะน้ำท่วมเช็คได้ที่ไหน", "road_status"),
    ],
)
def test_new_documents_are_found(query, expected_doc_id):
    results = client.post("/api/v1/safety/search", json={"query": query}).json()["data"]["results"]
    assert results and results[0]["doc_id"] == expected_doc_id


def test_few_matching_lines_are_filled_from_the_best_document():
    results = client.post("/api/v1/safety/search", json={"query": "รถดับกลางน้ำท่วมต้องทำยังไง"}).json()["data"]["results"]
    assert len(results) == 4
    assert "ถ้ารถดับกลางน้ำท่วม" in results[0]["snippet_th"]
    assert sum(r["doc_id"] == "flood" for r in results) >= 3  # ส่วนใหญ่มาจากเอกสารที่ตรงที่สุด
    assert len({(r["doc_id"], r["snippet_th"]) for r in results}) == 4  # ไม่ซ้ำ


def test_limit_is_respected_when_filling():
    results = client.post("/api/v1/safety/search", json={"query": "รถดับกลางน้ำท่วม", "limit": 2}).json()["data"]["results"]
    assert len(results) == 2

