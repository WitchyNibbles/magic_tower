from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.config import Settings
from app.integrations.graph import GraphClient
from app.services.crypto import EncryptedTokenStore, generate_encryption_key
from app.services.graph import fetch_signals
from app.services.oauth import authorization_url, verify_state
from app.services.sync import sync


def test_token_store_encrypts_and_tamper_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "token"
    store = EncryptedTokenStore(path, generate_encryption_key())
    store.save({"access_token": "not-in-cleartext"})
    assert b"not-in-cleartext" not in path.read_bytes()
    path.write_bytes(b"tampered")
    try:
        store.load()
    except Exception as error:
        assert "cannot be decrypted" in str(error)
    else:
        raise AssertionError("tampered token was accepted")


def test_oauth_uses_pkce_and_one_time_state(tmp_path: Path) -> None:
    key = generate_encryption_key()
    settings = Settings(
        microsoft_tenant_id="tenant",
        microsoft_client_id="client",
        microsoft_client_secret="client-secret",
        microsoft_target_user_id="oid",
        app_encryption_key=key,
        oauth_state_store_path=tmp_path / "state",
    )
    query = parse_qs(urlparse(authorization_url(settings)).query)
    assert query["code_challenge_method"] == ["S256"]
    assert verify_state(settings, query["state"][0])
    try:
        verify_state(settings, query["state"][0])
    except Exception:
        pass
    else:
        raise AssertionError("state replay was accepted")


def test_sync_uses_me_and_deduplicates_mocked_messages(tmp_path: Path) -> None:
    key = generate_encryption_key()
    settings = Settings(
        microsoft_tenant_id="tenant", microsoft_client_id="client", microsoft_client_secret="secret",
        microsoft_target_user_id="expected-oid", app_encryption_key=key,
        token_store_path=tmp_path / "tokens",
    )
    EncryptedTokenStore(settings.token_store_path, key).save({"access_token": "token"})
    calls: list[str] = []
    def transport(method: str, url: str, headers: dict[str, str], payload: object) -> dict:
        calls.append(url)
        if "/me?$select=" in url:
            return {"id": "expected-oid"}
        if "/me/mailFolders/" in url:
            return {"value": [{"id": "m1", "subject": "Do task", "bodyPreview": "please", "webLink": "https://x"}, {"id": "m1", "subject": "duplicate"}]}
        raise AssertionError(url)
    result = sync(settings, client=GraphClient("token", transport))
    assert result["count"] == 1
    assert all("/users/" not in call for call in calls)


def test_graph_client_has_no_chat_fetch_path() -> None:
    """The Graph chat fetch path is gone, not merely unused by ``fetch_signals``."""
    assert not hasattr(GraphClient, "chat_messages")


def test_graph_scopes_no_longer_request_chat_read() -> None:
    """Chat.Read asks the owner for a consent the Teams source no longer needs.

    Requesting a scope nothing uses asks for admin consent on a mailbox where it
    cannot be granted -- exactly the reason the Teams source was removed -- so
    this pins the OAuth scope list, not just the connector code.
    """
    from app.services.oauth import GRAPH_SCOPES

    assert "Chat.Read" not in GRAPH_SCOPES
    assert GRAPH_SCOPES == ("offline_access", "User.Read", "Mail.Read")
