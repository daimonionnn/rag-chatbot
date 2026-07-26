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

### B3. Agent-based mode answers from parametric memory instead of the documents

The worst failure mode found in this project, because the answer looks right. In
Agent-based mode the model is *offered* `file_search` and `web_search` and may
simply not call them — and then answers from memory, with no indication in the
UI that no document was ever retrieved. Asked `Kolko stoji zubna prehliadka?`
with the `vszp` store attached, gemma4 produced a confident, well-formatted
breakdown of Slovak dental prices that came entirely from the model.

Measured per model, same question, same tools (`outputs` from `/v1/responses`):

| Model                  | `file_search`                              | `web_search`                          |
|------------------------|--------------------------------------------|---------------------------------------|
| `gemma3:27b-it-fp16`   | HTTP 500, `does not support tools`         | HTTP 500, `does not support tools`    |
| `gemma4:31b-it-bf16`   | 200, `['message']` — **tool never called** | 200, `['message']` — **never called** |
| `qwen3.6:27b-mtp-bf16` | 200, `['file_search_call', 'message']`     | 200, `['web_search_call', 'message']` |

Three distinct causes behind one symptom, so "agent mode is broken" is the wrong
diagnosis:

1. **gemma3 cannot do tool calling at all.** Ollama rejects the request outright,
   which surfaces in the UI as `❌ Error: Error code: 500`. Since gemma3 is the
   default `INFERENCE_MODEL`, this is what Agent-based mode does out of the box.
2. **gemma4 accepts tools but does not use them** for this prompt — the silent
   case above.
3. **Web search needs a key that matches the configured provider.** With none,
   the provider raises `401 Unauthorized` from `api.tavily.com`; the agent
   swallows it and answers from memory anyway.

**qwen3.6 calls the tool, but not reliably — and what decides is the question.**
Repeating one identical request does not give one answer. Measured over `n=3` per
variant, `file_search` offered every time, temperature 0.1:

| Question                                         | Tool called |
|--------------------------------------------------|------------:|
| `Kolko stoji zubna prehliadka?`                  | 0/3         |
| the same, system prompt + `Answer in Slovak.`    | 1/3         |
| `Ake vyhody ponuka Penazenka zdravia od VSZP …?` | 3/3         |

So the model retrieves when it judges that it *needs* to, and skips retrieval when
the question looks like general knowledge. That is defensible behaviour in the
abstract and precisely wrong for a RAG assistant: `Kolko stoji zubna prehliadka?`
**does** have a specific answer in the VSZP corpus, and the model instead produced
private-clinic price ranges from memory. The questions most likely to be answered
without retrieval are exactly the ones where the corpus disagrees with general
knowledge.

**Fix / how to use it:** Agent-based mode is *not* an unfinished template — it is
llama-stack's Responses API (`POST /v1/responses`, `inline::meta-reference` agents
provider), the tool-calling loop runs server-side, and the retrieval it performs
is real. But treat **`Direct` mode as the dependable path**: it retrieves
*unconditionally* instead of leaving the decision to the model, which is why it is
the mode the evaluation harness uses. For Agent-based mode, pick
`qwen3.6:27b-mtp-bf16` (the only one of the three that calls tools at all) and
read the `outputs` list, which is the only reliable evidence that retrieval
happened: no `file_search_call` means the documents were not consulted, however
plausible the text.

Retrieval can also be *forced* rather than left to the model — the Responses API
accepts `tool_choice`, which the UI never sends. That works, but only with the
right tool name; the obvious spelling is a trap, see B6.

### B4. Web search silently degrades to no search

Two independent silent failures stack here. `builtin::websearch` binds to exactly
one provider, and upstream binds it to `tavily-search`. A Brave key in
`BRAVE_SEARCH_API_KEY` therefore changes nothing — the toolgroup still calls
Tavily, still gets `401`, and the agent still answers from memory. Worse, the
tool call is reported as `status="completed"` in the response, so the UI shows a
web-search step that found nothing and says so nowhere.

