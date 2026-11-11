"""Every shipped model is open-weight from a US or European lab (ADR 0002)."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROVENANCE = json.loads((ROOT / "models" / "provenance.json").read_text())
MODELS: list[dict[str, Any]] = PROVENANCE["models"]
BACKEND_FILES = sorted((ROOT / "backends").glob("*.env"))

# The United States, the EU and EEA, the United Kingdom and Switzerland.
ALLOWED_ORIGINS = {
    "United States", "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia",
    "Denmark", "Estonia", "Finland", "France", "Germany", "Greece", "Hungary", "Iceland",
    "Ireland", "Italy", "Latvia", "Liechtenstein", "Lithuania", "Luxembourg", "Malta",
    "Netherlands", "Norway", "Poland", "Portugal", "Romania", "Slovakia", "Slovenia", "Spain",
    "Sweden", "Switzerland", "United Kingdom",
}  # fmt: skip
# Model families and publishers of Chinese origin, matched as whole words.
CHINESE_ORIGIN = re.compile(
    r"\b(qwen\w*|qwq|deepseek\w*|baichuan\w*|internlm\w*|internvl\w*|yi|01-ai|chatglm\w*|"
    r"glm|thudm|zhipu\w*|bge|baai|gte|alibaba\w*|minicpm\w*|openbmb|kimi|moonshot\w*|"
    r"hunyuan\w*|ernie|baidu|tencent|stepfun|minimax)\b",
    re.IGNORECASE,
)


def _backend_settings(path: Path) -> dict[str, str]:
    settings = {}
    for line in path.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            settings[key.strip()] = value.strip().strip("\"'")
    return settings


@pytest.mark.parametrize("model", MODELS, ids=[m["name"] for m in MODELS])
def test_each_shipped_model_names_its_lab_origin_licence_and_source(model: dict[str, Any]) -> None:
    for field in ("name", "role", "lab", "origin", "licence", "source", "served_as"):
        assert model.get(field), f"{model.get('name')} has no {field}"
    assert model["role"] in {"chat", "embedding"}
    assert model["source"].startswith("https://huggingface.co/")


@pytest.mark.parametrize("model", MODELS, ids=[m["name"] for m in MODELS])
def test_each_shipped_model_comes_from_a_us_or_european_lab(model: dict[str, Any]) -> None:
    assert model["origin"] in ALLOWED_ORIGINS


@pytest.mark.parametrize("model", MODELS, ids=[m["name"] for m in MODELS])
def test_no_shipped_model_is_of_chinese_origin(model: dict[str, Any]) -> None:
    assert not CHINESE_ORIGIN.search(json.dumps(model))


def test_the_chinese_origin_check_recognises_known_families() -> None:
    for name in ("Qwen2.5-7B-Instruct", "deepseek-r1", "BAAI/bge-m3", "thenlper/gte-large"):
        assert CHINESE_ORIGIN.search(name), name
    for name in ("meta-llama/Llama-3.2-3B-Instruct", "nomic-embed-text", "gpt-oss:20b"):
        assert not CHINESE_ORIGIN.search(name), name


def test_there_is_a_config_for_each_supported_backend() -> None:
    assert {path.stem for path in BACKEND_FILES} == {"ollama", "llamacpp", "vllm"}


@pytest.mark.parametrize("path", BACKEND_FILES, ids=[p.stem for p in BACKEND_FILES])
def test_every_model_a_backend_config_names_is_in_the_provenance_list(path: Path) -> None:
    settings = _backend_settings(path)
    for setting, role in (("INFERENCE_MODEL", "chat"), ("EMBEDDING_MODEL", "embedding")):
        served = {m["served_as"].get(path.stem) for m in MODELS if m["role"] == role}
        assert settings[setting] in served, f"{path.name}: {setting}"


def test_the_published_model_list_covers_every_shipped_model() -> None:
    published = (ROOT / "docs" / "models.md").read_text()
    for model in MODELS:
        assert f"| {model['name']} | {model['lab']} | {model['origin']} |" in published
