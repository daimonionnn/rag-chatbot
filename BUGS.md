# Bugs, traps and fixes

Everything that had to be diagnosed to get this stack running, across all three
phases. Grouped by cause rather than by phase, because the same causes recur.

Two patterns account for most of the time spent:

1. **Unpinned dependencies.** Every upstream here declares at least one
   dependency with no version bound. They were correct on the day they were
   released and resolve to something incompatible today. Six separate failures
   below are this.
2. **Silently swallowed exceptions.** Two failures reported *success* or an
   *empty error* while doing nothing at all. These are the expensive ones:
   nothing looks broken, so you only find them by checking that the feature
   actually does its job.

Every defect in section A is fixed by a build-time patch, so the full upstream
feature set — including all six RAGAS metrics — is available.

---

## A. Real upstream defects, patched

### A1. Non-latin-1 filenames silently fail to ingest — **Slovak-critical**

`llama-stack 0.6.0`, `providers/inline/files/localfs/files.py`:

```python
headers={"Content-Disposition": f'attachment; filename="{file_obj.filename}"'}
```

HTTP header values are latin-1, so any filename with a character above U+00FF
made Starlette raise `UnicodeEncodeError`. llama-stack caught it while attaching
the file to a vector store and reported `status: failed` with an **empty
`last_error`** — it read exactly like a PDF parsing problem, and the same PDF
under an ASCII name ingested fine.

The latin-1 boundary is the failure boundary, which is nasty for Slovak:

| Characters          | In latin-1? | Result          |
|---------------------|-------------|-----------------|
| `á é í ó ú ý ô ä`   | yes         | ingested        |
| `č ď ľ ĺ ň ŕ š ť ž` | **no**      | silently failed |

So *most* Slovak filenames broke while a few worked — easy to misread as random.
Found by bisecting one character at a time until the boundary was exactly U+00FF.

**Fix:** [`llamastack-local-image/patch-content-disposition.py`](llamastack-local-image/patch-content-disposition.py)
emits an RFC 5987/6266 header (`filename*=utf-8''<pct-encoded>`), the same thing
Starlette's own `FileResponse` does. Filenames keep their diacritics end to end.

### A2. RAGAS embeddings deadlock the eval job

`llama-stack-provider-ragas`, `inline/wrappers_inline.py` — upstream's own `TODO`
flags it:

```python
def embed_query(self, text):
    # TODO: propose a way to configure BaseRagasEmbeddings to use sync or async
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(self.aembed_query(text))
```

ragas is driven from a worker thread (`asyncio.to_thread`), so
`get_event_loop()` returns the *server's* loop, which is already running →
`RuntimeError: This event loop is already running`, and the whole job fails.

It isolated cleanly: `faithfulness` (LLM only) completed, while
`answer_relevancy` / `answer_similarity` and friends all died — because the LLM
wrapper's sync path raises `NotImplementedError`, forcing ragas onto its async
path, while the embeddings wrapper offers this broken sync bridge.

**Fix:** [`llamastack-local-image/patch-ragas-embeddings-loop.py`](llamastack-local-image/patch-ragas-embeddings-loop.py)
captures the loop at construction and submits coroutines with
`asyncio.run_coroutine_threadsafe` — the correct primitive for calling into a
loop from another thread.

### A3. `factual_correctness` kills the eval job

Same file, the result-collection loop:

```python
for metric_name in [m.name for m in metrics]:
    metric_scores = result[metric_name]
```

ragas does not always key scores by the bare metric name (`ragas/evaluation.py`):

```python
if isinstance(m, ModeMetric):
    key = f"{m.name}(mode={m.mode})"
else:
    key = m.name
```

`FactualCorrectness` is a `ModeMetric` with `mode="f1"`, so its real key is
`factual_correctness(mode=f1)` and the whole job dies with
`KeyError: 'factual_correctness'`. Purely a naming-convention mismatch — the
metric itself is fine.

**Fix:** [`llamastack-local-image/patch-ragas-mode-metrics.py`](llamastack-local-image/patch-ragas-mode-metrics.py)
resolves the key the way ragas wrote it (bare name → `<name>(mode=…)` → any
`<name>(…)`) while still reporting under the bare name. This recovers the sixth
metric, so the full PoC metric set is available.

All three patches are idempotent and **fail the build** if the upstream source no
longer matches, so they cannot silently lapse across an upgrade.

---

## B. Silent failures (no error, feature simply absent)

### B1. fastText + NumPy 2 disables the language rail entirely

`nemo-local/configs/rag/actions.py`:

```python
except Exception:
    return "allowed"
```

fastText still calls `np.array(..., copy=False)`, which NumPy 2 rejects with a
`ValueError`. Every `predict()` therefore threw, the bare `except` turned that
into `"allowed"`, and the language rail **never blocked anything** while looking
perfectly healthy. Observed directly: English input sailed through a rail whose
entire purpose is to reject it.

