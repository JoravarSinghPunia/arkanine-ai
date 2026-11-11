"""Build a signed Offline bundle: container images, model weights, install files and checksums.

    python bundle/build.py --tier laptop --models-dir models/weights \\
        --signing-key ~/.config/arkanine/release-signing-key --out dist

The bundle is one tar archive holding a directory with SHA256SUMS, which lists every other
file, and SHA256SUMS.sig, an SSH signature over it. See docs/bundle.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "bundle"
PRINCIPAL = "release@arkanine"
NAMESPACE = "arkanine-bundle"
# Images Arkanine builds itself, and the context each is built from. Others are pulled.
LOCAL_BUILDS = {
    "arkanine/api": ROOT,
    "arkanine/fake-inference": ROOT / "testing" / "fake_inference",
}


class BundleError(Exception):
    pass


def _run(*args: str | Path, **kwargs: Any) -> str:
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise BundleError(f"{' '.join(map(str, args))} failed:\n{result.stderr.strip()}")
    output: str = result.stdout
    return output


def _project_version() -> str:
    match = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M)
    if not match:
        raise BundleError("no version in pyproject.toml")
    return match.group(1)


def _check_signing_key(signing_key: Path, allowed_signers: Path) -> None:
    """Refuse to sign with a key that the public key shipped with the install would reject."""
    if not signing_key.is_file():
        raise BundleError(f"no signing key at {signing_key}")
    key_type, key_data = _run("ssh-keygen", "-y", "-f", signing_key).split()[:2]
    for line in allowed_signers.read_text().splitlines():
        fields = line.split()
        if fields and fields[0] == PRINCIPAL and key_data in fields and key_type in fields:
            return
    raise BundleError(f"{allowed_signers} does not trust {signing_key} as {PRINCIPAL}")


def _images(tier: str, version: str) -> list[str]:
    """Every image the installed stack runs, as Compose resolves it."""
    files: list[str | Path] = ["-f", HERE / "compose.yaml", "-f", HERE / f"compose.{tier}.yaml"]
    # Placeholders for values install.sh sets; they don't change which images are used.
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "ARKANINE_VERSION": version,
        "ARKANINE_DB_PASSWORD": "-",
        "ARKANINE_ADMIN_PASSWORD": "-",
    }
    return sorted(set(_run("docker", "compose", *files, "config", "--images", env=env).split()))


def _fetch(image: str, platform: str) -> None:
    repository = image.rsplit(":", 1)[0]
    if repository in LOCAL_BUILDS:
        print(f"Building {image}", flush=True)
        _run("docker", "build", "--platform", platform, "-t", image, LOCAL_BUILDS[repository])
    else:
        print(f"Pulling {image}", flush=True)
        _run("docker", "pull", "--platform", platform, image)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _model_files(models_dir: Path, path: str) -> dict[str, Path]:
    """The files making up one bundled model, by their path inside the bundle."""
    source = models_dir / path
    if source.is_file():
        return {f"models/{path}": source}
    return {
        f"models/{path}/{file.relative_to(source).as_posix()}": file
        for file in sorted(source.rglob("*"))
        if file.is_file()
    }


def build(
    tier: str,
    version: str,
    models_dir: Path,
    signing_key: Path,
    allowed_signers: Path,
    out: Path,
    platform: str,
) -> Path:
    tiers = json.loads((HERE / "tiers.json").read_text())
    if tier not in tiers:
        raise BundleError(f"unknown tier {tier!r}; choose one of {', '.join(sorted(tiers))}")
    # Check everything cheap before the slow image work.
    models = tiers[tier]["models"]
    missing = [m["path"] for m in models if not (models_dir / m["path"]).exists()]
    if missing:
        raise BundleError(
            f"missing model files in {models_dir}: {', '.join(missing)}. Build them from the "
            "original weights listed in docs/models.md."
        )
    _check_signing_key(signing_key, allowed_signers)

    name = f"arkanine-{version}-{tier}"
    staging = out / f".{name}"
    shutil.rmtree(staging, ignore_errors=True)
    (staging / "images").mkdir(parents=True)
    (staging / "keys").mkdir()
    for file in ("compose.yaml", f"compose.{tier}.yaml", "install.sh"):
        shutil.copy2(HERE / file, staging / file)
    shutil.copy2(allowed_signers, staging / "keys" / "allowed_signers")
    (staging / "bundle.env").write_text(f"ARKANINE_VERSION={version}\nARKANINE_TIER={tier}\n")

    for image in _images(tier, version):
        _fetch(image, platform)
        target = staging / "images" / (re.sub(r"[^A-Za-z0-9_.-]", "_", image) + ".tar")
        print(f"Saving {image}", flush=True)
        _run("docker", "save", "--platform", platform, "-o", target, image)

    entries = {
        file.relative_to(staging).as_posix(): file
        for file in sorted(staging.rglob("*"))
        if file.is_file()
    }
    for model in models:
        entries.update(_model_files(models_dir, model["path"]))

    print("Writing checksums", flush=True)
    sums = "".join(f"{_sha256(entries[path])}  {path}\n" for path in sorted(entries))
    (staging / "SHA256SUMS").write_text(sums)
    _run("ssh-keygen", "-Y", "sign", "-q", "-f", signing_key, "-n", NAMESPACE,
         staging / "SHA256SUMS")  # fmt: skip
    entries["SHA256SUMS"] = staging / "SHA256SUMS"
    entries["SHA256SUMS.sig"] = staging / "SHA256SUMS.sig"

    archive_path = out / f"{name}.tar"
    print(f"Writing {archive_path}", flush=True)
    with tarfile.open(archive_path, "w") as archive:
        for path in sorted(entries):
            info = archive.gettarinfo(entries[path].resolve(), f"{name}/{path}")
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with entries[path].open("rb") as content:
                archive.addfile(info, content)
    shutil.rmtree(staging)
    return archive_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tier", required=True, help="laptop, gpu or test; see bundle/tiers.json")
    parser.add_argument("--models-dir", type=Path, default=ROOT / "models" / "weights")
    parser.add_argument("--signing-key", type=Path, required=True)
    parser.add_argument(
        "--allowed-signers",
        type=Path,
        default=ROOT / "keys" / "allowed_signers",
        help="the public key shipped with the install",
    )
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    parser.add_argument("--version", default=None, help="defaults to pyproject.toml's version")
    parser.add_argument(
        "--platform",
        default=None,
        help="the install machine's platform, e.g. linux/amd64; defaults to this Docker host's",
    )
    args = parser.parse_args(argv)
    try:
        args.out.mkdir(parents=True, exist_ok=True)
        platform = (
            args.platform
            or _run("docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}").strip()
        )
        archive = build(
            tier=args.tier,
            version=args.version or _project_version(),
            models_dir=args.models_dir.expanduser(),
            signing_key=args.signing_key.expanduser(),
            allowed_signers=args.allowed_signers.expanduser(),
            out=args.out,
            platform=platform,
        )
    except BundleError as error:
        print(f"bundle: {error}", file=sys.stderr)
        return 1
    print(f"Built {archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
