"""An Offline bundle is signed, and anyone can check it with standard tools.

These tests build a real bundle of the `test` tier with a throwaway signing key, so they need
Docker and the images the bundle carries.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tarfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NamedTuple

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
PRINCIPAL = "release@arkanine"
NAMESPACE = "arkanine-bundle"


def _run(*args: str | Path, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, **kwargs)


class SigningKey(NamedTuple):
    private: Path
    signers: Path


def _new_key(directory: Path) -> SigningKey:
    """A fresh Ed25519 key, and an allowed-signers file that trusts it for bundles."""
    directory.mkdir(parents=True)
    key = directory / "key"
    _run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", PRINCIPAL, "-f", key, check=True)
    signers = directory / "allowed_signers"
    public = (directory / "key.pub").read_text().split()
    signers.write_text(f'{PRINCIPAL} namespaces="{NAMESPACE}" {public[0]} {public[1]}\n')
    return SigningKey(key, signers)


@pytest.fixture(scope="session")
def release_key(tmp_path_factory: pytest.TempPathFactory) -> SigningKey:
    return _new_key(tmp_path_factory.mktemp("keys") / "release")


@pytest.fixture(scope="session")
def other_key(tmp_path_factory: pytest.TempPathFactory) -> SigningKey:
    return _new_key(tmp_path_factory.mktemp("keys") / "other")


@pytest.fixture(scope="session")
def bundle_archive(tmp_path_factory: pytest.TempPathFactory, release_key: SigningKey) -> Path:
    key, signers = release_key.private, release_key.signers
    out = tmp_path_factory.mktemp("dist")
    result = _run(
        "python3", ROOT / "bundle" / "build.py", "--tier", "test", "--version", "0.0.0-test",
        "--signing-key", key, "--allowed-signers", signers, "--out", out,
    )  # fmt: skip
    assert result.returncode == 0, result.stdout + result.stderr
    return out / "arkanine-0.0.0-test-test.tar"


@pytest.fixture(scope="session")
def bundle_dir(tmp_path_factory: pytest.TempPathFactory, bundle_archive: Path) -> Path:
    """The bundle as an operator sees it after unpacking the archive."""
    destination = tmp_path_factory.mktemp("unpacked")
    with tarfile.open(bundle_archive) as archive:
        archive.extractall(destination)
    (unpacked,) = destination.iterdir()
    return unpacked


def test_checksums_verify_with_standard_tools(bundle_dir: Path) -> None:
    result = _run("shasum", "-a", "256", "-c", "SHA256SUMS", cwd=bundle_dir)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_checksums_cover_every_file_in_the_bundle(bundle_dir: Path) -> None:
    listed = {
        line.split("  ", 1)[1] for line in (bundle_dir / "SHA256SUMS").read_text().splitlines()
    }
    present = {
        str(path.relative_to(bundle_dir))
        for path in bundle_dir.rglob("*")
        if path.is_file() and path.name not in {"SHA256SUMS", "SHA256SUMS.sig"}
    }
    assert listed == present


def test_the_signature_verifies_with_standard_tools(
    bundle_dir: Path, release_key: SigningKey
) -> None:
    signers = release_key.signers
    result = _run(
        "ssh-keygen", "-Y", "verify", "-f", signers, "-I", PRINCIPAL, "-n", NAMESPACE,
        "-s", bundle_dir / "SHA256SUMS.sig", stdin=(bundle_dir / "SHA256SUMS").open(),
    )  # fmt: skip
    assert result.returncode == 0, result.stdout + result.stderr


def _copy(bundle_dir: Path, destination: Path) -> Path:
    """A cheap copy of the bundle: hard links, so tampering must replace files, not edit them."""
    shutil.copytree(bundle_dir, destination, copy_function=os.link)
    return destination


def _replace(path: Path, content: bytes) -> None:
    path.unlink()
    path.write_bytes(content)


def _verify(bundle: Path, signers: Path) -> subprocess.CompletedProcess[str]:
    return _run("sh", bundle / "install.sh", "--verify-only", "--signers", signers, bundle)


def test_an_untouched_bundle_passes_verification(bundle_dir: Path, release_key: SigningKey) -> None:
    result = _verify(bundle_dir, release_key.signers)
    assert result.returncode == 0, result.stdout + result.stderr


def _modify_compose(bundle: Path) -> None:
    compose = bundle / "compose.yaml"
    _replace(compose, compose.read_bytes().replace(b"pull_policy: never", b"pull_policy: always"))


def _modify_image(bundle: Path) -> None:
    image = next((bundle / "images").iterdir())
    _replace(image, image.read_bytes() + b"\0")


def _add_file(bundle: Path) -> None:
    (bundle / "images" / "extra.tar").write_bytes(b"not listed in SHA256SUMS")


def _remove_file(bundle: Path) -> None:
    next((bundle / "images").iterdir()).unlink()


def _replace_installer(bundle: Path) -> None:
    _replace(bundle / "install.sh", b'#!/bin/sh\necho "Verified"\n')


def _rewrite_checksums(bundle: Path) -> None:
    """Edit a file and update SHA256SUMS to match, without being able to re-sign it."""
    _modify_compose(bundle)
    sums = bundle / "SHA256SUMS"
    digest = _run("shasum", "-a", "256", "compose.yaml", cwd=bundle, check=True).stdout.split()[0]
    lines = [
        f"{digest}  compose.yaml" if line.endswith("  compose.yaml") else line
        for line in sums.read_text().splitlines()
    ]
    _replace(sums, ("\n".join(lines) + "\n").encode())


@pytest.mark.parametrize(
    "tamper",
    [
        _modify_compose,
        _modify_image,
        _replace_installer,
        _add_file,
        _remove_file,
        _rewrite_checksums,
    ],
)
def test_a_tampered_bundle_fails_verification(
    bundle_dir: Path,
    release_key: SigningKey,
    tmp_path: Path,
    tamper: Callable[[Path], None],
) -> None:
    bundle = _copy(bundle_dir, tmp_path / "bundle")
    tamper(bundle)
    # Verify with the untouched installer, as an existing installation would.
    shutil.copy2(bundle_dir / "install.sh", tmp_path / "install.sh")
    result = _run(
        "sh", tmp_path / "install.sh", "--verify-only", "--signers", release_key.signers, bundle
    )
    assert result.returncode != 0, result.stdout
    assert "Do not install this bundle" in result.stderr


def test_a_bundle_signed_with_another_key_fails_verification(
    bundle_dir: Path, release_key: SigningKey, other_key: SigningKey, tmp_path: Path
) -> None:
    bundle = _copy(bundle_dir, tmp_path / "bundle")
    (bundle / "SHA256SUMS.sig").unlink()
    _run("ssh-keygen", "-Y", "sign", "-q", "-f", other_key.private, "-n", NAMESPACE,
         bundle / "SHA256SUMS", check=True)  # fmt: skip
    result = _verify(bundle, release_key.signers)
    assert result.returncode != 0, result.stdout
    assert "not signed by a trusted Arkanine key" in result.stderr


def test_verification_needs_a_trusted_public_key(bundle_dir: Path, tmp_path: Path) -> None:
    """With no key given and no installation, the bundle can't vouch for itself."""
    result = _run(
        "sh", bundle_dir / "install.sh", "--verify-only", bundle_dir,
        env={**os.environ, "ARKANINE_HOME": str(tmp_path / "nowhere")},
    )  # fmt: skip
    assert result.returncode != 0
    assert "public key" in result.stderr


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