**Fix:** `numpy<2` pinned in `nemo-local/Containerfile`. Verified afterwards that
English scores `blocked` (lang=en, conf 0.911) and Slovak `allowed`.

### B2. See also A1

`status: failed` with an empty `last_error` is the same class of problem: the
failure was reported, but with no information, and the plausible-looking
explanation (bad PDFs) was wrong.

---

## C. Unpinned / drifted dependencies

| #   | Where | What resolved | Symptom | Fix |
|-----|-----|-----|-----|-----|
| C1  | `llama stack build`'s generated Containerfile installs `llama-stack` unpinned | 0.7.x instead of 0.2.9 | entrypoint `llama_stack.distribution.server.server` no longer exists in 0.7.x — container would not even start | pin the version being built |
| C2  | `datasets` (transitively, for the 0.2.9 attempt) | 1.1.1 (from 2020) | `AttributeError: module 'pyarrow' has no attribute 'PyExtensionType'` at server startup | force `datasets>=3` |
| C3  | `llama-stack 0.6.0` declares `llama-stack-api` with **no bound** | 0.7.2 | `ImportError: cannot import name 'agents' from 'llama_stack_api'` — the CLI would not even load | pin all three llama-stack packages to 0.6.0 |
| C4  | `ragas 0.4.3` declares `langchain`, `langchain-core`, `langchain-community` with **no bounds** | langchain-community 0.4.2 | `ModuleNotFoundError: langchain_community.chat_models.vertexai` — ragas would not import | `langchain-community>=0.3,<0.4` |
| C5  | provider docs' own note | — | `inline/files/localfs` errors with "greenlet not found" | `greenlet==3.2.4` |
| C6  | `trl` → `liger_kernel` (0.2.9 attempt) | — | `ModuleNotFoundError: liger_kernel` crashed startup via the `post_training` provider | dropped the training providers from the run config entirely — a RAG chatbot needs none of them |

C1–C3 and C6 were all hit while trying to reproduce the 0.2.9 image, which is
why that attempt was abandoned in favour of aligning to 0.6.0.

---

## D. API / config drift

| #   | Symptom | Cause | Fix |
|-----|-----|-----|-----|
| D1  | UI gets `HTTP 426 "Client version 0.6.0 is not compatible with server version 0.2.9"` | the repo pins UI client 0.6.0 against a 0.2.9 server image | align the server to 0.6.0 (`LLAMA_STACK_DISABLE_VERSION_CHECK=1` alone is not enough — see D2) |
| D2  | with the version check off, UI calls `404` | `vector_stores`, `responses`, `conversations`, `chat/completions` do not exist before 0.6.0 | same: align the server, do not paper over the check |
| D3  | `ValueError: You must provide a URL … to use vLLM` although the config has one | 0.6.0's `remote::vllm` expects `base_url`; upstream's backup run-config uses the older `url:`, which is silently ignored | use `base_url` |
| D4  | `Embedding model 'X' not found. Available: ['sentence-transformers/sentence-transformers/…']` | `vector_stores.default_embedding_model` is looked up as `provider_id/model_id`, so `model_id` must repeat the provider's own model path | reference the full identifier |
| D5  | `nemoguardrails` refuses the config: "0.21-style LangChain conventions" | ≥0.23 renamed `openai_api_base` → `base_url` | rename the key |
| D6  | NeMo `/v1/models` returns `MAIN_MODEL_BASE_URL is not set`, breaking llama-stack's model listing | that endpoint needs the upstream base URL in the environment | set `MAIN_MODEL_BASE_URL` |
| D7  | NeMo returns `Internal server error`; log shows `model 'rag' not found` | the `model` field of a chat request is forwarded to Ollama; passing the *config id* there is wrong | pass the real model name; the config comes from `--default-config-id` |
| D9  | `Unknown metric: answer_correctness` (warning, then a failing job) | renamed in ragas 0.4.x | use the current names |
| D10 | UI's "Max Tokens" slider cannot reach its own labelled maximum (stops at 4033, not 4096), and its 512 default silently truncates thinking models | two separate causes. (a) `st.slider(label, min, max, value, step)` only yields values reachable by stepping from `min`, so upstream's `(1, 4096, 512, 64)` tops out at `1 + 63*64 = 4033`. (b) On the OpenAI-compatible path, `max_tokens` caps **reasoning + content combined** — measured on gemma4 with `max_tokens=200`: reasoning ate the whole budget, `content` came back as `""` with `finish_reason=length`, i.e. a blank reply and no error. Uncapped, gemma4 spends 1686–2168 completion tokens (~900 on reasoning) | `(0, 24576, 16384, 128)` — bounds are exact multiples of the step so the ceiling is reachable, and both fit the context budget. Note `max_tokens` shares `OLLAMA_CONTEXT_LENGTH` (32768) with the prompt (~434 tokens per retrieved chunk), so a ceiling of 32000 would **never** fit even at Top K=5 and would make Ollama silently drop the retrieved chunks. Patched at container start by `patch-max-tokens-slider.py` |

