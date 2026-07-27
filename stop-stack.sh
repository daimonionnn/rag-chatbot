#!/usr/bin/env bash
# Stop every piece of the local RAG stack and hand the GPU back: rag-ui,
# llamastack, the NeMo Guardrails proxy, and host Ollama. The mirror of
# start-stack.sh, and idempotent the same way — anything already stopped is
# reported and skipped, never treated as an error.
#
# Freeing VRAM is the point, not a side effect. Only one 27B-class model fits on
# this card at a time (SETUP.md 1.3), so anything else wanting the GPU — LM
# Studio, a training run, a different model — needs these weights out of VRAM
# first. Stopping the containers alone does NOT do that: the weights are held by
# Ollama on the host, not by any container, so the models are unloaded explicitly
# here and the result is verified against nvidia-smi rather than assumed.
#
# Usage:
#   ./stop-stack.sh                 stop everything, including ollama serve
#   ./stop-stack.sh --keep-ollama   unload the models but leave the server up
#                                   (frees the VRAM; makes the next start faster)
#   ./stop-stack.sh --force         stop even while an evaluation job is running
set -uo pipefail
cd "$(dirname "$0")"

export PATH="$HOME/.local/bin:$PATH"

KEEP_OLLAMA=""
FORCE=""
for arg in "$@"; do
    case "$arg" in
        --keep-ollama) KEEP_OLLAMA=1 ;;
        --force)       FORCE=1 ;;
        -h|--help)     sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg (try --help)" >&2; exit 1 ;;
    esac
done

log() { printf '%-7s %s\n' "$1" "$2"; }

vram_used() {   # MiB currently allocated on the GPU, or empty if no nvidia-smi
    command -v nvidia-smi >/dev/null || return 0
    nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1
}

# --- 0. refuse to pull the rug out from under a running benchmark -------------
# A full evaluation run is ~12 h and talks to both Ollama and llamastack the
# whole time; stopping either mid-run loses it. Cheap check, expensive mistake.
#
# `pgrep -f` matches whole command lines, so it also matches any ancestor shell
# whose command line happens to mention these paths — invoke this script from a
# one-liner that names score_ragas.py and it reports its own caller as a running
# job. Same root cause as BUGS.md E10. So the ancestor chain is walked and
# excluded before deciding.
eval_jobs() {
    local skip=" " pid=$$
    while [[ -n "$pid" && "$pid" != "0" && "$pid" != "1" ]]; do
        skip+="$pid "
        pid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
    done
    local p
    for p in $(pgrep -f "rag-eval/(run_all\.sh|run_rag\.py|score_ragas\.py)" 2>/dev/null); do
        [[ "$skip" == *" $p "* ]] || echo "$p"
    done
}

if [[ -z "$FORCE" ]]; then
    JOBS=$(eval_jobs)
    if [[ -n "$JOBS" ]]; then
        echo "ERROR: an evaluation job is still running:" >&2
        ps -o pid=,etime=,cmd= -p $(echo "$JOBS" | tr '\n' ',' | sed 's/,$//') 2>/dev/null \
            | cut -c1-120 | sed 's/^/  /' >&2
        echo "Stopping the stack now would lose it. Wait, or re-run with --force." >&2
        exit 1
    fi
fi

VRAM_BEFORE=$(vram_used)

# --- 1. containers, in reverse dependency order -------------------------------
# rag-ui first: podman enforces the compose `depends_on` as a real dependency,
# so llamastack cannot be removed while rag-ui exists (BUGS.md E9). Stopping
# follows the same order to keep the UI from erroring at anyone still on it.
for c in rag-ui rag-llamastack nemo-guardrails; do
    if ! podman container exists "$c" 2>/dev/null; then
        log SKIP "$c (no such container)"
    elif [[ "$(podman inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" == "true" ]]; then
        log STOP "$c"
        podman stop "$c" >/dev/null 2>&1 || log WARN "$c did not stop cleanly"
    else
        log OK "$c already stopped"
    fi
done

# --- 2. unload the models — this is what actually frees VRAM ------------------
if curl -sf --max-time 2 http://localhost:11434/api/version >/dev/null 2>&1; then
    LOADED=$(curl -s --max-time 5 http://localhost:11434/api/ps 2>/dev/null \
             | python3 -c 'import json,sys
try: print("\n".join(m["name"] for m in json.load(sys.stdin).get("models", [])))
except Exception: pass' 2>/dev/null)
    if [[ -z "$LOADED" ]]; then
        log OK "no models loaded in VRAM"
    else
        while read -r m; do
            [[ -n "$m" ]] || continue
            log UNLOAD "$m"
            ollama stop "$m" >/dev/null 2>&1 || log WARN "could not unload $m"
        done <<< "$LOADED"
    fi
else
    log SKIP "ollama not responding on :11434 — nothing to unload"
fi

# --- 3. the Ollama server itself ---------------------------------------------
if [[ -n "$KEEP_OLLAMA" ]]; then
    log KEEP "ollama serve (--keep-ollama)"
else
    # Match the process by exact name rather than `pkill -f ollama`, which is
    # broad enough to match this script's own command line and kill the shell
    # running it (BUGS.md E10). `ollama stop` above is a client call and has
    # already exited, so anything still named `ollama` is the server.
    PIDS=$(pgrep -x ollama 2>/dev/null)
    if [[ -z "$PIDS" ]]; then
        log OK "ollama serve not running"
    elif systemctl is-active --quiet ollama 2>/dev/null; then
        log SKIP "ollama runs under systemd — leaving it to systemctl"
    else
        log STOP "ollama serve (pid $(echo "$PIDS" | tr '\n' ' '))"
        kill $PIDS 2>/dev/null
        for _ in $(seq 1 20); do
            pgrep -x ollama >/dev/null || break
            sleep 0.5
        done
        pgrep -x ollama >/dev/null && log WARN "ollama still running after SIGTERM"
    fi
fi

# --- 4. report what was actually freed ----------------------------------------
VRAM_AFTER=$(vram_used)
echo ""
echo "=== status ==="
for p in "ollama :11434 http://localhost:11434/api/version" \
         "nemo   :9000  http://localhost:9000/v1/rails/configs" \
         "llama  :8321  http://localhost:8321/v1/health" \
         "rag-ui :8501  http://localhost:8501/"; do
    set -- $p
    if curl -sf --max-time 2 "$3" >/dev/null 2>&1; then
        printf '  %-7s %-6s still up\n' "$1" "$2"
    else
        printf '  %-7s %-6s down\n' "$1" "$2"
    fi
done
if [[ -n "${VRAM_BEFORE:-}" && -n "${VRAM_AFTER:-}" ]]; then
    echo ""
    printf '  VRAM %s MiB -> %s MiB (freed %s MiB)\n' \
        "$VRAM_BEFORE" "$VRAM_AFTER" "$(( VRAM_BEFORE - VRAM_AFTER ))"
    # Unloading is asynchronous on Ollama's side; a large residue usually means
    # something outside this stack is holding the card (SETUP.md 1.3).
    if (( VRAM_AFTER > 2000 )); then
        echo "  NOTE: $VRAM_AFTER MiB still allocated — check what else holds the GPU:"
        echo "        nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv"
    fi
fi
