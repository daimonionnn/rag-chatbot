#!/usr/bin/env bash
# Full RAGAS benchmark: every model under test is generated, then scored by a
# fixed judge (the PoC uses one judge for all runs so the numbers are
# comparable). Each model is independent — a failure in one does not stop the
# rest, and finished results are never lost.
#
# Usage:  rag-eval/run_all.sh [JUDGE] [MODEL ...]
# Runs in the foreground; launch it detached with nohup/setsid for the ~16 h job.
set -u

cd "$(dirname "$0")/.."
# Stream progress into the log instead of block-buffering it, so a multi-hour
# run can be monitored while it happens.
export PYTHONUNBUFFERED=1
PY=.client06-venv/bin/python

JUDGE="${1:-ollama/gemma3:27b-it-fp16}"; [ $# -gt 0 ] && shift
MODELS=("${@:-}")
if [ -z "${MODELS[*]}" ]; then
    MODELS=(
        ollama/gemma3:27b-it-fp16
        ollama/gemma4:31b-it-bf16
        ollama/qwen3.6:27b-mtp-bf16
    )
fi

slug() { echo "$1" | sed 's#[^A-Za-z0-9._-]#_#g'; }
log()  { echo "[$(date '+%F %T')] $*"; }

log "benchmark start | judge=$JUDGE | models: ${MODELS[*]}"
START=$(date +%s)

for MODEL in "${MODELS[@]}"; do
    SLUG=$(slug "$MODEL")
    DATA="rag-eval/results/eval_data__${SLUG}.json"
    log "===== $MODEL : generation ====="
    if [ -s "$DATA" ]; then
        log "generation already done ($DATA) — skipping"
    else
        "$PY" rag-eval/run_rag.py "$MODEL" \
            && log "generation done -> $DATA" \
            || { log "GENERATION FAILED for $MODEL — skipping to next model"; continue; }
    fi

    log "===== $MODEL : scoring (judge=$JUDGE) ====="
    "$PY" rag-eval/score_ragas.py "$DATA" "$JUDGE" \
        && log "scoring done for $MODEL" \
        || log "SCORING FAILED for $MODEL"
done

log "benchmark finished | elapsed $(( ($(date +%s) - START) / 60 )) min"
