import json
from pathlib import Path

from backend.modules import drug_service


def _reset_caches() -> None:
    drug_service._DB = None
    drug_service._NORMALIZED_KEY_INDEX = None
    drug_service._KEYS_LIST = None
    drug_service._NORMALIZED_KEYS_LIST = None
    drug_service._USER_FAKE_MEDICINES = None
    drug_service._USER_FAKE_KEYS_LIST = None
    drug_service._BANNED_DRUGS = None
    drug_service._BANNED_KEYS_LIST = None


def test_lookup_exact():
    data = {"dolo 650": {"name": "Dolo 650", "dosage": "650 mg", "manufacturer": "Micro Labs"}}

    # point loader at our temp file by temporarily replacing the data file path
    # monkeypatching internal path is unnecessary; load_db reads from data/drug_info.json
    # so write to that path inside the repo instead for test isolation
    repo_path = Path(__file__).parent.parent / "backend" / "data"
    repo_path.mkdir(parents=True, exist_ok=True)
    dst = repo_path / "drug_info.json"
    dst.write_text(json.dumps(data), encoding="utf-8")
    # Clear cached DB so loader picks up our test file
    _reset_caches()

    result = drug_service.lookup_drug("Dolo 650")
    assert result is not None
    assert result["name"].lower().startswith("dolo")
    assert result["score"] >= 99.0
    assert result["info"]["is_banned"] is False


def test_lookup_fuzzy():
    data = {
        "crocin": {
            "name": "Crocin",
            "dosage": "500 mg",
            "manufacturer": "GSK",
            "side_effects": ["Nausea"],
            "risks": ["Liver toxicity in overdose"],
        }
    }
    repo_path = Path(__file__).parent.parent / "backend" / "data"
    repo_path.mkdir(parents=True, exist_ok=True)
    dst = repo_path / "drug_info.json"
    dst.write_text(json.dumps(data), encoding="utf-8")
    _reset_caches()

    result = drug_service.lookup_drug("crocin500")
    assert result is not None
    assert "crocin" in result["name"].lower()
    assert result["score"] >= 50.0
    assert "Nausea" in result["info"]["side_effects"]
    assert "Liver toxicity in overdose" in result["info"]["risks"]


def test_lookup_true_medicine_flag():
    data = {
        "Gemtesa": {
            "name": "Gemtesa",
            "notes": "Allowlisted",
            "is_true_medicine": True,
            "true_medicine_source": "user_allowlist",
        }
    }
    repo_path = Path(__file__).parent.parent / "backend" / "data"
    repo_path.mkdir(parents=True, exist_ok=True)
    dst = repo_path / "drug_info.json"
    dst.write_text(json.dumps(data), encoding="utf-8")
    _reset_caches()

    result = drug_service.lookup_drug("gemtesa")

    assert result is not None
    assert result["info"]["is_true_medicine"] is True
    assert result["info"]["true_medicine_source"] == "user_allowlist"
    assert "Overactive bladder" in result["info"]["uses"]
    assert "Overactive bladder" in result["info"]["assistant_summary"]
    assert result["info"]["reference_sources"] == []


def test_lookup_banned_without_regular_db():
    repo_path = Path(__file__).parent.parent / "backend" / "data"
    repo_path.mkdir(parents=True, exist_ok=True)
    dst = repo_path / "drug_info.json"
    dst.write_text("{}", encoding="utf-8")

    _reset_caches()
    drug_service._BANNED_DRUGS = {"phenacetin": "Phenacetin"}
    drug_service._BANNED_KEYS_LIST = ["phenacetin"]

    result = drug_service.lookup_drug("Phenacetin 500")

    assert result is not None
    assert result["info"]["name"] == "Phenacetin"
    assert result["info"]["is_banned"] is True
    assert result["info"]["ban_source"] == "banneddrugs_1.pdf"


def test_lookup_user_fake_medicine_overrides_true_flag():
    data = {
        "Azithromycin": {
            "name": "Azithromycin",
            "notes": "Allowlisted",
            "is_true_medicine": True,
            "true_medicine_source": "user_allowlist",
        }
    }
    repo_path = Path(__file__).parent.parent / "backend" / "data"
    repo_path.mkdir(parents=True, exist_ok=True)
    dst = repo_path / "drug_info.json"
    dst.write_text(json.dumps(data), encoding="utf-8")
    _reset_caches()

    result = drug_service.lookup_drug("Azithromycin")

    assert result is not None
    assert result["info"]["is_fake_medicine"] is True
    assert result["info"]["fake_medicine_source"] == "user_fake_list"
    assert result["info"]["is_true_medicine"] is False


def test_lookup_new_fake_alias_variant():
    repo_path = Path(__file__).parent.parent / "backend" / "data"
    repo_path.mkdir(parents=True, exist_ok=True)
    dst = repo_path / "drug_info.json"
    dst.write_text("{}", encoding="utf-8")
    _reset_caches()

    result = drug_service.lookup_drug("Telma-AM")

    assert result is not None
    assert result["info"]["is_fake_medicine"] is True
    assert result["info"]["name"] == "Telmisartan (Telma, Telma-H, Telma-AM)"
    assert "High blood pressure" in result["info"]["uses"]
    assert "High blood pressure" in result["info"]["assistant_summary"]


def test_lookup_returns_reference_sources_for_web_verified_profile():
    data = {
        "Metformin": {
            "name": "Metformin",
            "notes": "Allowlisted",
            "is_true_medicine": True,
            "true_medicine_source": "user_allowlist",
        }
    }
    repo_path = Path(__file__).parent.parent / "backend" / "data"
    repo_path.mkdir(parents=True, exist_ok=True)
    dst = repo_path / "drug_info.json"
    dst.write_text(json.dumps(data), encoding="utf-8")
    _reset_caches()

    result = drug_service.lookup_drug("Metformin")

    assert result is not None
    assert "type 2 diabetes" in result["info"]["assistant_summary"].lower()
    assert result["info"]["reference_sources"] == ["https://www.nhs.uk/medicines/metformin/about-metformin/"]
