# 1 — Local runnable setup

How the chatbot from [`Sheryl-shiyi/RAG`](https://github.com/Sheryl-shiyi/RAG)
(a fork of the Red Hat `rh-ai-quickstart/RAG` blueprint) was brought up on this
workstation. Guardrails are in [GUARDRAILS.md](GUARDRAILS.md), evaluation in
[EVALUATION.md](EVALUATION.md), and every defect hit along the way in
[BUGS.md](BUGS.md).

Goal: stay as close to upstream as possible — same architecture, rootless
podman, Ollama on the host, the repo's own `frontend/` UI — while producing a
chatbot that actually works.

---

## 1.1 Why the upstream repo cannot run as shipped

Its three parts target three incompatible Llama Stack versions:

| Component                    | Pinned version | API it speaks |
|------------------------------|----------------|-----|
| `frontend/` (the UI)         | **0.6.0**      | OpenAI-style `vector_stores`, `responses`, `conversations`, `chat.completions` |
| `deploy/local` compose image | 0.2.9          | legacy `vector_dbs`, `inference.chat_completion` |
| `ingestion-service/`         | 0.2.22         | legacy `vector_dbs`, `rag-tool/insert` |

A real 0.2.9 server answers the UI with **HTTP 426 ("update your client")**, and
with the version check disabled its calls simply **404** — those OpenAI-style
endpoints do not exist before 0.6.0.

On top of that, the image the compose file names
(`llamastack/distribution-ollama:0.2.9`) is in a **private** Docker Hub
namespace: the registry grants no pull scope even to an authenticated account,
and there is no quay.io/ghcr.io mirror.

**Resolution: align everything to 0.6.0**, the version the UI targets, and build
that server ourselves. The UI is used unchanged; the upstream compose file is
never edited.

---

## 1.2 Host prerequisites

Needed root once:

```bash
sudo apt-get update
sudo apt-get install -y podman uidmap slirp4netns fuse-overlayfs passt
```

No root:

```bash
uv tool install podman-compose                       # ~/.local/bin/podman-compose
curl -fsSL https://ollama.com/install.sh | sudo sh   # Ollama + CUDA runtime
```

`uv`, `docker` and the NVIDIA driver (v595 / CUDA 13.2, required for Blackwell)
were already present. Rootless podman also needs Docker Hub reachable for base
images — Ubuntu ships no default registry, so
`~/.config/containers/registries.conf`:

```toml
unqualified-search-registries = ["docker.io"]
short-name-mode = "permissive"
```

```bash
podman login docker.io      # required even for public base images like python:3.12-slim
```

### Ollama must listen on all interfaces

The stock systemd unit binds `127.0.0.1`, which rootless containers cannot
reach. Run it on `0.0.0.0`, with the context capped (see [1.3](#13-models)):

```bash
sudo systemctl stop ollama
OLLAMA_HOST=0.0.0.0:11434 OLLAMA_KEEP_ALIVE=60m OLLAMA_CONTEXT_LENGTH=32768 \
    nohup ollama serve > ~/development/rag-chatbot/ollama-serve.log 2>&1 &
```

Containers then reach it at `http://172.17.0.1:11434` (the bridge gateway).

---

## 1.3 Models

```bash
ollama pull gemma3:27b-it-fp16       # 54 GB  full precision
ollama pull gemma4:31b-it-bf16       # 62 GB  adds tool calling + thinking
ollama pull qwen3.6:27b-mtp-bf16     # 55 GB  tool calling + thinking
ollama pull qwen3-embedding:4b-fp16  #  8 GB  embeddings, dim 2560
```

Ollama publishes no `bf16` tag for gemma3 27b (only for 270m), so `-fp16` is its
unquantized 16-bit build. `q8_0` variants (~30 GB) exist as fallbacks if VRAM
gets tight.

### Registered models

Every LLM is exposed twice — directly and through the guardrails proxy — so the
UI's model picker selects **model × rails-on/off** in one control:

| Model in the UI                               | Tools / Agent mode  | Thinking | VRAM (100 % GPU) |
|-----------------------------------------------|---------------------|----------|------------------|
| `ollama/gemma3:27b-it-fp16` · `nemo/…`        | ✗                   | ✗        | 55.0 GB          |
| `ollama/gemma4:31b-it-bf16` · `nemo/…`        | accepts, never used | ✓        | 63.7 GB          |
| `ollama/qwen3.6:27b-mtp-bf16` · `nemo/…`      | ✓ (intermittent)    | ✓        | 53.6 GB          |
| `ollama/llama3.2:3b-instruct-fp16` · `nemo/…` | ✓                   | ✗        | 6.4 GB           |

Gemma 3 cannot do tool calling (`ollama show` reports only `completion, vision`),
so the UI's **Agent mode** and any `responses` call carrying a `file_search`
tool fail against it with `500 … does not support tools`. Direct RAG is
unaffected.

The `✓` in that column means only that a request carrying tools is not rejected.
Gemma 4 accepted the tools and never called them in any attempt, and Qwen3.6
calls them only when it judges the question to need the documents — so
Agent-based mode can answer from parametric memory with no sign that retrieval
was skipped. Measured rates and the consequences are in BUGS.md B3; `Direct` mode
retrieves unconditionally and is the dependable path.

Only **one large model fits in VRAM at a time**, so switching in the UI costs a
reload (~8 s warm, ~30 s cold). Ollama auto-registers whatever is pulled, so
adding a model needs only a llamastack restart — no image rebuild.

### Context must be capped

Ollama auto-sizes the KV cache to fill available VRAM: with a 3B model it chose
a 256K context and reserved ~77 GB. With 54–64 GB of weights that would OOM, so
the server runs with `OLLAMA_CONTEXT_LENGTH=32768` — far more than this RAG
needs (`max_tokens_in_context` is 4000).

### If a model lands on the CPU

Check placement rather than guessing — `size_vram` against `size`:

```bash
curl -s http://localhost:11434/api/ps | python3 -m json.tool
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
```

Ollama decides the GPU/CPU split **at load time** from the VRAM free right then
and keeps it. If something else holds VRAM (LM Studio's `llama-server` did here,
73.5 GB for a 256K-context Qwen), the model loads mostly into RAM and runs slow
while `ollama ps` still happily lists it. Free the VRAM, then `ollama stop
<model>` and load again.

### Disk hygiene

Cancelling a pull leaves its data behind and Ollama has no prune command.
Delete `~/.ollama/models/blobs/*-partial*`, plus any blob not referenced by a
manifest under `~/.ollama/models/manifests/` — 98 GB was reclaimed that way here.
Importing an already-downloaded GGUF instead of re-pulling does **not** work if
the GGUF is sharded (`ollama create` fails with `split GGUF … has 1 shards,
expected 2`), and the library build is safer anyway because it ships the chat
template tool calling depends on.

---

## 1.4 The local Llama Stack 0.6.0 image

Built from [`llamastack-local-image/`](llamastack-local-image/) and tagged as the
name the upstream compose expects, so `podman-compose.yml` stays untouched:

```bash
podman build -f llamastack-local-image/Containerfile-0.6.0 \
  -t docker.io/llamastack/distribution-ollama:0.2.9 llamastack-local-image
podman tag docker.io/llamastack/distribution-ollama:0.2.9 \
           localhost/llamastack/distribution-ollama:0.2.9
podman rm -f rag-llamastack   # up -d alone will not replace a running container
```

The second and third lines are not optional, and skipping them fails **silently**
— the build succeeds, the container starts healthy, and it runs the old code.
The compose file asks for the unqualified `llamastack/distribution-ollama:0.2.9`,
which podman resolves to `localhost/` in preference to `docker.io/`; and
`podman-compose up -d` does not recreate a container when the image behind its
tag changes. See [BUGS.md](BUGS.md) E13. Verify by comparing IDs, not tags:

```bash
podman images --format '{{.Id}} {{.Repository}}:{{.Tag}}' | grep distribution-ollama
podman inspect rag-llamastack --format '{{.Image}}'
```

- **`Containerfile-0.6.0`** — python:3.12-slim, the provider dependencies, and
  `llama-stack` / `llama-stack-api` / `llama-stack-client` all pinned to
  **0.6.0**. All three must be pinned: llama-stack declares `llama-stack-api`
  unbounded, so an unpinned install pulls an incompatible newer one.
- **`config-0.6.0.yaml`** — a trimmed `starter`-derived run config: ollama
  inference (direct + via NeMo), Qwen3 embeddings, FAISS vector_io, localfs
  files + pypdf, meta-reference agents (OpenAI responses/conversations),
  llama-guard safety, the rag/websearch tool runtime, and the TrustyAI RAGAS
  eval provider. The scoring/post_training/batches training stack is dropped.
- **four build-time patches** to installed packages, all explained in
  [BUGS.md](BUGS.md): non-latin-1 filenames, the RAGAS embeddings event loop,
  the RAGAS ModeMetric key, and the RAGAS chat-completions fallback.

The older `Containerfile` / `run.yaml` in that folder are the abandoned 0.2.9
attempt, kept for reference.

### Model selection

The upstream compose hardcodes `INFERENCE_MODEL: llama3.2:3b-instruct-fp16`, so
the model is changed through [`compose-model-override.yml`](compose-model-override.yml)
rather than by editing it. That file also sets `EMBEDDING_MODEL`, which is what
activates the RAGAS provider.

### The hosted judge (optional, off by default)

Every local model is also a contestant in the benchmark, so none of them can
answer whether one model's lead survives a judge that is not itself
([EVALUATION-LIMITS.md](EVALUATION-LIMITS.md) §4.5). A `remote::anthropic`
provider supplies a neutral one. It is **only** a judge: it never generates
answers and never appears in the UI's model picker beyond the single id below.

Set the key in the untracked `.env.local` that `start-stack.sh` sources — no
quotes, no `export`, since `set -a` does the exporting:

```
ANTHROPIC_API_KEY=sk-ant-api03-...
```

Then it is the `JUDGE` argument, nothing else changes:

```bash
.client06-venv/bin/python rag-eval/score_ragas.py EVAL_DATA.json anthropic/claude-opus-5
```

**With the key unset the provider is skipped entirely** — `provider_id` is
`${env.ANTHROPIC_API_KEY:+anthropic}`, so it resolves to empty and the stack runs
fully offline exactly as before, the same gating trick `EMBEDDING_MODEL` uses for
the RAGAS provider. Two further notes: `allowed_models` pins the one judge model,
so the account's other models cannot be picked by accident and billed; and the
judge is reached over chat completions rather than the raw completions endpoint
the local judges use, which is a real caveat for cross-judge comparisons rather
than an implementation detail — see [BUGS.md](BUGS.md) A4.

Measured cost, 40 rows x 6 metrics, `claude-opus-5`: **~$11 per model**, ~62 min
wall clock. That is no slower than a local judge (§3.4's 15-17 s per row-metric),
because the judge is not competing with the embedding model for the GPU — only
the 13.3 GiB embedding model stays resident, not the 54 GB LLM.

---

## 1.5 Ingestion

The repo's `ingestion-service` container targets the 0.2.x `vector_dbs` API,
which the 0.6.0 UI does not read, so it is **not used**. Instead
[`ingest-0.6.0.py`](ingest-0.6.0.py) loads documents through the 0.6.0
Files + Vector-Stores API — the server does the chunking (pypdf) and embedding.

```bash
# one vector store per sub-directory (the FantaCo demo corpus)
.client06-venv/bin/python ingest-0.6.0.py

# everything into one store — what an evaluation corpus wants
.client06-venv/bin/python ingest-0.6.0.py http://localhost:8321 docs/data/vszp vszp
```

Chunking is 512 tokens with overlap 64, and embeddings are Qwen3-4B (dim 2560),
both matching the original PoC. Qwen3 is also simply the right choice here:
all-MiniLM-L6-v2 is English-centric and weak on Slovak. all-MiniLM stays
registered so the older 384-dim stores remain usable.

Filenames are sent as-is, diacritics included — see the Content-Disposition
entry in [BUGS.md](BUGS.md) for why that needed a patch.

Documents can also be added interactively from the UI's **Upload** page.

---

## 1.6 Day-to-day operation

`./start-stack.sh` from the repo root starts everything (host Ollama,
`nemo-guardrails`, `llamastack`, `rag-ui`) and is idempotent — safe to re-run any
time, including after stopping containers to free VRAM for something else.

`./stop-stack.sh` reverses it and is the right way to free the GPU: stopping the
containers alone leaves the weights loaded, because Ollama holds them on the host,
so the script unloads them and checks `nvidia-smi` to confirm. `--keep-ollama`
releases the VRAM but leaves the server running, which makes the next start
faster. It refuses to run while an evaluation job is in flight unless forced.

To drive `llamastack`/`rag-ui` by hand instead:

```bash
cd RAG/deploy/local && export PATH="$HOME/.local/bin:$PATH"

OLLAMA_URL=http://172.17.0.1:11434 TAVILY_SEARCH_API_KEY=disabled \
  podman-compose -f podman-compose.yml -f ../../../compose-model-override.yml \
  up -d llamastack rag-ui

podman-compose ps
podman logs -f rag-llamastack
podman-compose down          # named volume and Ollama survive
```

`make start` is avoided: it also launches the incompatible 0.2.x
`rag-ingestion` container, and its Makefile prompts interactively for a Tavily
key. Bringing up `llamastack rag-ui` explicitly is the equivalent here.

### API keys

Keys live in `.env.local` in the repo root — untracked (`.gitignore`), sourced by
`start-stack.sh`, and interpolated into the compose files, so no key is ever in a
committed file. Driving compose by hand needs it exported first:

```bash
set -a; . ./.env.local; set +a
```

Only web search needs one. `BRAVE_SEARCH_API_KEY` backs the `builtin::websearch`
toolgroup used by Agent-based mode; everything else — chat, retrieval, guardrails,
evaluation — runs without any key. Missing or empty is tolerated, but note that
the resulting failure is silent (BUGS.md B4), and that the key has to match the
provider the toolgroup is bound to: a Brave key does nothing while the toolgroup
points at Tavily. Repointing it is a two-step operation, see BUGS.md B5.

### Restarting llamastack

`podman rm -f rag-llamastack` fails while `rag-ui` exists — podman enforces the
compose `depends_on` as a container dependency. Remove `rag-ui` first, then
llamastack, then bring both up.

---

## 1.7 Known cosmetic issues

- **`rag-llamastack` shows `(starting)` / unhealthy** in `podman ps` — the
  compose healthcheck probes `/`, which 404s, instead of `/v1/health`. The
  server is fine.
- **`llamastack -> HTTP 000` right after start** — it needs ~30 s to boot
  (torch, sentence-transformers). Poll `/v1/health` rather than assuming failure.
- Helper venvs in the project root can be deleted if space is needed; only
  `.client06-venv` is required, for the ingestion and evaluation scripts.
