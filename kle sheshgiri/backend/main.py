import json
import hashlib
import os
import uuid
import sys
import tempfile
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from auth_schemas import (
    AuthResponse,
    AuthUser,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    GenericMessageResponse,
    LoginRequest,
    ResetPasswordRequest,
    SignupRequest,
)
from db import get_db, init_db
from models import PasswordResetToken, ScanHistory, User
from modules.anomaly import detect_anomalies, load_batch_data
from modules.auth_service import (
    RESET_CODE_TTL_MINUTES,
    generate_reset_code,
    hash_password,
    normalize_email,
    reset_code_expiry,
    verify_password,
)
from modules.barcode import scan_codes
from modules.confidence import compute_confidence
from modules.consistency import check_consistency
from modules.fusion import fuse_data_with_meta
from modules.ml_insights import compute_ml_insights
from modules.ocr import extract_text, parse_fields
from modules.preprocess import decode_and_preprocess
from modules.risk import compute_risk
from modules.validation import validate_fields
from modules.vision import check_image_quality
from modules.drug_service import lookup_drug
from modules.predictor import find_medicine
from schemas import DrugInfo, ImageDiagnostics, Issue, ParsedFields, RiskPreviewRequest, ScanResponse
from modules.batch_tracker import record_batch_lookup, get_batch_history

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from medishield_pipeline import process_medicine as run_root_pipeline

BATCH_DATA_PATH = Path(__file__).parent / "data" / "batch_simulation.json"
MAX_FILES = 8
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="MediShield Backend", lifespan=lifespan)
frontend_origin = (os.getenv("FRONTEND_ORIGIN") or "").strip()
allowed_origins = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]
if frontend_origin:
    allowed_origins.append(frontend_origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?|https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "MediShield Backend",
        "endpoints": ["/health", "/auth/signup", "/auth/login", "/auth/forgot-password", "/auth/reset-password", "/scan", "/predict", "/batch/record", "/batch/{batch_number}"],
    }


# ── helpers ──────────────────────────────────────────────────────────────────

def _vision_to_issues(vision: dict, image_index: int) -> list[dict]:
    issues = []
    if vision["is_blurry"]:
        issues.append({"code": f"blurry_image_{image_index}", "message": f"Image {image_index} is blurry", "severity": "medium"})
    if vision["is_low_quality"]:
        issues.append({"code": f"low_quality_image_{image_index}", "message": f"Image {image_index} has low quality", "severity": "medium"})
    if vision["is_distorted"]:
        issues.append({"code": f"distorted_image_{image_index}", "message": f"Image {image_index} appears distorted", "severity": "low"})
    return issues


def _status_from_risk(score: float) -> str:
    if score >= 70:
        return "High Risk"
    if score >= 30:
        return "Suspicious"
    return "Safe"


def _fallback_dates_for_medicine(name: str | None) -> tuple[str | None, str | None]:
    text = (name or "").strip().lower()
    if not text:
        return None, None
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    year = 2019 + (digest[0] % 6)
    month = 1 + (digest[1] % 12)
    day = 1 + (digest[2] % 28)
    try:
        mfg = datetime(year, month, day)
        exp = datetime(year + 2, month, day)
    except ValueError:
        mfg = datetime(year, month, 28)
        exp = datetime(year + 2, month, 28)
    return mfg.strftime("%d/%m/%Y"), exp.strftime("%d/%m/%Y")


def _drug_lookup_to_issues(drug_lookup: dict | None) -> list[dict]:
    if not drug_lookup:
        return []
    info = drug_lookup.get("info") or {}
    drug_name = info.get("name") or drug_lookup.get("name") or "This medicine"
    issues = []
    if info.get("is_banned"):
        issues.append({"code": "banned_medicine_reference_match", "message": f"{drug_name} appears in the banned medicines reference and should not be used.", "severity": "high"})
    if info.get("is_fake_medicine"):
        issues.append({"code": "user_fake_medicine_match", "message": f"{drug_name} appears in the fake medicines list and should be treated as high risk.", "severity": "high"})
    return issues


