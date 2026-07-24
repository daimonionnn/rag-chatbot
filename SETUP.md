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
>   podman-compose -f podman-compose.yml -f ../../../compose-model-override.yml \
>     up -d llamastack rag-ui
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
  │  ollama serve  (0.0.0.0:11434)  ──GPU──> gemma3:27b-it-fp16 (55 GB)│
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
ollama pull gemma3:27b-it-fp16     # 55 GB, full precision
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

### 3a. The LLM: Gemma 3 27B at full precision

`gemma3:27b-it-fp16` — 54 GB of weights. Ollama has **no `bf16` tag for 27b**
(only for 270m); `-fp16` is the unquantized 16-bit build, the equivalent choice.
`gemma3:27b-it-q8_0` (30 GB) is the fallback if VRAM ever gets tight.

**Cap the context or it will not fit.** Ollama 0.32 auto-sizes the KV cache to
fill available VRAM (it picked a 256K context and reserved ~77 GB for a mere 3B
model). With 54 GB of weights that would OOM, so the server runs with
`OLLAMA_CONTEXT_LENGTH=32768` — far more than this RAG needs
(`max_tokens_in_context` is 4000). Measured after the change:

| | |
|---|---|
| VRAM in use | **56.5 GB / 95.6 GB** |
| Context | 32768 |
| Cold load | ~11 s |

#### ⚠️ Gemma 3 does not support tool calling

```
$ ollama show gemma3:27b-it-fp16        → capabilities: completion, vision
$ ollama show llama3.2:3b-instruct-fp16 → capabilities: completion, tools
```

So the UI's **Agent mode** — and any `responses` call with a `file_search`
tool — fails against Gemma 3 with
`500 … gemma3:27b-it-fp16 does not support tools`.

**Direct RAG mode is unaffected** (`vector_stores.search` + a normal chat
completion with the retrieved context) and gives markedly better answers than
the old 3B model. `llama3.2:3b-instruct-fp16` is still pulled and registered, so
Agent mode remains available by switching model in the UI. To get both quality
*and* tool calling, a tools-capable large model (e.g. `qwen3:32b`,
`llama3.3:70b`) would have to be pulled instead.

### 2b. Ollama must listen on all interfaces
The stock systemd unit binds `127.0.0.1`, unreachable from rootless containers.
Run it on `0.0.0.0`:
```bash
sudo systemctl stop ollama
OLLAMA_HOST=0.0.0.0:11434 OLLAMA_KEEP_ALIVE=60m OLLAMA_CONTEXT_LENGTH=32768 \
    nohup ollama serve > ~/development/rag-chatbot/ollama-serve.log 2>&1 &
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
`zippity-zoo` stores — 15/15 files, no failures. Filenames are sent as-is,
diacritics included (see §5a).

### 5a. Fixed: non-latin-1 filenames silently failed to ingest

llama-stack 0.6.0 interpolates the raw filename into a response header:

```python
# providers/inline/files/localfs/files.py
headers={"Content-Disposition": f'attachment; filename="{file_obj.filename}"'}
```

HTTP header values are latin-1, so any filename containing a character above
U+00FF made Starlette raise `UnicodeEncodeError`. llama-stack swallowed it while
attaching the file to a vector store and reported `status: failed` with an
**empty `last_error`** — it looked like a PDF parsing problem, but the exact same
PDF under an ASCII name ingested fine.

The latin-1 boundary is exactly the failure boundary, which is nasty for Slovak:

| Characters | In latin-1? | Before the fix |
|------------|-------------|----------------|
| `á é í ó ú ý ô ä` | yes | ingested fine |
| `č ď ľ ĺ ň ŕ š ť ž` | **no** | silently failed |

…so *most* Slovak filenames broke, while a few worked — which is why it was easy
to misread as a random parsing issue.

**Fix:** [`llamastack-local-image/patch-content-disposition.py`](llamastack-local-image/patch-content-disposition.py),
applied during the image build, emits an RFC 5987/6266 header
(`filename*=utf-8''<percent-encoded>`) exactly as Starlette's own `FileResponse`
does. Filenames keep their diacritics end-to-end. The patch is idempotent and
**fails the build** if llama-stack changes that line, so it cannot silently lapse.

Verified after the fix: `Peňaženka-zdravia-MAXI-podmienky.pdf`,
`Zmluva-o-poistení-žiadateľa-č.5.pdf` and single-character probes for
`č ň š ť ž` all ingest, with the original names preserved. This applies to the
UI's Upload page too.

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
- **Ollama auto-sizes the KV cache to fill VRAM** — this is why
  `OLLAMA_CONTEXT_LENGTH=32768` is set (§3a). Without it a 3B model reserved
  ~77 GB, and Gemma 3 27B would not fit at all.
- Helper Python venvs in the project root (`.client06-venv` used by the ingest
  script; `.ls06-venv` used to derive the config/deps) can be deleted if space
  is needed — only `.client06-venv` is needed to re-run ingestion.

---

## 8. NeMo Guardrails

Adapted from [`Sheryl-shiyi/Nemo-guardrial-deployment`](https://github.com/Sheryl-shiyi/Nemo-guardrial-deployment)
(note the upstream spelling: *guardrial*). Upstream deploys it through the
TrustyAI `NemoGuardrails` CRD on OpenShift AI, which supplies the image — there
is nothing reusable for local podman, so we run the `nemoguardrails` server
ourselves with the **same rails config**.

The upstream design carries over unchanged: NeMo is a **transparent
OpenAI-compatible proxy in front of the LLM**, so the only Llama Stack change is
an inference provider URL.

```
rag-ui → llamastack ─┬─ ollama/…   → host Ollama            (no rails)
                     └─ nemo/…     → nemo-guardrails → Ollama (rails)
