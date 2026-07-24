# Enterprise RAG Chatbot — Local Setup (this machine)

How the RAG chatbot from [`Sheryl-shiyi/RAG`](https://github.com/Sheryl-shiyi/RAG)
(a fork of the Red Hat `rh-ai-quickstart/RAG` blueprint) was brought up locally
on this workstation, and where reality forced deviations from the repo's stock
instructions.

Goal: stay as close to the repo as possible — same architecture, **rootless
podman**, **Ollama on the host**, the repo's own `frontend/` UI — while producing
a chatbot that actually works.

> **TL;DR — start it**
> ```bash
> # 1. host Ollama must be listening on 0.0.0.0 (see §2b)
> # 2. the local Llama Stack image must exist (see §3)
> cd RAG/deploy/local && export PATH="$HOME/.local/bin:$PATH"
> OLLAMA_URL=http://172.17.0.1:11434 TAVILY_SEARCH_API_KEY=disabled \
>   podman-compose up -d llamastack rag-ui
> # 3. load demo data once (see §4):  .client06-venv/bin/python ingest-0.6.0.py
> ```
> Then open **http://localhost:8501**.

---

## 1. The big gotcha: the repo is internally version-inconsistent

The three moving parts target three incompatible Llama Stack versions:

| Component | Pinned version | API it speaks |
|-----------|----------------|---------------|
| `frontend/` (the UI) | **0.6.0** | OpenAI-style `vector_stores`, `responses`, `conversations`, `chat.completions` |
| `deploy/local` compose image | 0.2.9 | legacy `vector_dbs`, `inference.chat_completion` |
| `ingestion-service/` | 0.2.22 | legacy `vector_dbs`, `rag-tool/insert` |

A real 0.2.9 server answers the UI with **HTTP 426 ("update your client")**, and
even with the version check off the UI's calls **404** — those OpenAI-style
endpoints simply don't exist before 0.6.0. So the repo cannot run as shipped.

**Resolution chosen: align everything to 0.6.0** (the UI's version). We run a
Llama Stack **0.6.0** server and ingest through the 0.6.0 Files/Vector-Stores
API. The UI is used unchanged.

---

## 2. Architecture (what is running)

```
              host (Linux, NVIDIA RTX PRO 6000 Blackwell, 96 GB VRAM)
  ┌──────────────────────────────────────────────────────────────────┐
  │  ollama serve  (0.0.0.0:11434)  ──GPU──> llama3.2:3b-instruct-fp16 │
  └───────────────▲──────────────────────────────────────────────────┘
                  │ OLLAMA_URL=http://172.17.0.1:11434  (+ /v1 appended)
   rootless podman network `local_rag-network`
  ┌───────────────┴────────────────────────┐        ┌──────────────────┐
  │ rag-llamastack  :8321                   │        │ rag-ui  :8501     │
  │ Llama Stack 0.6.0 (our local image)     │◄───────│ Streamlit (repo)  │
  │  • inference: remote::ollama            │  0.6.0 │ 0.6.0 client      │
  │  • embeddings: sentence-transformers    │  APIs  │ chat / RAG / upload│
  │    (all-MiniLM-L6-v2, in-process)       │        └──────────────────┘
  │  • vector_io: faiss (inline)            │
  │  • files + pypdf, agents, safety, rag   │
  └─────────────────────────────────────────┘
```

Vector data lives in **OpenAI-style vector stores** (faiss under the hood),
populated by `ingest-0.6.0.py`. Embeddings are computed in-process by
sentence-transformers — Ollama serves only the chat LLM.

**Service URLs**
- RAG UI (open in a browser): <http://localhost:8501>
- Llama Stack API: <http://localhost:8321>
- Ollama API (host): <http://localhost:11434>

---

## 3. Host prerequisites that were installed

Required `sudo` (one-time):
```bash
sudo apt-get update
sudo apt-get install -y podman uidmap slirp4netns fuse-overlayfs passt
```
No root:
```bash
uv tool install podman-compose                       # ~/.local/bin/podman-compose
curl -fsSL https://ollama.com/install.sh | sudo sh   # Ollama + CUDA runtime
ollama pull llama3.2:3b-instruct-fp16
```
`uv`, `docker` and the NVIDIA driver (v595 / CUDA 13.2, needed for Blackwell)
were already present.

Rootless podman needs Docker Hub reachable for base images
(`~/.config/containers/registries.conf`):
```toml
unqualified-search-registries = ["docker.io"]
short-name-mode = "permissive"
```
```bash
podman login docker.io      # a Docker Hub account is required to pull python:3.12-slim etc.
```

### 2b. Ollama must listen on all interfaces
The stock systemd unit binds `127.0.0.1`, unreachable from rootless containers.
Run it on `0.0.0.0`:
```bash
sudo systemctl stop ollama
OLLAMA_HOST=0.0.0.0:11434 OLLAMA_KEEP_ALIVE=60m nohup ollama serve \
    > ~/development/rag-chatbot/ollama-serve.log 2>&1 &
```

---

## 4. The local Llama Stack 0.6.0 image

`deploy/local/podman-compose.yml` references
`llamastack/distribution-ollama:0.2.9`. That Docker Hub repo is **private**
(empty pull scope even when authenticated) and has no public quay.io/ghcr.io
mirror — it cannot be pulled. And even if it could, it's the wrong version
(§1). So we build our **own 0.6.0 server** and tag it as the name the compose
file expects, leaving `podman-compose.yml` unchanged.

Files in [`llamastack-local-image/`](llamastack-local-image/):
- `Containerfile-0.6.0` — python:3.12-slim + the provider deps + `llama-stack`,
  `llama-stack-api`, `llama-stack-client` all pinned to **0.6.0** (the api
  package is declared unpinned upstream and otherwise resolves to an
  incompatible newer version). Entrypoint: `llama stack run /app/config.yaml`.
- `config-0.6.0.yaml` — a trimmed `starter`-derived run config: ollama
  inference, sentence-transformers embeddings, faiss, files+pypdf, agents
  (responses/conversations), llama-guard safety, rag/websearch tools. The
  eval/scoring/datasetio/post_training providers are dropped. `LLAMA_STACK_DISABLE_VERSION_CHECK=1`
  is baked in.

Build (tagging as the compose image):
```bash
podman build -f llamastack-local-image/Containerfile-0.6.0 \
  -t docker.io/llamastack/distribution-ollama:0.2.9 llamastack-local-image
```

> The older `Containerfile` / `run.yaml` in that folder are the abandoned 0.2.9
> attempt, kept only for reference.

---

## 5. Ingestion (`ingest-0.6.0.py`)

The repo's `ingestion-service` container targets the 0.2.x `vector_dbs` API,
which the 0.6.0 UI does not read, so it is **not used**. Instead
[`ingest-0.6.0.py`](ingest-0.6.0.py) loads documents through the 0.6.0
Files + Vector-Stores API (server-side pypdf chunking + sentence-transformers
embedding). Each sub-folder of `RAG/notebooks/` becomes one vector store.

```bash
.client06-venv/bin/python ingest-0.6.0.py            # defaults to localhost:8321, RAG/notebooks
```
This creates the `hr`, `legal`, `sales`, `procurement`, `techsupport` and
`zippity-zoo` stores — 15/15 files, no failures.

> **Filename gotcha (handled by the script).** Server-side file processing
> silently fails for filenames containing non-ASCII characters: the two
> `FantaCo-TechGear-Pro-Laptop–…` PDFs (en-dash, U+2013) upload fine, report
> `status: failed` with an empty `last_error`, and never get chunked — while the
> byte-identical PDF under an ASCII name completes. `ingest-0.6.0.py` therefore
> normalises the *transmitted* filename (`ascii_filename()`); the files on disk
> are left untouched. Keep this in mind when uploading such documents through
> the UI's Upload page.

You can also add documents interactively from the UI's **Upload** page.

---

## 6. Day-to-day operation

```bash
cd RAG/deploy/local && export PATH="$HOME/.local/bin:$PATH"

# start (llamastack + ui only; the legacy ingestion container is skipped)
OLLAMA_URL=http://172.17.0.1:11434 TAVILY_SEARCH_API_KEY=disabled \
  podman-compose up -d llamastack rag-ui

podman-compose ps
podman logs -f rag-llamastack
podman-compose down          # stop (named volume + Ollama survive)
```

> `make start` is avoided because it also launches the incompatible 0.2.x
> `rag-ingestion` container; bringing up `llamastack rag-ui` explicitly is the
> equivalent for this 0.6.0 setup.

### Health checks
```bash
curl -s http://localhost:8321/v1/health                        # {"status":"OK"}
curl -s http://localhost:8321/v1/models                        # llm + embedding
curl -s http://localhost:8321/v1/vector_stores                 # the ingested stores
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8501 # UI -> 200
```

---

## 7. Known cosmetic issues

- **`rag-llamastack` shows `(starting)`/unhealthy** in `podman ps` — the compose
  healthcheck probes `/` (404) instead of `/v1/health`. The server is fine.
- **Large VRAM use for a 3B model** — Ollama 0.32 auto-sizes the KV cache to the
  95 GB VRAM (~77 GB reserved). Cap with `OLLAMA_CONTEXT_LENGTH` if VRAM is
  needed elsewhere (e.g. when adding NeMo Guardrails).
- Helper Python venvs in the project root (`.client06-venv` used by the ingest
  script; `.ls06-venv` used to derive the config/deps) can be deleted if space
  is needed — only `.client06-venv` is needed to re-run ingestion.

---

## 8. Next steps (planned)

- **NeMo Guardrails** — [`Sheryl-shiyi/Nemo-guardrail-deployment`](https://github.com/Sheryl-shiyi/Nemo-guardrail-deployment).
  Plugs into the Llama Stack **safety/shields** layer (the `llama-guard` provider
  is already configured; `nvcr.io` credentials are present on this host).
- **RAGAS evaluation** — [`Sheryl-shiyi/proj-poc-RAGAS`](https://github.com/Sheryl-shiyi/proj-poc-RAGAS)
  against this running stack.
