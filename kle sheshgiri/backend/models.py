"""
Plain dataclass models — replaces SQLAlchemy ORM models.
No external dependencies.
"""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class User:
    id: int | None
    name: str
    email: str
    password_hash: str
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_login_at: str | None = None
    is_active: bool = True


@dataclass
class ScanHistory:
    request_id: str
    num_images: int
    status: str
    risk_score: float
    confidence: float
    fused_data: dict
    reasons: list
    id: int | None = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class PasswordResetToken:
    user_id: int
    code: str
    expires_at: str
    id: int | None = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    used: bool = False