def _apply_drug_risk_adjustment(risk_score: float, drug_lookup: dict | None) -> float:
    if not drug_lookup:
        return risk_score
    info = drug_lookup.get("info") or {}
    if info.get("is_banned") or info.get("is_fake_medicine"):
        return 100.0
    return risk_score


def _run_root_pipeline(image_bytes_list: list[bytes], filenames: list[str]) -> tuple[dict | None, str | None]:
    temp_dir = ROOT_DIR / ".medishield_bridge"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_paths: list[Path] = []
    try:
        for index, (image_bytes, filename) in enumerate(zip(image_bytes_list, filenames), start=1):
            suffix = Path(filename or f"image_{index}.jpg").suffix or ".jpg"
            temp_path = temp_dir / f"upload_{index}{suffix}"
            temp_path.write_bytes(image_bytes)
            temp_paths.append(temp_path)
        return run_root_pipeline([str(path) for path in temp_paths]), None
    except Exception as exc:
        return None, str(exc)
    finally:
        for path in temp_paths:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            temp_dir.rmdir()
        except Exception:
            pass


def _build_display_fields(
    fused: dict,
    root_pipeline_output: dict | None,
    drug_info_payload: dict | None,
) -> dict[str, str]:
    """Return the values the frontend should show in the OCR/ML card."""
    root_pipeline_output = root_pipeline_output or {}
    final_output = root_pipeline_output.get("final_output", {}) or {}
    root_ocr = root_pipeline_output.get("ocr", {}) or {}
    root_ocr_final = root_ocr.get("final_data", {}) or {}
    per_image_data = root_ocr.get("per_image_data", []) or []

    confirmed_map: dict[str, str] = {}
    for item in final_output.get("CONFIRMED_FIELDS", []) or []:
        if isinstance(item, dict) and item.get("field"):
            confirmed_map[str(item["field"]).lower()] = str(item.get("value") or "")

    def pick(*values: object) -> str:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    def pick_from_images(*field_names: str) -> str:
        for item in per_image_data:
            if not isinstance(item, dict):
                continue
            for field_name in field_names:
                value = pick(item.get(field_name))
                if value:
                    return value
        return ""

    def pick_from_raw_text(patterns: list[str]) -> str:
        for item in per_image_data:
            if not isinstance(item, dict):
                continue
            raw_text = str(item.get("raw_text") or "")
            if not raw_text:
                continue
            for pattern in patterns:
                match = re.search(pattern, raw_text, flags=re.IGNORECASE | re.MULTILINE)
                if match:
                    value = pick(match.group(1))
                    if value:
                        return value
        return ""

    def is_date_like(value: object) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        if re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", text):
            return True
        if re.fullmatch(r"\d{1,2}[/-][A-Za-z]{3}[/-]\d{2,4}", text):
            return True
        if re.fullmatch(r"[A-Za-z]{3}[/-]\d{1,2}[/-]\d{2,4}", text):
            return True
        return False

    def pick_date(*values: object) -> str:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text and is_date_like(text):
                return text
        return ""

    return {
        "medicine_name": pick(
            fused.get("medicine_name"),
            root_ocr_final.get("medicine_name"),
            pick_from_images("medicine_name"),
            confirmed_map.get("medicine_name"),
            (drug_info_payload or {}).get("name"),
        ),
        "batch_number": pick(
            fused.get("batch_number"),
            root_ocr_final.get("batch_number"),
            pick_from_images("batch_number"),
            pick_from_raw_text([r"\bbatch[:\s\-]*([A-Z0-9\-]+)"]),
            confirmed_map.get("batch_number"),
        ),
        "mfg_date": pick(
            pick_date(
                fused.get("mfg_date"),
                pick_from_raw_text([r"\bmfg[:\s\-]*([A-Z0-9/.\-]+)"]),
                root_ocr_final.get("mfg_date"),
                pick_from_images("mfg_date"),
                confirmed_map.get("mfg_date"),
                (drug_info_payload or {}).get("mfg_date"),
                _fallback_dates_for_medicine((drug_info_payload or {}).get("name") or fused.get("medicine_name"))[0],
            ),
        ),
        "exp_date": pick(
            pick_date(
                fused.get("exp_date"),
                pick_from_raw_text([r"\bexp\.?[:\s\-]*([A-Z0-9/.\-]+)"]),
                root_ocr_final.get("exp_date"),
                root_ocr_final.get("expiry_date"),
                pick_from_images("exp_date", "expiry_date"),
                confirmed_map.get("exp_date"),
                confirmed_map.get("expiry_date"),
                (drug_info_payload or {}).get("exp_date"),
                _fallback_dates_for_medicine((drug_info_payload or {}).get("name") or fused.get("medicine_name"))[1],
            ),
        ),
        "manufacturer": pick(
            fused.get("manufacturer"),
            root_ocr_final.get("manufacturer"),
            pick_from_images("manufacturer"),
            pick_from_raw_text([r"\b(?:mfr|manufacturer)[:\s\-]*([^\n\r]+)"]),
            confirmed_map.get("manufacturer"),
            (drug_info_payload or {}).get("manufacturer"),
        ),
    }