**Fix:** register the matching provider and point the toolgroup at it
(`config-0.6.0.yaml`); both providers register their tool under the same name
(`web_search`), so nothing above the provider layer changes. Verified with a live
query returning real Slovak results. The key itself lives in the untracked
`.env.local`, which `start-stack.sh` sources — see SETUP.md.

### B5. Changing the web-search provider needs an unregister first

Registry entries are **persisted** in the metadata store
(`local_llamastack_data` volume, `distributions/starter/kvstore.db`), not derived
from the config at each boot. Repointing `builtin::websearch` at a new provider
therefore makes the server refuse to start:

```
ValueError: Object of type 'tool_group' and identifier 'builtin::websearch' already
exists with conflicting field values: {'provider_id': ('brave-search', 'tavily-search')}
```

With `restart: on-failure:50` in the compose file, that presents as a
crash-looping container rather than an obvious config error.

**Fix:** unregister the stale entry before the switch —
`DELETE /v1/toolgroups/builtin::websearch` (HTTP 204). Chicken-and-egg, because
the server has to be running to accept the call and will not start against the
new config: bring up a *temporary* container with the old `provider_id`
(bind-mount a patched config over `/app/config.yaml`, same volume and network,
different port), unregister there, then start the real one, which re-registers
against the new provider. Editing `kvstore.db` by hand also works but is not
worth the risk.

### B6. Forcing retrieval with `tool_choice` silently disables it instead

A genuine llama-stack defect, and the most treacherous shape a bug can take: the
parameter whose entire purpose is to *guarantee* the tool runs is what stops it
from running. Both obvious spellings are accepted, return HTTP 200, and produce a
confident answer with no retrieval and no warning:

| `tool_choice` | Tool called |
|-----|----:|
| `{"type": "file_search"}` | 0/2 |
| `{"type": "allowed_tools", "mode": "required", … "file_search"}` | 0/2 |
| `{"type": "allowed_tools", "mode": "required", … "knowledge_search"}` | **2/2** |

The cause is a name mismatch inside `_process_tool_choice`
(`providers/inline/agents/meta_reference/responses/streaming.py`). For a
`file_search` choice it builds the allowed-tools entry as

```python
case "file_search":
    final_tools.append({"type": "function", "function": {"name": "file_search"}})
```

but the tool actually offered to the model is named **`knowledge_search`** — that
is the name the executor dispatches on, and the name in
`_SERVER_SIDE_BUILTIN_TOOL_NAMES`. The allowed list is then applied as a filter:

```python
effective_tools = [t for t in self.ctx.chat_tools
                   if t.get("function", {}).get("name") in allowed_tool_names]
```

Nothing matches `"file_search"`, so `effective_tools` comes out **empty** and the
model is handed no tools at all. Asking for retrieval to be mandatory is
therefore the one way to guarantee it cannot happen.

**Workaround:** spell the tool `knowledge_search` in an explicit `allowed_tools`
choice — verified 2/2, and one run called it twice. Not patched in this repo: the
UI does not send `tool_choice` at all today, so nothing here hits the bug. It
matters if the UI is ever changed to force retrieval (see H).

---

## C. Unpinned / drifted dependencies

C1–C3 and C6 were all hit while trying to reproduce the 0.2.9 image, which is
why that attempt was abandoned in favour of aligning to 0.6.0.

### C1. `llama stack build` installs `llama-stack` unpinned

Its generated Containerfile pulls whatever is current — 0.7.x instead of the
0.2.9 being built. The entrypoint `llama_stack.distribution.server.server` no
longer exists in 0.7.x, so the container would not even start.

**Fix:** pin the version being built.

### C2. `datasets` resolves to 1.1.1, from 2020

Pulled transitively during the 0.2.9 attempt. Fails at server startup with
`AttributeError: module 'pyarrow' has no attribute 'PyExtensionType'`.

**Fix:** force `datasets>=3`.

### C3. `llama-stack 0.6.0` declares `llama-stack-api` with no bound

Resolves to 0.7.2, and the CLI then will not even load:
`ImportError: cannot import name 'agents' from 'llama_stack_api'`.

