"""login ด้วย Google: ตรวจ ID token ด้วยกุญแจทดสอบที่สร้างเอง (ไม่ต่อ Google จริง)"""
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

import auth

CLIENT_ID = "test-client.apps.googleusercontent.com"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def google_token(email, key=KEY, **claims):
    now = int(time.time())
    payload = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "1234", "email": email,
               "email_verified": True, "name": "นักทดสอบ", "iat": now, "exp": now + 600, **claims}
    return jwt.encode(payload, key, algorithm="RS256")


@pytest.fixture(autouse=True)
def fake_google(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(auth, "_google_signing_key", lambda credential: KEY.public_key())


def test_config_tells_the_web_whether_google_is_on(client, monkeypatch):
    assert client.get("/api/v1/auth/config").json()["data"] == {"google_client_id": CLIENT_ID}
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    assert client.get("/api/v1/auth/config").json()["data"] == {"google_client_id": None}
    res = client.post("/api/v1/auth/google", json={"credential": google_token("a@example.com")})
    assert res.status_code == 400


def test_first_google_login_creates_account_with_google_name(client):
    email = f"g-{uuid.uuid4()}@example.com"
    res = client.post("/api/v1/auth/google", json={"credential": google_token(email.upper())})
    data = res.json()["data"]
    assert res.status_code == 200 and data["user"]["email"] == email and data["user"]["display_name"] == "นักทดสอบ"
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {data['token']}"}).json()["data"]
    assert me["email"] == email
    # ครั้งที่สองได้บัญชีเดิม
    again = client.post("/api/v1/auth/google", json={"credential": google_token(email)}).json()["data"]
    assert again["user"]["user_id"] == data["user"]["user_id"]


def test_same_email_as_password_account_signs_into_it_and_password_still_works(client):
    email = f"p-{uuid.uuid4()}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "secret123"})
    user = client.post("/api/v1/auth/google", json={"credential": google_token(email)}).json()["data"]["user"]
    assert user["display_name"] is None  # บัญชีเดิมไม่ถูกเปลี่ยนชื่อ
    assert client.post("/api/v1/auth/login", json={"email": email, "password": "secret123"}).status_code == 200


@pytest.mark.parametrize("bad", [
    lambda e: google_token(e, key=OTHER_KEY),  # ไม่ได้เซ็นโดย Google
    lambda e: google_token(e, aud="someone-else"),  # ออกให้แอปอื่น
    lambda e: google_token(e, iss="https://evil.example.com"),
    lambda e: google_token(e, email_verified=False),
    lambda e: google_token(e, exp=int(time.time()) - 10),
    lambda e: "not-a-token",
])
def test_bad_tokens_are_rejected_and_create_nothing(client, bad):
    email = f"bad-{uuid.uuid4()}@example.com"
    res = client.post("/api/v1/auth/google", json={"credential": bad(email)})
    assert res.status_code == 401 and res.json()["data"] is None
    import db
    assert db.find_user_by_email(email) is None


def test_google_account_has_no_usable_password(client):
    email = f"g-{uuid.uuid4()}@example.com"
    client.post("/api/v1/auth/google", json={"credential": google_token(email)})
    for pw in ("", "secret123", "None"):
        assert client.post("/api/v1/auth/login", json={"email": email, "password": pw}).status_code == 401