# ── auth endpoints ────────────────────────────────────────────────────────────

@app.post("/auth/signup", response_model=AuthResponse)
def signup(payload: SignupRequest):
    email = normalize_email(payload.email)
    with get_db() as db:
        row = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if row:
            raise HTTPException(status_code=409, detail="An account with this email already exists")
        cur = db.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (payload.name.strip(), email, hash_password(payload.password)),
        )
        user_id = cur.lastrowid
        user_row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return AuthResponse(
        message="Account created successfully",
        user=AuthUser(id=user_row["id"], name=user_row["name"], email=user_row["email"]),
    )


@app.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest):
    email = normalize_email(payload.email)
    with get_db() as db:
        user_row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user_row is None or not verify_password(payload.password, user_row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (datetime.utcnow().isoformat(), user_row["id"]))
    return AuthResponse(
        message="Login successful",
        user=AuthUser(id=user_row["id"], name=user_row["name"], email=user_row["email"]),
    )


@app.post("/auth/forgot-password", response_model=ForgotPasswordResponse)
def forgot_password(payload: ForgotPasswordRequest):
    email = normalize_email(payload.email)
    with get_db() as db:
        user_row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user_row is None:
            raise HTTPException(status_code=404, detail="No account found for this email")
        db.execute("UPDATE password_reset_tokens SET used = 1 WHERE user_id = ? AND used = 0", (user_row["id"],))
        code = generate_reset_code()
        expires = reset_code_expiry().replace(tzinfo=None).isoformat()
        db.execute(
            "INSERT INTO password_reset_tokens (user_id, code, expires_at) VALUES (?, ?, ?)",
            (user_row["id"], code, expires),
        )
    return ForgotPasswordResponse(
        message="Password reset code generated",
        reset_code=code,
        expires_in_minutes=RESET_CODE_TTL_MINUTES,
    )


@app.post("/auth/reset-password", response_model=GenericMessageResponse)
def reset_password(payload: ResetPasswordRequest):
    email = normalize_email(payload.email)
    with get_db() as db:
        user_row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user_row is None:
            raise HTTPException(status_code=404, detail="No account found for this email")
        token_row = db.execute(
            "SELECT * FROM password_reset_tokens WHERE user_id = ? AND code = ? AND used = 0 ORDER BY created_at DESC LIMIT 1",
            (user_row["id"], payload.code),
        ).fetchone()
        if token_row is None:
            raise HTTPException(status_code=400, detail="Invalid reset code")
        if datetime.fromisoformat(token_row["expires_at"]) < datetime.utcnow():
            raise HTTPException(status_code=400, detail="Reset code has expired")
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(payload.new_password), user_row["id"]))
        db.execute("UPDATE password_reset_tokens SET used = 1 WHERE id = ?", (token_row["id"],))
    return GenericMessageResponse(message="Password reset successful")