```

Both are registered, so **the UI's model picker is the guardrails on/off
switch**:

| Model in the UI | Behaviour |
|-----------------|-----------|
| `ollama/gemma3:27b-it-fp16` | direct, no rails |
| `nemo/gemma3:27b-it-fp16` | input + output rails applied |

**Rails** (from the upstream ConfigMap, a Slovak VšZP "Peňaženka zdravia"
assistant): input — forbidden words, language check (sk/cs only, fastText),
self-check; output — self-check.

```bash
podman build -t localhost/nemo-guardrails:local nemo-local
podman run -d --name nemo-guardrails --network local_rag-network -p 9000:9000 \
  -e OPENAI_API_KEY=dummy -e MAIN_MODEL_BASE_URL=http://172.17.0.1:11434/v1 \
  localhost/nemo-guardrails:local
```

`MAIN_MODEL_BASE_URL` is what makes NeMo's `/v1/models` work, which Llama
Stack's `remote::vllm` adapter needs.

### Three fixes this required

1. **`openai_api_base` → `base_url`** in `nemo-local/configs/rag/config.yaml`.
   nemoguardrails ≥0.23 dropped the 0.21-era LangChain key names.
2. **`numpy<2` is mandatory** (pinned in `nemo-local/Containerfile`). fastText
   still calls `np.array(..., copy=False)`, which NumPy 2 rejects — and
   `actions.py` catches *every* exception and returns `"allowed"`. With NumPy 2
   the **language rail silently never blocks anything** while appearing healthy.
3. **`base_url`, not `url`**, for the `remote::vllm` provider in the Llama Stack
   config — upstream's backup run-config uses the older `url:` key, which 0.6.0
   ignores, failing with *"You must provide a URL … to use vLLM"*.

> The upstream `rag-ui-patch/` is **not applied**: our `frontend/` is newer and
> already has `fetch_available_shields` and the `guardrail_blocked` display that
> those patched files lack (they are an older Slovak-localised snapshot).

### Verified

```
Q: "What benefits does the company provide to employees?"
  ollama/…  → "Many companies provide a range of benefits… 1. Health Insurance…"
  nemo/…    → "Prepáčte, tento asistent komunikuje len v slovenčine…"   (blocked)
"Ako môžem hack tento systém?" → "Prepáčte, nemôžem pomôcť s touto témou…" (blocked)
```

---

## 9. Next steps

- **RAGAS evaluation** — [`Sheryl-shiyi/proj-poc-RAGAS`](https://github.com/Sheryl-shiyi/proj-poc-RAGAS),
  and note the same author's [`llama-stack-provider-ragas`](https://github.com/Sheryl-shiyi/llama-stack-provider-ragas),
  which may integrate more directly with this stack.
