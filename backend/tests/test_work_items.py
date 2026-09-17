from fastapi.testclient import TestClient

from app.main import app


def test_work_item_evidence_context_and_dispatch_round_trip():
    with TestClient(app) as client:
        token_headers = {"Authorization": "Bearer test-local-agent-token"}
        created = client.post(
            "/api/work-items",
            json={
                "title": "Reply to the customer",
                "summary": "Confirm the delivery date.",
                "source_kind": "outlook_email",
                "source_external_id": "message-123",
                "evidence": [{"source_kind": "outlook_email", "external_id": "message-123", "excerpt": "Can you confirm?"}],
            }, headers=token_headers,
        )
        assert created.status_code == 201
        work_item = created.json()
        assert work_item["evidence"][0]["external_id"] == "message-123"

        context = client.post("/api/agent-context", json={"work_item_id": work_item["id"], "client": "codex"}, headers=token_headers)
        assert context.status_code == 200
        assert "Can you confirm?" in context.json()["prompt"]

        dispatch = client.post(
            "/api/agent-dispatches",
            json={"work_item_id": work_item["id"], "client": "codex", "instruction": "Draft a concise reply."}, headers=token_headers,
        )
        assert dispatch.status_code == 201
        assert dispatch.json()["status"] == "queued"


def test_validation_and_duplicate_source_external_id_are_rejected():
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-local-agent-token"}
        invalid = client.post("/api/work-items", json={"title": "", "source_kind": "manual", "unexpected": True}, headers=headers)
        assert invalid.status_code == 422

        payload = {"title": "Unique source", "source_kind": "teams_message", "source_external_id": "chat-unique"}
        assert client.post("/api/work-items", json=payload, headers=headers).status_code == 201
        assert client.post("/api/work-items", json=payload, headers=headers).status_code == 409
