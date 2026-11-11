import os
import uuid
from collections.abc import Callable, Iterator

import httpx
import pytest

API_URL = os.environ.get("ARKANINE_API_URL", "http://localhost:8000")
FAKE_INFERENCE_URL = os.environ.get("ARKANINE_FAKE_INFERENCE_URL", "http://localhost:8080")
# Must match the administrator the stack is started with (see compose.yaml).
ADMIN_USERNAME = os.environ.get("ARKANINE_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ARKANINE_ADMIN_PASSWORD", "arkanine-dev-admin")
# Must match the INFERENCE_API_KEY the stack is started with (see Makefile).
INFERENCE_API_KEY = os.environ.get("ARKANINE_INFERENCE_API_KEY", "test-inference-key")


@pytest.fixture(scope="session")
def admin_credentials() -> dict[str, str]:
    return {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}


@pytest.fixture(scope="session")
def inference_api_key() -> str:
    return INFERENCE_API_KEY


@pytest.fixture(scope="session")
def anon() -> Iterator[httpx.Client]:
    """A client that has not signed in."""
    with httpx.Client(base_url=API_URL, timeout=10) as client:
        yield client


def _signed_in(anon: httpx.Client, credentials: dict[str, str]) -> httpx.Client:
    response = anon.post("/sessions", json=credentials)
    response.raise_for_status()
    return httpx.Client(
        base_url=API_URL,
        timeout=10,
        headers={"Authorization": f"Bearer {response.json()['token']}"},
    )


@pytest.fixture(scope="session")
def api(anon: httpx.Client, admin_credentials: dict[str, str]) -> Iterator[httpx.Client]:
    """A client signed in as the administrator."""
    with _signed_in(anon, admin_credentials) as client:
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


@pytest.fixture
def user_account(anon: httpx.Client, api: httpx.Client) -> Iterator[tuple[int, httpx.Client]]:
    """A local account created by the administrator, with no access to any Collection."""
    credentials = {"username": f"user-{uuid.uuid4()}", "password": "correct horse"}
    created = api.post("/users", json=credentials)
    created.raise_for_status()
    with _signed_in(anon, credentials) as client:
        yield int(created.json()["id"]), client


@pytest.fixture
def user(user_account: tuple[int, httpx.Client]) -> httpx.Client:
    """A client signed in as `user_account`."""
    return user_account[1]


@pytest.fixture
def user_id(user_account: tuple[int, httpx.Client]) -> int:
    return user_account[0]
