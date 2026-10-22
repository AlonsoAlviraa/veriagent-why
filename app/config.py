"""Runtime config from environment. Secrets are read from env only and never logged."""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def sample_mode() -> bool:
    return env("SAMPLE_MODE", "true").lower() in ("1", "true", "yes")


def provider() -> str:
    """LLM_PROVIDER = nightshift | nvidia | sample. SAMPLE_MODE forces sample."""
    if sample_mode():
        return "sample"
    return env("LLM_PROVIDER", "nightshift")


CAPS = {"evaluator_rounds": 3, "claim_gate_rounds": 2, "retriever_retries": 2}
TIMEOUTS = {"model_s": 60, "zetaris_s": 20, "run_s": 480}


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
