from functools import lru_cache

from pathlib import Path
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Optional settings that a documented ``.env`` may list with an empty value to show
# the key exists without committing a secret (``MICROSOFT_TENANT_ID=``). Pydantic
# reads that as the literal string ``""``, not as an absent variable, so every one
# of these has to be normalized to ``None`` before field validation sees it.
_BLANKABLE_OPTIONAL_FIELDS = (
    "microsoft_tenant_id",
    "microsoft_client_id",
    "microsoft_client_secret",
    "microsoft_target_user_id",
    "app_encryption_key",
    "local_api_token",
    "jira_site_url",
    "jira_account_email",
    "jira_api_token",
    "jira_management_project_key",
)


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
    # Jira: optional settings mirroring the Graph ones above. A classic API token
    # authenticates as Basic auth over ``email:token`` against
    # ``https://<site>.atlassian.net`` (not the scoped-token host).
    jira_site_url: str | None = None
    jira_account_email: str | None = None
    jira_api_token: SecretStr | None = None
    # The project key a management view syncs browse-only, without ever
    # promoting its issues into the actionable queue. Optional: absent means no
    # project gets that extra visibility.
    jira_management_project_key: str | None = None
    # Addresses whose mail the promotion heuristic treats as work whatever its rules
    # decide, comma-separated. Tenant-specific by nature -- an internal robot one
    # owner acts on is noise to the next -- so it is configuration, not a constant.
    promotion_allowlisted_senders: str = ""
    local_session_ttl_seconds: int = 28_800
    max_request_body_bytes: int = 1_048_576
    token_store_path: Path = Path("/data/workboard-graph-tokens.json")
    oauth_state_store_path: Path = Path("/data/workboard-oauth-state.json")

    @model_validator(mode="before")
    @classmethod
    def blank_optional_settings_are_absent(cls, data: object) -> object:
        """Treat an empty or whitespace-only value as an unset optional setting.

        Runs before every other validator so a blank ``.env`` entry never reaches
        ``graph_identifiers_are_not_urls`` or the secret fields as the literal
        string ``""`` -- it becomes the same "not configured" state an omitted
        variable already produces.
        """
        if not isinstance(data, dict):
            return data
        cleaned = dict(data)
        for field_name in _BLANKABLE_OPTIONAL_FIELDS:
            value = cleaned.get(field_name)
            if isinstance(value, str) and not value.strip():
                cleaned[field_name] = None
        return cleaned

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

    def jira_configuration_errors(self) -> list[str]:
        """Names of missing or blank core Jira settings, fail-closed.

        The management-project key is a visibility setting (T09), not part of
        the core connection, so it is deliberately excluded here.
        """
        required = {
            "JIRA_SITE_URL": self.jira_site_url,
            "JIRA_ACCOUNT_EMAIL": self.jira_account_email,
            "JIRA_API_TOKEN": self.jira_api_token,
        }
        def present(value: str | SecretStr | None) -> bool:
            if isinstance(value, SecretStr):
                return bool(value.get_secret_value().strip())
            return bool(value and value.strip())
        return [name for name, value in required.items() if not present(value)]


@lru_cache
def get_settings() -> Settings:
    return Settings()
