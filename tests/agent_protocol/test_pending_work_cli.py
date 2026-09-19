"""Tests for the local-only pending-work agent protocol CLI."""

import importlib.machinery
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest


SCRIPT = Path(__file__).parents[2] / "scripts" / "pending-work"
LOADER = importlib.machinery.SourceFileLoader("pending_work_cli", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
cli = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(cli)


@pytest.mark.parametrize("value", ["https://example.com/api", "http://192.168.1.3/api", "http://localhost/api?token=x", "http://user@localhost/api"])
def test_api_base_rejects_non_local_or_credentialed_urls(value):
    with pytest.raises(cli.CliError):
        cli.local_api_base(value)


def test_list_calls_loopback_api_and_decodes_json():
    class Response:
        def read(self):
            return b'[{"id":"item-1"}]'

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    with patch.object(cli, "urlopen", return_value=Response()) as urlopen_mock:
        result = cli.request_json("http://127.0.0.1:8787/api", "GET", "/work-items?status=pending")

    assert result == [{"id": "item-1"}]
    request = urlopen_mock.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:8787/api/work-items?status=pending"
    assert request.method == "GET"


def test_request_adds_a_bearer_token_only_when_given():
    class Response:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    with patch.object(cli, "urlopen", return_value=Response()) as urlopen_mock:
        cli.request_json("http://localhost:8787/api", "GET", "/work-items", api_token="local-app-token")

    request = urlopen_mock.call_args.args[0]
    assert request.get_header("Authorization") == "Bearer local-app-token"


def test_private_commands_require_a_local_app_token(monkeypatch):
    monkeypatch.delenv("PENDING_WORK_API_TOKEN", raising=False)
    with pytest.raises(cli.CliError, match="PENDING_WORK_API_TOKEN"):
        cli.local_api_token("context")
    assert cli.local_api_token("health") is None


def test_dispatch_serializes_a_bounded_request(monkeypatch):
    captured = {}
    monkeypatch.setenv("PENDING_WORK_API_TOKEN", "local-app-token")

    def fake_request(api_base, method, path, payload=None, api_token=None):
        captured.update(api_base=api_base, method=method, path=path, payload=payload, api_token=api_token)
        return {"id": "dispatch-1"}

    with patch.object(cli, "request_json", side_effect=fake_request):
        code = cli.main(["dispatch", "00000000-0000-0000-0000-000000000001", "--client", "codex", "--instruction", "Draft a bounded plan."])

    assert code == 0
    assert captured == {
        "api_base": cli.DEFAULT_API_BASE,
        "method": "POST",
        "path": "/work-items/00000000-0000-0000-0000-000000000001/dispatch",
        "payload": {"client": "codex", "instruction": "Draft a bounded plan."},
        "api_token": "local-app-token",
    }


def test_cli_error_is_json(capsys):
    code = cli.main(["--api-base", "https://example.com/api", "health"])
    assert code == 1
    assert "loopback" in json.loads(capsys.readouterr().out)["error"]


def test_context_rejects_a_non_uuid_id(capsys, monkeypatch):
    monkeypatch.setenv("PENDING_WORK_API_TOKEN", "local-app-token")
    assert cli.main(["context", "../../health"]) == 1
    assert "UUID" in json.loads(capsys.readouterr().out)["error"]


def test_source_kind_choices_no_longer_offer_the_removed_teams_kind():
    """argparse would accept a kind the API now answers 422 to.

    The CLI holds its own copy of the list because it is a standalone stdlib
    script with no import path to ``app.models``, so nothing but this test keeps
    the two in step.
    """
    parser = cli.build_parser()

    for argv in (["sources", "--kind", "teams_message"], ["propose", "--source-kind", "teams_message"]):
        with pytest.raises(SystemExit):
            parser.parse_args(argv)

    assert parser.parse_args(["sources", "--kind", "outlook_email"]).kind == "outlook_email"
    assert parser.parse_args(["propose", "--source-kind", "manual"]).source_kind == "manual"
