from functools import lru_cache

from pathlib import Path
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite:////data/workboard.db"
    microsoft_tenant_id: str | None = None
    microsoft_client_id: str | None = None
    microsoft_client_secret: SecretStr | None = None
    microsoft_target_user_id: str | None = None
    microsoft_redirect_uri: str = "http://localhost:8787/api/auth/callback"
    app_encryption_key: SecretStr | None = None
    # Distinct from Graph/OAuth secrets. Installed local agents use this only
    # as ``Authorization: Bearer ...`` when accessing the agent protocol.
    local_api_token: SecretStr | None = None
    # Addresses whose mail the promotion heuristic treats as work whatever its rules
    # decide, comma-separated. Tenant-specific by nature -- an internal robot one
    # owner acts on is noise to the next -- so it is configuration, not a constant.
    promotion_allowlisted_senders: str = ""
    local_session_ttl_seconds: int = 28_800
    max_request_body_bytes: int = 1_048_576
    token_store_path: Path = Path("/data/workboard-graph-tokens.json")
    oauth_state_store_path: Path = Path("/data/workboard-oauth-state.json")

    @field_validator("microsoft_redirect_uri")
    @classmethod
    def redirect_uri_is_safe(cls, value: str) -> str:
        """Only allow a local development callback over HTTP."""
        parsed = urlparse(value)
        if parsed.path != "/api/auth/callback":
            raise ValueError("MICROSOFT_REDIRECT_URI must end in /api/auth/callback")
        if parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
            return value
        raise ValueError("MICROSOFT_REDIRECT_URI must use HTTPS or localhost HTTP")

    @field_validator("microsoft_tenant_id", "microsoft_client_id", "microsoft_target_user_id")
    @classmethod
    def graph_identifiers_are_not_urls(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or any(char in value for char in "/\\?&#")):
            raise ValueError("Microsoft identifiers must be plain tenant, client, or object IDs")
        return value

    def allowlisted_senders(self) -> tuple[str, ...]:
        """The configured allowlist as addresses, with blanks from a trailing comma dropped."""
        return tuple(address.strip() for address in self.promotion_allowlisted_senders.split(",") if address.strip())

    def graph_configuration_errors(self) -> list[str]:
        required = {
            "MICROSOFT_TENANT_ID": self.microsoft_tenant_id,
            "MICROSOFT_CLIENT_ID": self.microsoft_client_id,
            "MICROSOFT_CLIENT_SECRET": self.microsoft_client_secret,
            "MICROSOFT_TARGET_USER_ID": self.microsoft_target_user_id,
            "APP_ENCRYPTION_KEY": self.app_encryption_key,
        }
        def present(value: str | SecretStr | None) -> bool:
            if isinstance(value, SecretStr):
                return bool(value.get_secret_value().strip())
            return bool(value and value.strip())
        return [name for name, value in required.items() if not present(value)]


@lru_cache
def get_settings() -> Settings:
    return Settings()