@pytest.fixture
def installation(tmp_path: Path) -> Iterator[dict[str, str]]:
    """Where to install, on ports and a Compose project of its own; torn down afterwards."""
    env = {
        **os.environ,
        "ARKANINE_HOME": str(tmp_path / "arkanine"),
        "COMPOSE_PROJECT_NAME": f"arkanine-bundle-test-{os.getpid()}",
        "API_PORT": str(_free_port()),
        "FAKE_INFERENCE_PORT": str(_free_port()),
    }
    yield env
    if (tmp_path / "arkanine").exists():
        _run("docker", "compose", "down", "--volumes", cwd=tmp_path / "arkanine", env=env)


def _install(
    bundle: Path, key: SigningKey, installation: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return _run("sh", bundle / "install.sh", "--signers", key.signers, env=installation)


def _remove_bundled_images(bundle: Path) -> None:
    """So the install can only work by loading the bundle's images, never by pulling."""
    for archive in (bundle / "images").iterdir():
        manifest = tarfile.open(archive).extractfile("manifest.json")
        assert manifest is not None
        for entry in json.load(manifest):
            for tag in entry.get("RepoTags") or []:
                _run("docker", "image", "rm", "--force", tag)


def test_the_bundle_installs_and_answers_without_anything_downloaded(
    bundle_dir: Path, release_key: SigningKey, installation: dict[str, str]
) -> None:
    _remove_bundled_images(bundle_dir)

    result = _install(bundle_dir, release_key, installation)
    assert result.returncode == 0, result.stdout + result.stderr

    home = Path(installation["ARKANINE_HOME"])
    settings = dict(
        line.split("=", 1) for line in (home / ".env").read_text().splitlines() if "=" in line
    )
    api = f"http://localhost:{installation['API_PORT']}"
    assert httpx.get(f"{api}/health", timeout=10).status_code == 200
    signed_in = httpx.post(
        f"{api}/sessions",
        json={"username": "admin", "password": settings["ARKANINE_ADMIN_PASSWORD"]},
        timeout=10,
    )
    assert signed_in.status_code == 201, signed_in.text


def test_an_installation_verifies_later_bundles_with_its_own_key(
    bundle_dir: Path, release_key: SigningKey, installation: dict[str, str]
) -> None:
    result = _install(bundle_dir, release_key, installation)
    assert result.returncode == 0, result.stdout + result.stderr

    installed = Path(installation["ARKANINE_HOME"]) / "bin" / "install.sh"
    result = _run("sh", installed, "--verify-only", bundle_dir, env=installation)
    assert result.returncode == 0, result.stdout + result.stderr
