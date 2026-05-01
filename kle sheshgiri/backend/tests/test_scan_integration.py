import cv2
import main as main_module
import numpy as np
from fastapi.testclient import TestClient

from db import get_db
from main import app
from modules import drug_service


def test_scan_persists_fusion_metadata() -> None:
    img = np.full((300, 500, 3), 255, dtype=np.uint8)
    cv2.putText(img, "Medicine: DemoMed", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    ok, buf = cv2.imencode(".png", img)
    assert ok

    with TestClient(app) as client:
        files = [("images", ("demo.png", buf.tobytes(), "image/png"))]
        response = client.post("/scan", files=files)

    assert response.status_code == 200
    payload = response.json()
    assert "parsed_data" in payload

    with get_db() as db:
        latest = db.execute(
            "SELECT * FROM scan_history ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert latest is not None
    fused_data = latest["fused_data"]
    if isinstance(fused_data, str):
        import json

        fused_data = json.loads(fused_data)

    assert isinstance(fused_data, dict)
    assert "fields" in fused_data
    assert "fusion_meta" in fused_data
    assert "medicine_name" in fused_data["fusion_meta"]
    assert "chosen_by" in fused_data["fusion_meta"]["medicine_name"]


def test_scan_flags_banned_medicine(monkeypatch) -> None:
    drug_service._BANNED_DRUGS = {"phenacetin": "Phenacetin"}
    drug_service._BANNED_KEYS_LIST = ["phenacetin"]
    drug_service._DB = {}
    drug_service._NORMALIZED_KEY_INDEX = {}
    drug_service._KEYS_LIST = []
    drug_service._NORMALIZED_KEYS_LIST = []
    monkeypatch.setattr(main_module, "extract_text", lambda image: ("Medicine: Phenacetin", {}))

    img = np.full((300, 500, 3), 255, dtype=np.uint8)
    cv2.putText(img, "Medicine: Phenacetin", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    ok, buf = cv2.imencode(".png", img)
    assert ok

    with TestClient(app) as client:
        files = [("images", ("demo.png", buf.tobytes(), "image/png"))]
        response = client.post("/scan", files=files)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "High Risk"
    assert payload["drug_info"]["is_banned"] is True
    assert any(issue["code"] == "banned_medicine_reference_match" for issue in payload["reasons"])


def test_scan_prefers_user_entered_medicine_name(monkeypatch) -> None:
    drug_service._BANNED_DRUGS = {"phenacetin": "Phenacetin"}
    drug_service._BANNED_KEYS_LIST = ["phenacetin"]
    drug_service._USER_FAKE_MEDICINES = {}
    drug_service._USER_FAKE_KEYS_LIST = []
    drug_service._DB = {
        "Gemtesa": {
            "name": "Gemtesa",
            "notes": "Allowlisted",
            "is_true_medicine": True,
            "true_medicine_source": "user_allowlist",
        }
    }
    drug_service._NORMALIZED_KEY_INDEX = {"gemtesa": "Gemtesa"}
    drug_service._KEYS_LIST = ["Gemtesa"]
    drug_service._NORMALIZED_KEYS_LIST = ["gemtesa"]
    monkeypatch.setattr(main_module, "extract_text", lambda image: ("Medicine: Phenacetin", {}))

    img = np.full((300, 500, 3), 255, dtype=np.uint8)
    cv2.putText(img, "Medicine: Phenacetin", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    ok, buf = cv2.imencode(".png", img)
    assert ok

    with TestClient(app) as client:
        files = [("images", ("demo.png", buf.tobytes(), "image/png"))]
        response = client.post("/scan", data={"medicine_name": "Gemtesa"}, files=files)

    assert response.status_code == 200
    payload = response.json()
    assert payload["drug_info"]["name"] == "Gemtesa"
    assert payload["drug_info"]["is_true_medicine"] is True
    assert payload["status"] == "Safe"
    assert payload["risk_score"] <= 20.0
    assert payload["parsed_data"]["medicine_name"] == "Gemtesa"


def test_risk_preview_reflects_medicine_name(monkeypatch) -> None:
    drug_service._BANNED_DRUGS = {"phenacetin": "Phenacetin"}
    drug_service._BANNED_KEYS_LIST = ["phenacetin"]
    drug_service._USER_FAKE_MEDICINES = {}
    drug_service._USER_FAKE_KEYS_LIST = []
    drug_service._DB = {
        "Gemtesa": {
            "name": "Gemtesa",
            "notes": "Allowlisted",
            "is_true_medicine": True,
            "true_medicine_source": "user_allowlist",
        }
    }
    drug_service._NORMALIZED_KEY_INDEX = {"gemtesa": "Gemtesa"}
    drug_service._KEYS_LIST = ["Gemtesa"]
    drug_service._NORMALIZED_KEYS_LIST = ["gemtesa"]

    with TestClient(app) as client:
        safe_response = client.post("/risk/preview", json={"medicine_name": "Gemtesa"})
        risky_response = client.post("/risk/preview", json={"medicine_name": "Phenacetin"})

    assert safe_response.status_code == 200
    assert risky_response.status_code == 200

    safe_payload = safe_response.json()
    risky_payload = risky_response.json()

    assert safe_payload["status"] == "Safe"
    assert safe_payload["risk_score"] <= 20.0
    assert risky_payload["status"] == "High Risk"
    assert risky_payload["risk_score"] >= 85.0


def test_scan_lowers_risk_for_true_medicine(monkeypatch) -> None:
    drug_service._BANNED_DRUGS = {}
    drug_service._BANNED_KEYS_LIST = []
    drug_service._DB = {
        "Gemtesa": {
            "name": "Gemtesa",
            "notes": "Allowlisted",
            "is_true_medicine": True,
            "true_medicine_source": "user_allowlist",
        }
    }
    drug_service._NORMALIZED_KEY_INDEX = {"gemtesa": "Gemtesa"}
    drug_service._KEYS_LIST = ["Gemtesa"]
    drug_service._NORMALIZED_KEYS_LIST = ["gemtesa"]
    monkeypatch.setattr(main_module, "extract_text", lambda image: ("Medicine: Gemtesa", {}))
    monkeypatch.setattr(
        main_module,
        "validate_fields",
        lambda fused: [{"code": "test_high_issue", "message": "synthetic issue", "severity": "high"}],
    )

    img = np.full((300, 500, 3), 255, dtype=np.uint8)
    cv2.putText(img, "Medicine: Gemtesa", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    ok, buf = cv2.imencode(".png", img)
    assert ok

    with TestClient(app) as client:
        files = [("images", ("demo.png", buf.tobytes(), "image/png"))]
        response = client.post("/scan", files=files)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "Safe"
    assert payload["risk_score"] <= 20.0
    assert payload["drug_info"]["is_true_medicine"] is True


def test_scan_flags_user_fake_medicine_as_high_risk(monkeypatch) -> None:
    drug_service._USER_FAKE_MEDICINES = {"azithromycin": "Azithromycin"}
    drug_service._USER_FAKE_KEYS_LIST = ["azithromycin"]
    drug_service._BANNED_DRUGS = {}
    drug_service._BANNED_KEYS_LIST = []
    drug_service._DB = {
        "Azithromycin": {
            "name": "Azithromycin",
            "notes": "Allowlisted",
            "is_true_medicine": True,
            "true_medicine_source": "user_allowlist",
        }
    }
    drug_service._NORMALIZED_KEY_INDEX = {"azithromycin": "Azithromycin"}
    drug_service._KEYS_LIST = ["Azithromycin"]
    drug_service._NORMALIZED_KEYS_LIST = ["azithromycin"]
    monkeypatch.setattr(main_module, "extract_text", lambda image: ("Medicine: Azithromycin", {}))

    img = np.full((300, 500, 3), 255, dtype=np.uint8)
    cv2.putText(img, "Medicine: Azithromycin", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    ok, buf = cv2.imencode(".png", img)
    assert ok

    with TestClient(app) as client:
        files = [("images", ("demo.png", buf.tobytes(), "image/png"))]
        response = client.post("/scan", files=files)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "High Risk"
    assert payload["risk_score"] >= 85.0
    assert payload["drug_info"]["is_fake_medicine"] is True
    assert payload["drug_info"]["is_true_medicine"] is False
    assert any(issue["code"] == "user_fake_medicine_match" for issue in payload["reasons"])
