#!/usr/bin/env bash
# Start every piece of the local RAG stack: host Ollama, the NeMo Guardrails
# proxy, and the llamastack + rag-ui containers. Idempotent — safe to re-run;
# each step starts only what isn't already up, and leaves the rest alone.
#
# This exists because forgetting one piece breaks things silently and
# confusingly downstream. Concretely: nemo-guardrails got stopped (along with
# everything else) to free VRAM during a benchmark run, and only llamastack +
# rag-ui were restarted afterwards — so Ollama and every ollama/* model worked
# fine, while every nemo/* model in the UI answered with a generic HTTP 500
# and nothing in the chatbot's own logs said "the guardrails container isn't
# running". This script starts all four pieces together so that can't happen
# by omission again.
#
# Building images and pulling models is SETUP.md's job, not this script's —
# it only starts what already exists. Ingestion is likewise separate (running
# it again would create duplicate vector stores), see README.md.
#
# Usage: ./start-stack.sh
set -euo pipefail
cd "$(dirname "$0")"

export PATH="$HOME/.local/bin:$PATH"
OLLAMA_URL_FOR_CONTAINERS="http://172.17.0.1:11434"   # podman bridge gateway
NEMO_NETWORK="local_rag-network"

log() { printf '%-7s %s\n' "$1" "$2"; }
up()  { curl -sf --max-time 2 "$1" >/dev/null 2>&1; }

# --- 0. sanity: the images this script starts must already exist -----------
for img in "docker.io/llamastack/distribution-ollama:0.2.9" "localhost/nemo-guardrails:local"; do
    podman image exists "$img" || {
        echo "ERROR: image $img not found — build it first (see SETUP.md / GUARDRAILS.md)." >&2
        exit 1
    }
done
command -v ollama >/dev/null || {
    echo "ERROR: ollama is not installed — see SETUP.md." >&2
    exit 1
}

# --- 1. host Ollama, listening on all interfaces, context capped -----------
if up http://localhost:11434/api/version; then
    log OK "ollama already listening on :11434"
else
    if systemctl is-active --quiet ollama 2>/dev/null; then
        echo "ERROR: systemd's ollama.service is active and binds 127.0.0.1," \
             "which containers cannot reach (see BUGS.md E3). Disable it first:" \
             "  sudo systemctl disable --now ollama" >&2
        exit 1
    fi
    log START "ollama serve (0.0.0.0:11434, context capped at 32768)"
    OLLAMA_HOST=0.0.0.0:11434 OLLAMA_KEEP_ALIVE=60m OLLAMA_CONTEXT_LENGTH=32768 \
        nohup ollama serve > ollama-serve.log 2>&1 &
    disown
    for _ in $(seq 1 30); do up http://localhost:11434/api/version && break; sleep 1; done
fi

# --- 2. NeMo Guardrails proxy ------------------------------------------------
if up http://localhost:9000/v1/rails/configs; then
    log OK "nemo-guardrails already up on :9000"
elif podman container exists nemo-guardrails; then
    log START "nemo-guardrails (existing container)"
    podman start nemo-guardrails >/dev/null
    for _ in $(seq 1 30); do up http://localhost:9000/v1/rails/configs && break; sleep 1; done
else
    log CREATE "nemo-guardrails (new container)"
    podman run -d --name nemo-guardrails --network "$NEMO_NETWORK" -p 9000:9000 \
        -e OPENAI_API_KEY=dummy \
        -e MAIN_MODEL_BASE_URL="$OLLAMA_URL_FOR_CONTAINERS/v1" \
        localhost/nemo-guardrails:local >/dev/null
    for _ in $(seq 1 30); do up http://localhost:9000/v1/rails/configs && break; sleep 1; done
fi

# --- 3. llamastack + rag-ui ---------------------------------------------------
log START "llamastack + rag-ui (podman-compose up -d is a no-op if already running)"
(
    cd RAG/deploy/local
    OLLAMA_URL="$OLLAMA_URL_FOR_CONTAINERS" TAVILY_SEARCH_API_KEY=disabled \
        podman-compose -f podman-compose.yml -f ../../../compose-model-override.yml \
        up -d llamastack rag-ui
)
echo -n "waiting for llamastack "
for _ in $(seq 1 60); do up http://localhost:8321/v1/health && break; echo -n "."; sleep 2; done
echo ""

# --- 4. report ---------------------------------------------------------------
echo ""
echo "=== status ==="
curl -s -o /dev/null -w "  ollama          :11434  HTTP %{http_code}\n" http://localhost:11434/api/version
curl -s -o /dev/null -w "  nemo-guardrails :9000   HTTP %{http_code}\n" http://localhost:9000/v1/rails/configs
curl -s -o /dev/null -w "  llamastack      :8321   HTTP %{http_code}\n" http://localhost:8321/v1/health
curl -s -o /dev/null -w "  rag-ui          :8501   HTTP %{http_code}\n" http://localhost:8501/
echo ""
echo "UI: http://localhost:8501"
