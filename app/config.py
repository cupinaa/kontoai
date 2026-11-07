"""Application settings, read from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

DEFAULT_MODEL = "gemini-3.6-flash"
DEFAULT_REVIEW_THRESHOLD = 0.75


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str | None
    gemini_model: str
    review_threshold: float
    db_path: Path
    chart_path: Path
    rules_path: Path
    analytic_plan_path: Path = DATA_DIR / "analiticki_plan.json"


def _resolve(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else BASE_DIR / path


def get_settings() -> Settings:
    """Build settings from the environment. `.env` never overrides real environment variables."""
    load_dotenv(BASE_DIR / ".env", override=False)
    api_key = os.getenv("GEMINI_API_KEY", "").strip() or None
    return Settings(
        gemini_api_key=api_key,
        gemini_model=os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_MODEL,
        review_threshold=float(os.getenv("REVIEW_THRESHOLD", DEFAULT_REVIEW_THRESHOLD)),
        db_path=_resolve(os.getenv("KONTOAI_DB_PATH", "kontoai.db")),
        chart_path=_resolve(os.getenv("KONTOAI_CHART_PATH", str(DATA_DIR / "kontni_okvir.json"))),
        rules_path=_resolve(os.getenv("KONTOAI_RULES_PATH", str(DATA_DIR / "rules.json"))),
        analytic_plan_path=_resolve(
            os.getenv("KONTOAI_ANALYTIC_PLAN_PATH", str(DATA_DIR / "analiticki_plan.json"))
        ),
    )