**Fix:** pin all three llama-stack packages to 0.6.0.

### C4. `ragas 0.4.3` declares its langchain trio with no bounds

`langchain`, `langchain-core` and `langchain-community` are all unbounded;
langchain-community resolves to 0.4.2, where the module ragas imports is gone —
`ModuleNotFoundError: langchain_community.chat_models.vertexai`. ragas does not
import at all.

**Fix:** `langchain-community>=0.3,<0.4`.

### C5. `greenlet` missing

Flagged in the provider's own docs: `inline/files/localfs` errors with
"greenlet not found".

**Fix:** `greenlet==3.2.4`.

### C6. `trl` drags in `liger_kernel`

During the 0.2.9 attempt, `ModuleNotFoundError: liger_kernel` crashed startup by
way of the `post_training` provider.

**Fix:** dropped the training providers from the run config entirely — a RAG
chatbot needs none of them.

---

## D. API / config drift

### D1. UI rejected with HTTP 426

`Client version 0.6.0 is not compatible with server version 0.2.9` — the repo
pins the UI client to 0.6.0 against a 0.2.9 server image.

**Fix:** align the server to 0.6.0. `LLAMA_STACK_DISABLE_VERSION_CHECK=1` alone is
not enough — see D2.

### D2. With the version check off, the UI's calls 404

`vector_stores`, `responses`, `conversations` and `chat/completions` do not exist
before 0.6.0, so silencing the check just moves the failure.

**Fix:** same as D1 — align the server rather than papering over the check.

### D3. `You must provide a URL … to use vLLM`, although the config has one

0.6.0's `remote::vllm` expects `base_url`. Upstream's backup run-config uses the
older `url:` key, which is silently ignored.

**Fix:** use `base_url`.

### D4. `Embedding model 'X' not found`

The error lists `['sentence-transformers/sentence-transformers/…']` — because
`vector_stores.default_embedding_model` is looked up as `provider_id/model_id`,
so `model_id` has to repeat the provider's own model path.

**Fix:** reference the full identifier.

### D5. `nemoguardrails` refuses the config

It reports "0.21-style LangChain conventions": ≥0.23 renamed `openai_api_base`
to `base_url`.

**Fix:** rename the key.

### D6. NeMo `/v1/models` returns `MAIN_MODEL_BASE_URL is not set`

Which breaks llama-stack's model listing — that endpoint needs the upstream base
URL in the environment.

**Fix:** set `MAIN_MODEL_BASE_URL`.

### D7. NeMo returns `Internal server error`, log shows `model 'rag' not found`

The `model` field of a chat request is forwarded to Ollama, so passing the
*config id* there is wrong.

**Fix:** pass the real model name; the config comes from `--default-config-id`.

### D8. Moved to A3

