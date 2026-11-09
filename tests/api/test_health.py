import httpx


def test_health_reports_ok(api: httpx.Client) -> None:
    response = api.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_each_dependency(api: httpx.Client) -> None:
    checks = api.get("/health").json()["checks"]

    assert checks == {"database": "ok", "inference": "ok"}
