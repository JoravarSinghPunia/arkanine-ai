import os

import httpx
import psycopg
from fastapi import FastAPI, Response

CHECK_TIMEOUT_SECONDS = 2


def _check_database() -> str:
    try:
        with psycopg.connect(
            os.environ["DATABASE_URL"], connect_timeout=CHECK_TIMEOUT_SECONDS
        ) as conn:
            conn.execute("SELECT 1")
    except (KeyError, psycopg.Error):
        return "unavailable"
    return "ok"


def _check_inference() -> str:
    try:
        base_url = os.environ["INFERENCE_BASE_URL"].rstrip("/")
        httpx.get(f"{base_url}/models", timeout=CHECK_TIMEOUT_SECONDS).raise_for_status()
    except (KeyError, httpx.HTTPError):
        return "unavailable"
    return "ok"


def create_app() -> FastAPI:
    app = FastAPI(title="Arkanine")

    @app.get("/health")
    def health(response: Response) -> dict[str, object]:
        checks = {"database": _check_database(), "inference": _check_inference()}
        healthy = all(state == "ok" for state in checks.values())
        if not healthy:
            response.status_code = 503
        return {"status": "ok" if healthy else "degraded", "checks": checks}

    return app


app = create_app()