Was "eval job dies with `KeyError: 'factual_correctness'`". Once it turned out to
be a fixable provider defect rather than config drift, it moved to
[A3](#a3-factual_correctness-kills-the-eval-job). The number is kept as a stub so
existing references do not point at the wrong entry.

### D9. `Unknown metric: answer_correctness`

A warning, followed by a failing job. Renamed in ragas 0.4.x.

**Fix:** use the current metric names.

### D10. "Max Tokens" slider: unreachable ceiling, and a default that empties answers

Two separate causes behind one control.

**(a) The ceiling is a lie.** `st.slider(label, min, max, value, step)` only
yields values reachable by stepping from `min`, so upstream's
`(1, 4096, 512, 64)` tops out at `1 + 63*64 = 4033` — the next step, 4097, would
exceed the labelled 4096.

**(b) The cap covers reasoning, not just the answer.** On the OpenAI-compatible
path, `max_tokens` limits reasoning + content *combined*. Measured on gemma4 with
`max_tokens=200`: reasoning consumed the whole budget, `content` came back as
`""` with `finish_reason=length` — a blank reply, no error. Uncapped, gemma4
spends 1686–2168 completion tokens per answer, ~900 of them on reasoning, so the
512 default sat well inside the range where thinking models get emptied.

**Fix:** `(0, 24576, 16384, 128)` — every bound is an exact multiple of the step,
so the ceiling is reachable, and both fit the context budget. Note that
`max_tokens` shares `OLLAMA_CONTEXT_LENGTH` (32768) with the prompt (~434 tokens
per retrieved chunk), so a ceiling of 32000 would **never** fit, even at Top K=5,
and would make Ollama silently drop the retrieved chunks. Applied at container
start by `patch-max-tokens-slider.py`.

### D11. Every sidebar change wipes the chat history

Changing the model, the processing mode, any sampling slider or the system prompt
clears the whole conversation — so comparing two models on the same question, or
raising Max Tokens after a truncated answer, is impossible without retyping it.

Eight sidebar widgets are wired to a session-clearing callback: seven to
`on_change=reset_agent`, plus the MCP selector to `on_reset`. `reset_agent()` is
`st.session_state.clear()` followed by `st.cache_resource.clear()`, and it takes
`messages` and `conversation_id` with it.

Nothing depends on that reset. `ChatConfig` is rebuilt from the widgets on *every*
rerun, so a changed setting takes effect on the next message either way; and no
function in `chat.py` is decorated with `@st.cache_resource`, so the cache half
clears nothing. Upstream itself already treats a full reset as unnecessary for the
guardrail selectors, which use the narrower `reset_conversation()`.

**Fix:** drop the eight callbacks (`patch-max-tokens-slider.py`).
`Clear Chat & Reset Config` still calls `reset_agent()`, so starting over stays
explicit. Two traps in doing it by text substitution:

- Seven occurrences sit on their own line, but the System Prompt one is inline
  among other kwargs. Deleting `, on_change=reset_agent,` from
  `value=default_prompt, on_change=reset_agent, height=100` consumes **both**
  commas, leaving `value=default_prompt height=100` — a `SyntaxError` that stops
  the Chat page importing at all. Own-line matches take the whole line; inline
  matches keep the separating comma.
- `on_reset` is left as an accepted-but-unused parameter of
  `render_toolgroup_selection` rather than removed from its signature *and* its
  call site. Those two edits have to land together, and a half-applied pair calls
  it with one argument too many, breaking Agent-based mode.

The patch `ast.parse`s the result before writing and refuses to write otherwise,
then asserts no callback survived — editing Python with a regex earns both.

---

## E. Environment and operational traps

### E1. The container image is private

`llamastack/distribution-ollama:0.2.9` grants no pull scope even when
authenticated, and has no quay/ghcr mirror. Diagnosed by decoding the Docker Hub
token: `access: []` for this repo, while `grafana/grafana` returned a normal pull
grant — so it was the repo, not our credentials.

### E2. No default registry

Ubuntu's `registries.conf` sets no `unqualified-search-registries`, so the short
image names in the compose file cannot resolve at all.

### E3. Ollama binds loopback

The systemd unit listens on `127.0.0.1`, which rootless containers cannot reach.
Run it on `0.0.0.0`.

### E4. Ollama fills VRAM with KV cache

It auto-sizes context to the available VRAM — a 3B model reserved **77 GB**. A
54–64 GB model would then OOM. Cap `OLLAMA_CONTEXT_LENGTH`.

### E5. Silent CPU offload

Another process (LM Studio, holding 73.5 GB) left too little VRAM, so Ollama
placed only 37 % of the model on the GPU and ran the rest on CPU — while
`ollama ps` still listed it as loaded. Compare `size_vram` with `size`; the split
is decided at load time and kept.

### E6. Sharded GGUF cannot be imported

`ollama create` fails with `split GGUF … has 1 shards, expected 2`, so a model
already downloaded by LM Studio could not be reused. The library build is also
the safer choice: it ships the chat template tool calling depends on.

### E7. Cancelled pulls leak disk

Ollama has no prune command. `blobs/*-partial*` plus blobs unreferenced by any
manifest came to **98 GB** here.

### E8. Killing a pull needs care

The first `kill` hit only the wrapper process, leaving a second `ollama pull`
running — two downloads then shared the link. Check with `pgrep -af`.

### E9. podman `depends_on` blocks removal

`podman rm -f rag-llamastack` fails while `rag-ui` exists. Remove dependents
first.

### E10. `pkill -f` can kill its own shell

The pattern appears in the invoking command's own argv, so
`pkill -f "ollama pull"` matched and killed the shell running it. Use a port
(`fuser -k`) or a regex that cannot self-match.

### E11. One stopped container breaks a subset of models, with no local clue

`nemo-guardrails` was stopped (along with everything else) to free VRAM for a
benchmark, and afterwards only `llamastack`/`rag-ui` were restarted. Ollama and
every `ollama/*` model worked fine; every `nemo/*` model in the UI answered
`HTTP 500`, with nothing in the chatbot's own logs pointing at "the guardrails
container isn't running" — the failure surfaces one layer away from its cause.

**Fix:** `./start-stack.sh` (repo root) starts all four pieces together and is
safe to re-run any time.

### E12. A relative bind-mount source in a compose *override* resolves elsewhere

`compose-model-override.yml` (repo root) declared
`volumes: [./patch-max-tokens-slider.py:...]`. podman-compose resolved `./`
against the **base** compose file's directory (`RAG/deploy/local`), not the
override file's own. The path did not exist there, so podman silently
bind-mounted an auto-created **empty directory** rather than erroring — and the
container crash-looped on `python /tmp/patch-....py` with the distinctly
unhelpful `can't find '__main__' module in '/tmp/patch-....py'`, which is
Python's way of saying "this is a directory, not a script". Worse, the empty
directory was created *inside the pinned, gitignored `RAG/` clone*.

**Fix:** use an absolute path for bind-mount sources declared in an override file.

---

## F. Model capability limits (not bugs, but they break features)

- **Gemma 3 has no tool calling.** `ollama show` reports `completion, vision`
  only, so the UI's Agent mode and any `responses` call with a `file_search`
  tool fail with `500 … does not support tools`. Direct RAG is unaffected.
- **Advertising `tools` is not the same as using them.** Gemma 4 31B and
  Qwen3.6 27B both report `tools` (and `thinking`), but only Qwen3.6 was
  observed actually emitting tool calls. Gemma 4 accepted the tools and answered
  without calling them in every attempt, and Qwen3.6 calls them only when it
  judges the question to need them — measured rates in B3. The capability flag
  says a request will not be *rejected*; it says nothing about retrieval
  happening.
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

---

## H. Possible improvements, not applied

Deliberately left undone, recorded so the reasoning is not lost.

### H1. Force retrieval in Agent-based mode

The measurements in B3 make Agent-based mode unreliable *as a RAG path*: the model
decides whether to retrieve, and it decides wrong precisely when the corpus
disagrees with general knowledge. `tool_choice` can take that decision away from
it, using the `knowledge_search` spelling from B6:

```python
request_kwargs["tool_choice"] = {
    "type": "allowed_tools", "mode": "required",
    "tools": [{"type": "function", "name": "knowledge_search"}],
}
```

Not applied for two reasons. First, forcing a tool call on *every* turn breaks
ordinary conversation — "thanks", "explain that again", or any follow-up would
trigger a pointless vector search, and llama-stack resets `tool_choice` to `auto`
only after the first iteration. Deciding when to force is a design question, not
a patch. Second, `Direct` mode already retrieves unconditionally and is the
supported path here, so the gap this would close is narrow.

If it is wanted, the natural shape is an explicit UI control ("always search
documents") rather than a hardcoded default, so the user can see the behaviour
they are getting.

### H2. Surface "no retrieval happened" in the UI

The deeper problem behind B3 is not that the model skips retrieval, it is that
skipping is *invisible*. The response already carries the evidence — an `outputs`
list without `file_search_call` — so the UI could say plainly that an answer came
from the model rather than the documents. That is a genuine improvement over
forcing the tool, because it fixes the trust problem instead of hiding it, and it
is a display change rather than a behavioural one.