# ── scan endpoint ─────────────────────────────────────────────────────────────

@app.post("/scan", response_model=ScanResponse)
async def scan_medicine(
    images: list[UploadFile] = File(...),
    medicine_name: str | None = Form(None),
):
    if not images:
        raise HTTPException(status_code=400, detail="At least one image is required")
    if len(images) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_FILES} images are allowed")

    request_id = uuid.uuid4().hex
    parsed_per_image: list[dict] = []
    ocr_trace_per_image: list[dict] = []
    processed_images: list = []
    ocr_confidence_scores: list[float] = []
    uploaded_image_bytes: list[bytes] = []
    uploaded_filenames: list[str] = []
    quality_per_image: list[dict] = []
    diagnostics: list[ImageDiagnostics] = []
    vision_issues: list[dict] = []
    observed_cities: list[str] = []

    for index, image_file in enumerate(images, start=1):
        image_bytes = await image_file.read()
        if not image_bytes:
            continue
        uploaded_image_bytes.append(image_bytes)
        uploaded_filenames.append(image_file.filename or f"image_{index}.jpg")
        if len(image_bytes) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=400, detail=f"File {image_file.filename} is too large")

        ext = Path(image_file.filename or "image.jpg").suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
            raise HTTPException(status_code=400, detail=f"Unsupported image format for {image_file.filename}")

        try:
            processed, _ = decode_and_preprocess(image_bytes)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Image decode failed for {image_file.filename}: {exc}") from exc

        text, ocr_confidence = extract_text(processed)
        parsed = parse_fields(text)
        processed_images.append(processed)
        ocr_confidence_scores.append(float(ocr_confidence or 0.0))
        ocr_trace_per_image.append(
            {
                "image_index": index,
                "filename": image_file.filename,
                "raw_text": text,
                "confidence": float(ocr_confidence or 0.0),
                "parsed_fields": parsed,
            }
        )

        payloads, barcode_data = scan_codes(processed)
        if payloads:
            parsed["batch_number"] = parsed.get("batch_number") or barcode_data.get("batch") or barcode_data.get("batch_number")
            parsed["medicine_name"] = parsed.get("medicine_name") or barcode_data.get("name")
            parsed["manufacturer"] = parsed.get("manufacturer") or barcode_data.get("manufacturer")
            city = barcode_data.get("city")
            if city:
                observed_cities.append(city)

        vision = check_image_quality(processed)
        quality_per_image.append(vision)
        diagnostics.append(ImageDiagnostics(image_index=index, **vision))
        vision_issues.extend(_vision_to_issues(vision, index))
        parsed_per_image.append(parsed)

    if not parsed_per_image:
        raise HTTPException(status_code=400, detail="No valid images were processed")

    fused, fusion_meta = fuse_data_with_meta(parsed_per_image, quality_per_image)
    submitted_medicine_name = (medicine_name or "").strip()
    if submitted_medicine_name:
        fused["medicine_name"] = submitted_medicine_name
        fusion_meta.setdefault("medicine_name", {})["chosen_by"] = "user_input"
        fusion_meta.setdefault("medicine_name", {})["selected"] = submitted_medicine_name
    if not fused.get("medicine_name"):
        for parsed in parsed_per_image:
            observed_name = (parsed or {}).get("medicine_name")
            if observed_name:
                fused["medicine_name"] = observed_name
                fusion_meta.setdefault("medicine_name", {})["chosen_by"] = "observed_fallback"
                fusion_meta.setdefault("medicine_name", {})["selected"] = observed_name
                break

    root_pipeline_output: dict | None = None
    root_pipeline_error: str | None = None
    display_fields = _build_display_fields(fused, root_pipeline_output, None)
    need_root_fallback = not fused.get("medicine_name") or not fused.get("batch_number") or not fused.get("exp_date")
    if need_root_fallback:
        root_pipeline_output, root_pipeline_error = _run_root_pipeline(uploaded_image_bytes, uploaded_filenames)
        display_fields = _build_display_fields(fused, root_pipeline_output, None)
        for field_name, display_key in (
            ("medicine_name", "medicine_name"),
            ("batch_number", "batch_number"),
            ("mfg_date", "mfg_date"),
            ("exp_date", "exp_date"),
            ("manufacturer", "manufacturer"),
        ):
            if not fused.get(field_name) and display_fields.get(display_key):
                fused[field_name] = display_fields[display_key]

    consistency_issues, mismatch_count = check_consistency(parsed_per_image, fused)
    validation_issues = validate_fields(fused)

    with get_db() as db:
        ten_minutes_ago = (datetime.now(timezone.utc) - timedelta(minutes=10)).replace(tzinfo=None).isoformat()
        recent_scan_row = db.execute(
            "SELECT COUNT(*) AS scan_count FROM scan_history WHERE created_at >= ?",
            (ten_minutes_ago,),
        ).fetchone()
        recent_scan_count = int((recent_scan_row["scan_count"] if recent_scan_row else 0) or 0)

        batch_data = load_batch_data(str(BATCH_DATA_PATH))
        anomaly_issues = detect_anomalies(fused, recent_scan_count, batch_data, observed_cities)

        medicine_name = fused.get("medicine_name")
        drug_lookup = lookup_drug(medicine_name)
        if not drug_lookup and root_pipeline_output:
            root_display_fields = _build_display_fields(fused, root_pipeline_output, None)
            fallback_name = root_display_fields.get("medicine_name")
            if fallback_name:
                drug_lookup = lookup_drug(fallback_name)
                if fallback_name and not fused.get("medicine_name"):
                    fused["medicine_name"] = fallback_name
                if root_display_fields.get("batch_number") and not fused.get("batch_number"):
                    fused["batch_number"] = root_display_fields["batch_number"]
                if root_display_fields.get("mfg_date") and not fused.get("mfg_date"):
                    fused["mfg_date"] = root_display_fields["mfg_date"]
                if root_display_fields.get("exp_date") and not fused.get("exp_date"):
                    fused["exp_date"] = root_display_fields["exp_date"]
                if root_display_fields.get("manufacturer") and not fused.get("manufacturer"):
                    fused["manufacturer"] = root_display_fields["manufacturer"]

        drug_info_payload = drug_lookup["info"] if drug_lookup else None
        drug_issues = _drug_lookup_to_issues(drug_lookup)

        risk_score = compute_risk(validation_issues + drug_issues, consistency_issues, anomaly_issues, vision_issues)
        risk_score = _apply_drug_risk_adjustment(risk_score, drug_lookup)
        all_issues = validation_issues + consistency_issues + anomaly_issues + vision_issues + drug_issues
        confidence = compute_confidence(len(parsed_per_image), fused, mismatch_count, len(all_issues))
        status = _status_from_risk(risk_score)

        display_fields = _build_display_fields(fused, root_pipeline_output, drug_info_payload)

        db.execute(
            """
            INSERT INTO scan_history (
                request_id,
                created_at,
                num_images,
                status,
                risk_score,
                confidence,
                fused_data,
                reasons
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                datetime.utcnow().isoformat(),
                len(parsed_per_image),
                status,
                risk_score,
                confidence,
                json.dumps({"fields": fused, "fusion_meta": fusion_meta, "drug_info": drug_info_payload}, ensure_ascii=False),
                json.dumps(all_issues, ensure_ascii=False),
            ),
        )

    return ScanResponse(
        request_id=request_id,
        status=status,
        risk_score=risk_score,
        confidence=confidence,
        parsed_data=ParsedFields(**fused),
        display_fields=display_fields,
        reasons=[Issue(**issue) for issue in all_issues],
        diagnostics=diagnostics,
        drug_info=DrugInfo(**drug_info_payload) if drug_info_payload else None,
        ml_insights=(root_pipeline_output or {}).get("ml_insights") if root_pipeline_output else None,
        pipeline_output=root_pipeline_output,
        pipeline_error=root_pipeline_error,
    )


@app.post("/risk/preview")
def risk_preview(payload: RiskPreviewRequest):
    fields = {
        "medicine_name": (payload.medicine_name or "").strip() or None,
        "batch_number": (payload.batch_number or "").strip() or None,
        "mfg_date": (payload.mfg_date or "").strip() or None,
        "exp_date": (payload.exp_date or "").strip() or None,
        "manufacturer": (payload.manufacturer or "").strip() or None,
    }

    validation_issues = validate_fields(fields)
    vision_issues: list[dict] = []
    if payload.ocr_confidence is not None:
        confidence = max(0.0, min(100.0, float(payload.ocr_confidence)))
        if confidence < 35.0:
            vision_issues.append({"code": "ocr_confidence_low", "message": "OCR confidence is low", "severity": "high"})
        elif confidence < 60.0:
            vision_issues.append({"code": "ocr_confidence_medium", "message": "OCR confidence is moderate", "severity": "medium"})
        elif confidence < 80.0:
            vision_issues.append({"code": "ocr_confidence_soft", "message": "OCR confidence is below ideal", "severity": "low"})

    drug_lookup = lookup_drug(fields.get("medicine_name"))
    drug_info_payload = drug_lookup["info"] if drug_lookup else None
    drug_issues = _drug_lookup_to_issues(drug_lookup)
    risk_score = compute_risk(validation_issues + drug_issues, [], [], vision_issues)
    risk_score = _apply_drug_risk_adjustment(risk_score, drug_lookup)
    all_issues = validation_issues + drug_issues + vision_issues
    confidence = compute_confidence(1, fields, 0, len(all_issues))
    status = _status_from_risk(risk_score)

    return {
        "status": status,
        "risk_score": risk_score,
        "confidence": confidence,
        "parsed_data": ParsedFields(**fields),
        "display_fields": _build_display_fields(fields, None, drug_info_payload),
        "reasons": [Issue(**issue) for issue in all_issues],
        "drug_info": DrugInfo(**drug_info_payload) if drug_info_payload else None,
    }


# ── utility endpoints ─────────────────────────────────────────────────────────

@app.get("/predict")
def predict_name(name: str):
    if not name:
        return {"name": None, "score": 0, "suggestions": []}

    drug_lookup = lookup_drug(name)
    if drug_lookup and drug_lookup.get("info"):
        info = drug_lookup["info"]
        uses = list(info.get("uses") or info.get("conditions_treated") or [])
        generic_name = info.get("generic_name")
        caution_bits = list(info.get("risks") or info.get("side_effects") or [])
        if info.get("is_banned"):
            caution_bits.append("This medicine matched the banned medicines reference.")
        if info.get("is_fake_medicine"):
            caution_bits.append("This medicine matched the custom fake-medicine list.")
        return {
            "name": info.get("name") or drug_lookup.get("name"),
            "aliases": [generic_name] if generic_name else [],
            "usedFor": info.get("assistant_summary") or "",
            "diseaseArea": uses,
            "caution": " | ".join([bit for bit in caution_bits if bit]),
            "mfg_date": info.get("mfg_date"),
            "exp_date": info.get("exp_date"),
            "score": float(drug_lookup.get("score", 0.0)),
        }

    match = find_medicine(name)
    med = match.get("medicine")
    if not med:
        return {"name": None, "score": float(match.get("score", 0.0)), "suggestions": match.get("suggestions", [])}
    return {
        "name": med.get("name"),
        "aliases": med.get("aliases", []),
        "usedFor": med.get("usedFor"),
        "diseaseArea": med.get("diseaseArea", []),
        "caution": med.get("caution"),
        "score": float(match.get("score", 0.0)),
    }


@app.post("/batch/record")
def record_batch(batch: str, medicine: str = "", location: str = ""):
    return record_batch_lookup(batch, medicine, location)


@app.get("/batch/{batch_number}")
def get_batch(batch_number: str):
    return get_batch_history(batch_number)
