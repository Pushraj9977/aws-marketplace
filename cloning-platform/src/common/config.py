"""
config.py — YAML configuration loader with environment variable resolution.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .exceptions import ConfigurationError


class Config:
    """
    Loads and provides access to YAML configuration with env-var override support.

    Environment variables take precedence over YAML values.
    Values in YAML may reference env vars using ${VAR_NAME} syntax.
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        env = os.environ.get("ENVIRONMENT", "prod")
        if config_path is None:
            base = Path(__file__).parent.parent.parent / "infrastructure" / "config"
            config_path = base / f"{env}.yaml"

        self._path = Path(config_path)
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        with open(self._path) as f:
            raw = yaml.safe_load(f) or {}
        return self._resolve_env_vars(raw)

    def _resolve_env_vars(self, obj: Any) -> Any:
        if isinstance(obj, str):
            import re
            def replacer(m: re.Match) -> str:
                key = m.group(1)
                val = os.environ.get(key)
                if val is None:
                    return ""
                return val
            return re.sub(r"\$\{([^}]+)\}", replacer, obj)
        if isinstance(obj, dict):
            return {k: self._resolve_env_vars(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._resolve_env_vars(i) for i in obj]
        return obj

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value by dot-separated key path."""
        keys = key.split(".")
        val = self._data
        for k in keys:
            if not isinstance(val, dict):
                return default
            val = val.get(k, default)
        return val

    # Convenience properties — overridable by environment variables

    @property
    def region(self) -> str:
        return os.environ.get("AWS_DEFAULT_REGION") or self.get("aws.region", "eu-central-1")

    @property
    def account_id(self) -> str:
        return os.environ.get("ACCOUNT_ID") or self.get("aws.account_id", "215116348101")

    @property
    def environment_state_table(self) -> str:
        return os.environ.get("STATE_TABLE") or os.environ.get("ENVIRONMENT_STATE_TABLE") or self.get("dynamodb.environment_state_table", "EnvironmentState")

    @property
    def subscribers_table(self) -> str:
        return os.environ.get("SUBSCRIBERS_TABLE") or self.get("dynamodb.subscribers_table", "MarketplaceSubscribers")

    @property
    def amplify_app_id(self) -> str:
        return os.environ.get("AMPLIFY_APP_ID") or self.get("amplify.app_id", "d246slprgvqfid")

    @property
    def source_env_name(self) -> str:
        return os.environ.get("SOURCE_ENV_NAME") or self.get("cloning.source_env_name", "dev")

    @property
    def report_s3_bucket(self) -> str:
        return os.environ.get("REPORT_S3_BUCKET") or self.get("reports.s3_bucket", "")

    @property
    def notification_topic_arn(self) -> str:
        return os.environ.get("NOTIFICATION_TOPIC_ARN") or self.get("notifications.topic_arn", "")

    @property
    def log_level(self) -> str:
        return os.environ.get("LOG_LEVEL", "INFO").upper()


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Return the singleton Config instance (cached)."""
    return Config()
