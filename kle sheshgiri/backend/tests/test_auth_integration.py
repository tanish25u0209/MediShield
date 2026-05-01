import uuid

from fastapi.testclient import TestClient

from main import app


def test_signup_login_and_reset_password_flow() -> None:
    email = f"auth-{uuid.uuid4().hex[:12]}@example.com"
    password = "SecurePass123"
    new_password = "EvenBetter456"

    with TestClient(app) as client:
        signup_response = client.post(
            "/auth/signup",
            json={"name": "Test User", "email": email, "password": password},
        )
        assert signup_response.status_code == 200
        signup_payload = signup_response.json()
        assert signup_payload["user"]["email"] == email

        login_response = client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )
        assert login_response.status_code == 200

        forgot_response = client.post(
            "/auth/forgot-password",
            json={"email": email},
        )
        assert forgot_response.status_code == 200
        forgot_payload = forgot_response.json()
        assert len(forgot_payload["reset_code"]) == 6

        reset_response = client.post(
            "/auth/reset-password",
            json={"email": email, "code": forgot_payload["reset_code"], "new_password": new_password},
        )
        assert reset_response.status_code == 200

        old_login_response = client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )
        assert old_login_response.status_code == 401

        new_login_response = client.post(
            "/auth/login",
            json={"email": email, "password": new_password},
        )
        assert new_login_response.status_code == 200
