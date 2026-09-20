"""What a run needs: both API keys, the loop's knobs, and the input files."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

# ── Loop defaults (override under [polish] in secrets.toml) ───────────────────

DEFAULT_MAX_ITERATIONS = 10
DEFAULT_MIN_IMPROVEMENT = 0.02
DEFAULT_TARGET_SCORE = 0.90
DEFAULT_PATIENCE = 2  # non-improving rounds tolerated before the loop stops
DEFAULT_REQUEST_TIMEOUT = 120.0  # seconds to wait on one model call
DEFAULT_MAX_RETRIES = 2  # retries per call when the provider fails or times out

# ── Report server defaults ────────────────────────────────────────────────────

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


@dataclass(frozen=True)
class Settings:
    """Everything configurable about a run, resolved from ``secrets.toml``."""

    typesafe_api_key: str
    typesafe_model: str | None
    # Writer LLM — any OpenAI-compatible provider ([writer] section in secrets.toml,
    # or [deepseek] for backward compatibility)
    writer_api_key: str
    writer_model: str
    writer_base_url: str
    max_iterations: int
    min_improvement: float
    target_score: float
    patience: int
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    # Budget caps (None = unlimited)
    max_tokens: int | None = None
    max_seconds: float | None = None
    # Privacy flags
    redact: bool = False
    no_store: bool = False
    # Structured JSON logging
    log_json: bool = False

    @property
    def reviewer_label(self) -> str:
        return self.typesafe_model or "account default (jev-latest)"

    @property
    def writer_label(self) -> str:
        return self.writer_model

    def typesafe_client_kwargs(self) -> dict[str, str | float]:
        kwargs: dict[str, str | float] = {
            "api_key": self.typesafe_api_key,
            "timeout": self.request_timeout,
        }
        if self.typesafe_model:
            kwargs["model"] = self.typesafe_model
        return kwargs


def load_settings(path: Path = Path("secrets.toml")) -> Settings:
    """Read both API keys and the loop's knobs from ``secrets.toml``.

    The writer LLM is configured under ``[writer]``; ``[deepseek]`` is accepted as a
    backward-compatible alias so existing config files keep working.
    """
    try:
        secrets = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise SystemExit(
            f"{path} not found — create it with a [typesafe] section and a [writer] section"
        )
    if "typesafe" not in secrets or not secrets["typesafe"].get("api_key"):
        raise SystemExit(f"[typesafe] api_key missing in {path}")

    # Accept [writer] or legacy [deepseek]
    writer_section = secrets.get("writer") or secrets.get("deepseek")
    if not writer_section or not writer_section.get("api_key"):
        raise SystemExit(f"[writer] api_key missing in {path} (or legacy [deepseek])")

    polish = secrets.get("polish", {})
    return Settings(
        typesafe_api_key=secrets["typesafe"]["api_key"],
        typesafe_model=secrets["typesafe"].get("model"),
        writer_api_key=writer_section["api_key"],
        writer_model=writer_section.get("model", "deepseek-chat"),
        writer_base_url=writer_section.get("base_url", "https://api.deepseek.com"),
        max_iterations=int(polish.get("max_iterations", DEFAULT_MAX_ITERATIONS)),
        min_improvement=float(polish.get("min_improvement", DEFAULT_MIN_IMPROVEMENT)),
        target_score=float(polish.get("target_score", DEFAULT_TARGET_SCORE)),
        patience=int(polish.get("patience", DEFAULT_PATIENCE)),
        request_timeout=float(polish.get("request_timeout", DEFAULT_REQUEST_TIMEOUT)),
        max_retries=int(polish.get("max_retries", DEFAULT_MAX_RETRIES)),
    )


def read_input(path: Path) -> str:
    """Read one input file, failing with a message worth reading when it is missing."""
    try:
        text = path.read_text().strip()
    except FileNotFoundError:
        raise SystemExit(f"{path} not found")
    if not text:
        raise SystemExit(f"{path} is empty")
    return text
