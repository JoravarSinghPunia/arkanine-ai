import os
import uuid
from collections.abc import Callable, Iterator

import httpx
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


@pytest.fixture
def collection_id(api: httpx.Client) -> int:
    """A fresh, empty Collection."""
    response = api.post("/collections", json={"name": f"collection-{uuid.uuid4()}"})
    response.raise_for_status()
    return int(response.json()["id"])


@pytest.fixture
def ingest(api: httpx.Client, collection_id: int) -> Callable[[str, str], int]:
    """Ingest a text document into the fresh Collection and return its id."""

    def _ingest(title: str, content: str) -> int:
        response = api.post(
            f"/collections/{collection_id}/documents",
            json={"title": title, "content": content},
        )
        response.raise_for_status()
        return int(response.json()["id"])

    return _ingest
