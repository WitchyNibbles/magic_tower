from fastapi.testclient import TestClient

from app.main import app


def test_openapi_document_names_the_product() -> None:
    """``/api/docs`` renders this title, so it is the first thing a reader of the API sees."""
    response = TestClient(app).get("/api/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Magic Tower API"
