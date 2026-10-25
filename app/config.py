"""Runtime config from environment. Secrets are read from env only and never logged."""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def zetaris_configured() -> bool:
    """Zetaris is the default data path whenever it is configured (ZETARIS_BACKEND=zetaris or a JDBC URL)."""
    return env("ZETARIS_BACKEND").lower() == "zetaris" or bool(env("ZETARIS_JDBC_URL"))


def sample_mode() -> bool:
    """SAMPLE_MODE is the explicit offline fallback (rules: "fallback/sample mode").
    Set explicitly: honoured. Unset: false when Zetaris is configured, else true (fallback, announced
    on stderr and in the trace/memo as "SAMPLE MODE: no Zetaris, synthetic DuckDB snapshot")."""
    v = env("SAMPLE_MODE").lower()
    if v:
        return v in ("1", "true", "yes")
    return not zetaris_configured()


def sample_mode_reason() -> str:
    if env("SAMPLE_MODE"):
        return "SAMPLE_MODE set explicitly"
    return "Zetaris not configured (no ZETARIS_BACKEND=zetaris / ZETARIS_JDBC_URL): automatic fallback"


def log_dir() -> Path:
    """Run artefacts directory. VA_LOG_DIR overrides logs/ (the test suite points it at a temp dir)."""
    return Path(env("VA_LOG_DIR")) if env("VA_LOG_DIR") else ROOT / "logs"


def meterless_required() -> bool:
    """METERLESS_REQUIRED=1: fail loudly if the Meterless bridge (node) is unavailable instead of falling back."""
    return env("METERLESS_REQUIRED").lower() in ("1", "true", "yes")


def provider() -> str:
    """LLM_PROVIDER = nightshift | nvidia | sample. SAMPLE_MODE forces sample."""
    if sample_mode():
        return "sample"
    return env("LLM_PROVIDER", "nightshift")


CAPS = {"evaluator_rounds": 3, "claim_gate_rounds": 2, "retriever_retries": 2}
TIMEOUTS = {"model_s": int(os.environ.get("MODEL_TIMEOUT_S") or 60), "zetaris_s": 20, "run_s": 480}


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Read KEY=VALUE lines from .env (gitignored); exported variables win. Never prints values."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v and k.strip() not in os.environ:
                os.environ[k.strip()] = v
