# Models, inference backends and hardware

Arkanine sends every model call through one OpenAI-compatible interface: chat completions, embeddings and a `/models` health check. Ollama, llama.cpp's `llama-server` and vLLM all provide it, so the same code runs on a Mac and on a GPU server. Switching backend or model changes configuration only.

## Shipped models

Arkanine ships only open-weight models from US and European labs ([ADR 0002](adr/0002-model-provenance.md)). No Chinese-origin weights are included, whatever their benchmark scores. Quantised files in the Offline bundle are made from the original weights listed here with llama.cpp's own tools, and third-party conversions are not shipped. Ollama's library tags used during development are a convenience, not what ships. The machine-readable list is [models/provenance.json](../models/provenance.json), and a test checks it against this table and against every backend configuration.

| Model | Lab | Origin | Role | Tier | Licence | Original weights |
| --- | --- | --- | --- | --- | --- | --- |
| Llama 3.2 3B Instruct | Meta | United States | Chat | Laptop or Mac demo | Llama 3.2 Community License | [meta-llama/Llama-3.2-3B-Instruct](https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct) |
| Mistral Small 3.1 24B Instruct | Mistral AI | France | Chat | Single GPU pilot | Apache-2.0 | [mistralai/Mistral-Small-3.1-24B-Instruct-2503](https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503) |
| gpt-oss-20b | OpenAI | United States | Chat (pilot alternative) | Single GPU pilot | Apache-2.0 | [openai/gpt-oss-20b](https://huggingface.co/openai/gpt-oss-20b) |
| nomic-embed-text v1.5 | Nomic AI | United States | Embeddings | Both | Apache-2.0 | [nomic-ai/nomic-embed-text-v1.5](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) |

To add a model, add it to `models/provenance.json` and to this table, with its lab, origin, licence and original weights.

## Configuration

| Variable | Meaning |
| --- | --- |
| `INFERENCE_BASE_URL` | The chat server's OpenAI-compatible base URL, ending in `/v1` |
| `INFERENCE_MODEL` | The chat model's name on that server |
| `INFERENCE_API_KEY` | Bearer token for the server, if it requires one (optional) |
| `EMBEDDING_BASE_URL` | The embedding server's base URL. Defaults to `INFERENCE_BASE_URL` |
| `EMBEDDING_MODEL` | The embedding model's name on that server |
| `EMBEDDING_API_KEY` | Bearer token for the embedding server. Defaults to `INFERENCE_API_KEY` |
| `EMBEDDING_QUERY_PREFIX`, `EMBEDDING_DOCUMENT_PREFIX` | Text put before questions and passages before embedding, for models that need it. nomic-embed-text uses `search_query: ` and `search_document: ` |

Passages are embedded when a document is ingested and stored in Postgres with pgvector. Answers rank passages by cosine similarity to the question, within the Collections the user can access. Embeddings are stored per embedding model. After `EMBEDDING_MODEL` changes, a Collection's documents are re-embedded the first time someone asks a question of it, so the first answer is slower.

The [backends/](../backends/) folder holds one configuration per backend. `make dev BACKEND=<name>` starts the stack with it. Without `BACKEND`, the stack uses the fake inference server that the tests use. Models run on the host, not in Compose, so the API reaches them at `host.docker.internal`.

During development, fetching models (`ollama pull`, downloading weights) needs the internet. In an installation, the weights come from the [Offline bundle](bundle.md) and nothing is downloaded ([ADR 0003](adr/0003-zero-phone-home.md)).

### Ollama (laptop or Mac)

```sh
ollama pull llama3.2:3b
ollama pull nomic-embed-text
make dev BACKEND=ollama
```

### llama.cpp (laptop or Mac)

Build the GGUF files from the original weights, using the scripts that come with llama.cpp:

```sh
python convert_hf_to_gguf.py Llama-3.2-3B-Instruct --outtype f16 --outfile Llama-3.2-3B-Instruct-F16.gguf
llama-quantize Llama-3.2-3B-Instruct-F16.gguf Llama-3.2-3B-Instruct-Q4_K_M.gguf Q4_K_M
python convert_hf_to_gguf.py nomic-embed-text-v1.5 --outtype f16 --outfile nomic-embed-text-v1.5.f16.gguf
```

`llama-server` serves one model per process, so run one for chat and one for embeddings:

```sh
llama-server -m Llama-3.2-3B-Instruct-Q4_K_M.gguf --alias llama-3.2-3b-instruct --port 8081 -c 8192
llama-server -m nomic-embed-text-v1.5.f16.gguf --alias nomic-embed-text-v1.5 --embeddings \
  --port 8082 -c 8192 -b 8192 -ub 8192
make dev BACKEND=llamacpp
```

### vLLM (single GPU pilot)

vLLM also serves one model per process. The two processes share the GPU, and each needs an API key because the servers listen beyond loopback:

```sh
export INFERENCE_API_KEY=<a long random string>
HF_HUB_OFFLINE=1 vllm serve /models/Mistral-Small-3.1-24B-Instruct-2503 \
  --served-model-name mistralai/Mistral-Small-3.1-24B-Instruct-2503 \
  --tokenizer-mode mistral --config-format mistral --load-format mistral \
  --quantization fp8 --max-model-len 32768 --gpu-memory-utilization 0.85 \
  --host 0.0.0.0 --port 8001 --api-key "$INFERENCE_API_KEY"
HF_HUB_OFFLINE=1 vllm serve /models/nomic-embed-text-v1.5 \
  --served-model-name nomic-ai/nomic-embed-text-v1.5 --trust-remote-code \
  --gpu-memory-utilization 0.05 --host 0.0.0.0 --port 8002 --api-key "$INFERENCE_API_KEY"
make dev BACKEND=vllm
```

To use gpt-oss-20b instead, serve it on port 8001 as `openai/gpt-oss-20b` and set `INFERENCE_MODEL=openai/gpt-oss-20b`. Firewall ports 8001 and 8002 so only the Arkanine host can reach them.

## Hardware tiers

No hardware is bought before a signed pilot. The customer supplies the pilot server.

| | Laptop or Mac demo | Single GPU pilot |
| --- | --- | --- |
| Purpose | Demos on public documents | Pilots on the customer's real documents |
| Backend | Ollama or llama.cpp | vLLM |
| Chat model | Llama 3.2 3B Instruct, 4-bit (Q4_K_M, about 2 GB) | Mistral Small 3.1 24B Instruct, FP8 (about 25 GB), or gpt-oss-20b (about 14 GB) |
| Embedding model | nomic-embed-text v1.5 (about 0.3 GB) | nomic-embed-text v1.5 |
| Processor | Apple silicon (M1 or later), or a recent x86-64 CPU (slower) | 16 or more x86-64 cores |
| Accelerator | Apple GPU through Metal | One NVIDIA GPU with at least 48 GB of memory and FP8 support (e.g. L40S, RTX 6000 Ada). An 80 GB H100 gives room for longer contexts and more users |
| Memory | 16 GB, unified on a Mac | 128 GB |
| Disk | 30 GB free | 1 TB NVMe SSD |
| Software | macOS 14 or later, or Linux; Docker with Compose | Linux, NVIDIA driver and Container Toolkit, Docker with Compose |
| Network | None needed after install | None needed after install; no route to the internet |

On a Mac, run Ollama or llama.cpp natively rather than in Docker, because containers can't use the Apple GPU.
