from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Any


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = BASE_DIR / "data"
DEFAULT_EXPORTS_DIR = BASE_DIR / "exports"


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _int_from_env(value: str | None, default: int) -> int:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class AppConfig:
    app_env: str
    auth_enabled: bool
    username: str
    password: str
    password_hash: str
    secret_key: str
    debug_exports: bool
    data_dir: Path
    exports_dir: Path
    max_upload_mb: int


def load_app_config(env: Mapping[str, str] | None = None, *, validate: bool = False) -> AppConfig:
    values = env or os.environ
    config = AppConfig(
        app_env=values.get("APP_ENV", "local"),
        auth_enabled=_truthy(values.get("APP_AUTH_ENABLED")),
        username=values.get("APP_USERNAME", "admin"),
        password=values.get("APP_PASSWORD", ""),
        password_hash=values.get("APP_PASSWORD_HASH", ""),
        secret_key=values.get("APP_SECRET_KEY", ""),
        debug_exports=_truthy(values.get("BUDGET_DEBUG_EXPORTS")),
        data_dir=Path(values.get("DATA_DIR", str(DEFAULT_DATA_DIR))).expanduser(),
        exports_dir=Path(values.get("EXPORTS_DIR", str(DEFAULT_EXPORTS_DIR))).expanduser(),
        max_upload_mb=max(1, _int_from_env(values.get("MAX_UPLOAD_MB"), 100)),
    )
    if validate:
        validate_app_config(config)
    return config


def validate_app_config(config: AppConfig) -> None:
    if config.auth_enabled and not (config.password or config.password_hash):
        raise ValueError("APP_AUTH_ENABLED=1 требует APP_PASSWORD или APP_PASSWORD_HASH.")


def get_app_config(*, validate: bool = False) -> AppConfig:
    return load_app_config(validate=validate)


def hash_password(password: str) -> str:
    return hashlib.sha256((password or "").encode("utf-8")).hexdigest()


def verify_password(password: str, config: AppConfig) -> bool:
    if config.password_hash:
        return hmac.compare_digest(hash_password(password), config.password_hash)
    return hmac.compare_digest(password or "", config.password or "")


def debug_exports_enabled() -> bool:
    return get_app_config().debug_exports


def uploaded_file_size_bytes(uploaded_file: Any) -> int:
    size = getattr(uploaded_file, "size", None)
    if size is not None:
        return int(size)
    if hasattr(uploaded_file, "getbuffer"):
        return len(uploaded_file.getbuffer())
    if hasattr(uploaded_file, "getvalue"):
        return len(uploaded_file.getvalue())
    return 0


def upload_within_limit(uploaded_file: Any, config: AppConfig | None = None) -> tuple[bool, int, int]:
    active_config = config or get_app_config()
    size_bytes = uploaded_file_size_bytes(uploaded_file)
    limit_bytes = active_config.max_upload_mb * 1024 * 1024
    return size_bytes <= limit_bytes, size_bytes, limit_bytes
