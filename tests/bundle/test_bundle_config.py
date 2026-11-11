"""What an Offline bundle installs must never need the network (ADR 0003)."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "bundle"
TIERS: dict[str, Any] = json.loads((BUNDLE / "tiers.json").read_text())
PROVENANCE: list[dict[str, Any]] = json.loads((ROOT / "models" / "provenance.json").read_text())[
    "models"
]


def _installed_compose(tier: str) -> dict[str, Any]:
    """The Compose configuration as Docker resolves it on an installed machine."""
    result = subprocess.run(
        ["docker", "compose", "-f", "compose.yaml", "-f", f"compose.{tier}.yaml"]
        + ["config", "--format", "json"],
        cwd=BUNDLE,
        env={
            "PATH": os.environ["PATH"],
            "ARKANINE_VERSION": "0.0.0",
            "ARKANINE_DB_PASSWORD": "db-password",
            "ARKANINE_ADMIN_PASSWORD": "admin-password",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    config: dict[str, Any] = json.loads(result.stdout)
    return config


def test_the_bundle_offers_the_demo_pilot_and_test_tiers() -> None:
    assert set(TIERS) == {"laptop", "gpu", "test"}


@pytest.mark.parametrize("tier", sorted(TIERS))
def test_no_installed_service_is_built_or_pulled(tier: str) -> None:
    services = _installed_compose(tier)["services"]
    for name, service in services.items():
        assert "build" not in service, name
        assert service.get("pull_policy") == "never", name


MODEL_TIERS = sorted(tier for tier, spec in TIERS.items() if spec["models"])


@pytest.mark.parametrize("tier", MODEL_TIERS)
def test_every_model_a_tier_bundles_is_provenanced_for_that_tier(tier: str) -> None:
    provenanced = {m["name"] for m in PROVENANCE if tier in m["tiers"]}
    for bundled in TIERS[tier]["models"]:
        assert bundled["model"] in provenanced, bundled


@pytest.mark.parametrize("tier", MODEL_TIERS)
def test_every_model_a_tier_serves_is_one_it_bundles(tier: str) -> None:
    bundled = {b["model"] for b in TIERS[tier]["models"]}
    served = {name for m in PROVENANCE if m["name"] in bundled for name in m["served_as"].values()}
    api = _installed_compose(tier)["services"]["api"]["environment"]
    assert api["INFERENCE_MODEL"] in served
    assert api["EMBEDDING_MODEL"] in served


@pytest.mark.parametrize("tier", MODEL_TIERS)
def test_every_model_file_a_tier_bundles_is_one_a_server_loads(tier: str) -> None:
    services = _installed_compose(tier)["services"]
    commands = " ".join(" ".join(s.get("command") or []) for s in services.values())
    for bundled in TIERS[tier]["models"]:
        assert f"/models/{bundled['path']}" in commands, bundled
