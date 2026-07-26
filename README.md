# Enterprise RAG Chatbot — local reproduction

A locally running RAG chatbot with safety guardrails and RAGAS evaluation,
reproduced from three upstream repositories on a single workstation with
**rootless podman** and **Ollama on the host** — no OpenShift, no Kubeflow, no
cluster.

| Upstream | What we take from it |
|----------|----------------------|
| [`Sheryl-shiyi/RAG`](https://github.com/Sheryl-shiyi/RAG) (fork of Red Hat `rh-ai-quickstart/RAG`) | the chatbot: Llama Stack + Streamlit UI + ingestion |
| [`Sheryl-shiyi/Nemo-guardrial-deployment`](https://github.com/Sheryl-shiyi/Nemo-guardrial-deployment) | the input/output safety rails |
| [`Sheryl-shiyi/proj-poc-RAGAS`](https://github.com/Sheryl-shiyi/proj-poc-RAGAS) + [`llama-stack-provider-ragas`](https://github.com/Sheryl-shiyi/llama-stack-provider-ragas) | the evaluation methodology and engine |

None of them runs as shipped on a workstation, and the first one does not run
*at all* as shipped — see [BUGS.md](BUGS.md).

They are referenced, not vendored: nothing inside them is modified, they are
gitignored, and every adaptation lives beside them instead (a compose override,
a locally built image, build-time patches — see [Layout](#layout)). Because
`BUGS.md` and `EVALUATION.md` quote exact line numbers and behaviour from
specific commits, `./fetch-upstream.sh` clones all four **pinned to the commits
everything here was verified against**, rather than whatever upstream happens to
contain today:

```bash
./fetch-upstream.sh
```

Re-running it is a no-op once the clones are at the pinned commits, and it
un-shallows and moves them if a pin is ever updated.

---

## Documentation

| | Document | Contents |
|---|----------|----------|
| 1 | **[SETUP.md](SETUP.md)** | Local runnable setup: prerequisites, the Llama Stack image we build, models, ingestion, day-to-day operation |
| 2 | **[GUARDRAILS.md](GUARDRAILS.md)** | NeMo Guardrails as a transparent proxy, the rails, and how the UI exposes rails-on/off |
| 3 | **[EVALUATION.md](EVALUATION.md)** | RAGAS evaluation through the TrustyAI llama-stack provider, metrics, and the harness |
| 4 | **[EVALUATION-LIMITS.md](EVALUATION-LIMITS.md)** | What the evaluation does *not* measure — measured blind spots (facts vs. fluency, Slovak untested) and a prioritised improvement backlog |
| — | **[BUGS.md](BUGS.md)** | Every defect and trap hit across the project, with the fix |

---

## Architecture

```
                host (Linux, NVIDIA RTX PRO 6000 Blackwell, 96 GB VRAM)
  ┌───────────────────────────────────────────────────────────────────────┐
  │  ollama serve  (0.0.0.0:11434)                                        │
  │    LLMs        gemma3 27B · gemma4 31B · qwen3.6 27B · llama3.2 3B    │
  │    embeddings  qwen3-embedding 4B (dim 2560)                          │
  └───────▲───────────────────────────────────▲───────────────────────────┘
          │ direct                            │ proxied
  ┌───────┴───────────────────┐   ┌───────────┴──────────────┐
  │ rag-llamastack  :8321      │   │ nemo-guardrails  :9000   │
  │ Llama Stack 0.6.0          │   │ input + output rails     │
  │  inference · vector_io      │   └──────────────────────────┘
  │  files · agents · safety    │
  │  eval (TrustyAI RAGAS)      │◄──── rag-eval/ harness
  └───────▲────────────────────┘
          │ 0.6.0 APIs
  ┌───────┴────────────────────┐
  │ rag-ui  :8501  (Streamlit) │   model picker = model × rails on/off
  └────────────────────────────┘
```

Vector data lives in OpenAI-style vector stores (FAISS underneath). Ollama
serves both the chat LLMs and the embedding model; everything else runs in
rootless podman containers on the `local_rag-network`.

---

## Quick start

Assumes the one-time setup in [SETUP.md](SETUP.md) is done (podman, Ollama, the
locally built Llama Stack image, models pulled).

```bash
# 0. pinned upstream clones (see "Upstream" above)
./fetch-upstream.sh

# 1. host Ollama, listening on all interfaces, with a capped context
OLLAMA_HOST=0.0.0.0:11434 OLLAMA_KEEP_ALIVE=60m OLLAMA_CONTEXT_LENGTH=32768 \
    nohup ollama serve > ~/development/rag-chatbot/ollama-serve.log 2>&1 &

# 2. guardrails proxy (optional — only needed for the nemo/* models)
podman run -d --name nemo-guardrails --network local_rag-network -p 9000:9000 \
  -e OPENAI_API_KEY=dummy -e MAIN_MODEL_BASE_URL=http://172.17.0.1:11434/v1 \
  localhost/nemo-guardrails:local

# 3. the chatbot
cd RAG/deploy/local && export PATH="$HOME/.local/bin:$PATH"
OLLAMA_URL=http://172.17.0.1:11434 TAVILY_SEARCH_API_KEY=disabled \
  podman-compose -f podman-compose.yml -f ../../../compose-model-override.yml \
  up -d llamastack rag-ui

# 4. load documents once
.client06-venv/bin/python ingest-0.6.0.py                       # demo corpus
.client06-venv/bin/python ingest-0.6.0.py http://localhost:8321 docs/vszp/data vszp
```

Open **<http://localhost:8501>**.

```bash
curl -s http://localhost:8321/v1/health                          # {"status":"OK"}
curl -s http://localhost:8321/v1/models                          # LLMs + embeddings
curl -s http://localhost:8321/v1/vector_stores                   # ingested corpora
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8501   # UI -> 200
```

---

## Layout

```
llamastack-local-image/   the Llama Stack 0.6.0 image we build, its run config,
                         and two source patches applied at build time
nemo-local/              the NeMo Guardrails server image and its rails config
rag-eval/                RAGAS harness (run_rag.py -> score_ragas.py)
ingest-0.6.0.py          document ingestion via the 0.6.0 Files/Vector-Stores API
compose-model-override.yml  overrides the model hardcoded upstream, leaving the
                            upstream compose file untouched
fetch-upstream.sh        clones the four repos below, pinned to verified commits
RAG/ nemo-guardrails/ ragas-poc/ ragas-provider/   upstream clones (gitignored)
docs/                    internal documents (gitignored)
```

Nothing inside the upstream clones is modified. Every adaptation lives beside
them: a compose override, a locally built image tagged as the name the upstream
compose expects, and build-time patches to installed packages.