---

## E. Environment and operational traps

| #   | Trap | Detail |
|-----|-----|-----|
| E1  | private container image | `llamastack/distribution-ollama:0.2.9` grants no pull scope even authenticated, and has no quay/ghcr mirror. Diagnosed by decoding the Docker Hub token: `access: []` for this repo, while `grafana/grafana` returned a normal pull grant — so it was the repo, not our auth |
| E2  | no default registry | Ubuntu's `registries.conf` sets no `unqualified-search-registries`, so short image names in the compose file cannot resolve at all |
| E3  | Ollama on loopback | the systemd unit binds `127.0.0.1`; rootless containers cannot reach it. Run it on `0.0.0.0` |
| E4  | Ollama fills VRAM with KV cache | it auto-sizes context to available VRAM — a 3B model reserved **77 GB**. A 54–64 GB model would then OOM. Cap `OLLAMA_CONTEXT_LENGTH` |
| E5  | silent CPU offload | another process (LM Studio, 73.5 GB) held VRAM, so Ollama placed only 37 % of the model on GPU and ran the rest on CPU — while `ollama ps` still listed it as loaded. Compare `size_vram` with `size`; the split is decided at load time and kept |
| E6  | sharded GGUF cannot be imported | `ollama create` fails with `split GGUF … has 1 shards, expected 2`, so a model already downloaded by LM Studio could not be reused. The library build is also safer: it ships the chat template tool calling needs |
| E7  | cancelled pulls leak disk | Ollama has no prune command. `blobs/*-partial*` plus blobs unreferenced by any manifest came to **98 GB** here |
| E8  | killing a pull needs care | the first `kill` hit only the wrapper process, leaving a second `ollama pull` running — two downloads then shared the link. Check with `pgrep -af` |
| E9  | podman `depends_on` blocks removal | `podman rm -f rag-llamastack` fails while `rag-ui` exists; remove dependents first |
| E10 | `pkill -f` can kill its own shell | the pattern appears in the invoking command's own argv, so `pkill -f "ollama pull"` matched and killed the shell running it. Use a port (`fuser -k`) or a regex that cannot self-match |
| E11 | one stopped container breaks a subset of models with no local clue | `nemo-guardrails` was stopped (with everything else) to free VRAM for a benchmark, then only `llamastack`/`rag-ui` were restarted afterward. Ollama and every `ollama/*` model worked fine; every `nemo/*` model in the UI answered `HTTP 500` with nothing in the chatbot's own logs pointing at "the guardrails container isn't running" — the failure surfaces one layer away from its cause. Fixed by `./start-stack.sh` (repo root), which starts all four pieces together and is safe to re-run any time |
| E12 | a relative bind-mount `source:` in a compose *override* file resolves against the wrong directory | `compose-model-override.yml` (repo root) declared `volumes: [./patch-max-tokens-slider.py:...]`; podman-compose resolved `./` against the **base** compose file's directory (`RAG/deploy/local`), not the override file's own directory. The path didn't exist there, so podman silently bind-mounted an auto-created **empty directory** instead of erroring — the container then crash-looped on `python /tmp/patch-....py` with the distinctly unhelpful `can't find '__main__' module in '/tmp/patch-....py'` (Python's error for "this is a directory, not a script"). Worse, the empty directory was created *inside the pinned, gitignored `RAG/` clone*. Use an absolute path for bind-mount sources declared in an override file |

---

## F. Model capability limits (not bugs, but they break features)

- **Gemma 3 has no tool calling.** `ollama show` reports `completion, vision`
  only, so the UI's Agent mode and any `responses` call with a `file_search`
  tool fail with `500 … does not support tools`. Direct RAG is unaffected.
  Gemma 4 31B and Qwen3.6 27B report `tools` (and `thinking`) and work.
- **all-MiniLM-L6-v2 is English-centric.** Fine for the FantaCo demo, weak on
  Slovak. Replaced with Qwen3-4B embeddings (dim 2560), which also matches the
  original PoC.

---

## G. Corrections made along the way

Recorded because the first explanation was wrong in each case, and the wrong one
was plausible:

- The two PDFs that failed to ingest were first blamed on **file names with
  diacritics in general**. Wrong twice over: the actual character was an en-dash
  (U+2013), and a filename with a single Slovak `í` ingested fine. Only
  bisecting per character revealed the real rule (the latin-1 boundary, A1).
- The failing PDFs were then suspected of having **no text layer**. Wrong:
  `pypdf` extracted 13 222 and 2 131 characters from them respectively — more
  than from several files that succeeded.
- "Gemma 4 31B" was initially doubted as non-existent (knowledge cutoff).
  It exists; checking the registry settled it in one call.
