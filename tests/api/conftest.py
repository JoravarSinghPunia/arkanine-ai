import os
from collections.abc import Iterator

import httpx
import psycopg
import pytest

API_URL = os.environ.get("ARKANINE_API_URL", "http://localhost:8000")
FAKE_INFERENCE_URL = os.environ.get("ARKANINE_FAKE_INFERENCE_URL", "http://localhost:8080")


@pytest.fixture(scope="session")
def api() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=API_URL, timeout=10) as client:
        yield client


@pytest.fixture(scope="session")
def fake_inference() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=FAKE_INFERENCE_URL, timeout=10) as client:
        yield client


@pytest.fixture(autouse=True)
def cleanup_database() -> Iterator[None]:
    """Clean up database before each test."""
    db_url = os.environ.get(
        "DATABASE_URL", "postgresql://arkanine:arkanine@localhost:5432/arkanine"
    )
    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE documents CASCADE")
                cur.execute("TRUNCATE TABLE collections CASCADE")
                conn.commit()
    except Exception:
        # Ignore errors during cleanup
        pass

    yield
