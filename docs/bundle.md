# The Offline bundle

An [Offline bundle](../GLOSSARY.md) is one tar archive holding everything a Private AI system needs to install or upgrade with no network access: the container images, the model weights including the embedding model, the install files, and checksums. Nothing is downloaded at install or run time ([ADR 0003](adr/0003-zero-phone-home.md)). The bundle is signed with the Arkanine signing key, and anyone can check it with standard tools ([ADR 0004](adr/0004-ssh-signed-bundles.md)).

## What's in a bundle

```
arkanine-<version>-<tier>/
  SHA256SUMS            checksum of every other file
  SHA256SUMS.sig        SSH signature over SHA256SUMS
  install.sh            verifies, then installs
  bundle.env            version and tier
  compose.yaml          the installed stack: Postgres and the API
  compose.<tier>.yaml   the tier's inference servers
  keys/allowed_signers  the Arkanine public key, kept by the installation
  images/*.tar          every container image the stack runs
  models/...            the tier's model files
```

Each installed service sets `pull_policy: never` and none is built, so a missing image is an error rather than a download. A test checks this for every tier.

## Tiers

The tiers match the [hardware tiers](models.md#hardware-tiers). [bundle/tiers.json](../bundle/tiers.json) lists the model files each one needs, and a test checks them against the [provenance list](models.md#shipped-models).

| Tier | Inference | Model files in `MODELS_DIR` |
| --- | --- | --- |
| `laptop` | Two llama.cpp servers on the CPU | `Llama-3.2-3B-Instruct-Q4_K_M.gguf`, `nomic-embed-text-v1.5.f16.gguf` |
| `gpu` | vLLM on one NVIDIA GPU for chat, llama.cpp on the CPU for embeddings | `Mistral-Small-3.1-24B-Instruct-2503/` (the original weights directory), `nomic-embed-text-v1.5.f16.gguf` |
| `test` | The fake inference server the tests use | None |

Build the GGUF files from the original weights as in [docs/models.md](models.md#llamacpp-laptop-or-mac). The `gpu` tier serves embeddings with llama.cpp because vLLM would need nomic-embed-text's custom model code, which it fetches from Hugging Face. On a Mac, containers can't use the Apple GPU, so the `laptop` tier runs on the CPU and is slower than running llama.cpp natively.

## Building

Building needs the internet to pull the third-party images. It never fetches model weights.

```sh
make bundle TIER=laptop MODELS_DIR=~/arkanine-weights
```

| Variable | Meaning | Default |
| --- | --- | --- |
| `TIER` | `laptop`, `gpu` or `test` | `laptop` |
| `MODELS_DIR` | The directory holding the tier's model files | `models/weights` |
| `SIGNING_KEY` | The Arkanine private key | `~/.config/arkanine/release-signing-key` |
| `PLATFORM` | The install machine's platform, e.g. `linux/amd64` for a GPU server | This Docker host's |

The bundle is written to `dist/arkanine-<version>-<tier>.tar`. The build refuses to sign with a key that [keys/allowed_signers](../keys/allowed_signers) doesn't trust, because installations would reject the result.

## The signing key

The Arkanine public key is [keys/allowed_signers](../keys/allowed_signers). Its fingerprint is:

```
SHA256:S5J0OVTtnBakvnJpM8k6lZFREvBLqJzm57K0QUB51Og release@arkanine (ED25519)
```

The private key is kept outside the repository, at `~/.config/arkanine/release-signing-key` on the machine that builds bundles, and must never be committed. Back it up offline and protect it with a passphrase (`ssh-keygen -p -f ~/.config/arkanine/release-signing-key`). Customer-held signing keys are later work.

## Checking a bundle by hand

These steps use no Arkanine tooling. Get the public key and its fingerprint separately from the bundle, for example from this repository, and check the fingerprint with `ssh-keygen -lf allowed_signers`. Then:

```sh
tar -xf arkanine-0.1.0-laptop.tar
cd arkanine-0.1.0-laptop
ssh-keygen -Y verify -f /path/to/allowed_signers -I release@arkanine -n arkanine-bundle \
  -s SHA256SUMS.sig < SHA256SUMS
sha256sum -c SHA256SUMS    # or: shasum -a 256 -c SHA256SUMS
```

The first command must print `Good "arkanine-bundle" signature for release@arkanine`, and the second must report every file as `OK`. Also check that the directory holds no files missing from `SHA256SUMS`. `install.sh` repeats all of these checks before installing anything.

## Installing

The machine needs Docker with Compose, and OpenSSH 8.2 or later. On a GPU server it also needs the NVIDIA driver and Container Toolkit.

On the first install there is no trusted `install.sh` yet, and the one in the bundle is part of what needs checking. So [check the bundle by hand](#checking-a-bundle-by-hand) first, then run its `install.sh` with the public key you received separately:

```sh
sh arkanine-0.1.0-laptop/install.sh --signers /path/to/allowed_signers
```

`install.sh` verifies the bundle again and stops if anything doesn't match. It then loads the images, copies the Compose files and models into `ARKANINE_HOME` (default `~/arkanine`), and starts the stack. The API listens on port 8000, or on `API_PORT` if set. The first install generates the administrator and database passwords and writes them to `ARKANINE_HOME/.env`, which only the installing user can read. Sign in as `admin` with that password.

`install.sh --verify-only` verifies without installing.

## Upgrading

Run the `install.sh` kept by the installation, not the one in the new bundle. It verifies the new bundle with the installation's own key, so no check by hand is needed:

```sh
~/arkanine/bin/install.sh /path/to/arkanine-0.2.0-laptop
```

Passwords and data are kept. The Compose files, models, `install.sh` and public key are replaced with the new bundle's.
