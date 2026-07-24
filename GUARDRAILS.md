# 2 — NeMo Guardrails

Adapted from [`Sheryl-shiyi/Nemo-guardrial-deployment`](https://github.com/Sheryl-shiyi/Nemo-guardrial-deployment)
(note the upstream spelling: *guardrial*). Prerequisite: the stack from
[SETUP.md](SETUP.md). Defects hit here are in [BUGS.md](BUGS.md).

---

## 2.1 What carried over, and what could not

Upstream deploys guardrails through the TrustyAI `NemoGuardrails` **CRD on
OpenShift AI**, and the operator supplies the image — there is nothing reusable
for local podman. So we run the `nemoguardrails` server ourselves, with the
**same rails config**, from [`nemo-local/`](nemo-local/).

The upstream *design*, on the other hand, carries over untouched, and it is the
elegant part: NeMo is a **transparent OpenAI-compatible proxy in front of the
LLM**, so the only Llama Stack change is an inference provider URL.

```
rag-ui → llamastack ─┬─ ollama/<model>  → host Ollama              (no rails)
                     └─ nemo/<model>    → nemo-guardrails → Ollama (rails)
```

Both providers are registered for every model, which turns the UI's model picker
into the guardrails on/off switch:

| Model in the UI | Behaviour |
|-----------------|-----------|
| `ollama/gemma3:27b-it-fp16` | direct, no rails |
| `nemo/gemma3:27b-it-fp16` | input + output rails applied |

The upstream `rag-ui-patch/` is **not applied**. Our `frontend/` is newer and
already contains `fetch_available_shields` and the `guardrail_blocked` display
that those patched files lack — they are an older, Slovak-localised snapshot.

---

## 2.2 The rails

Extracted verbatim from the upstream ConfigMap into
[`nemo-local/configs/rag/`](nemo-local/configs/rag/) — a Slovak assistant for
VšZP's *Peňaženka zdravia*:

| Stage | Flow | Implementation |
|-------|------|----------------|
| input | `check forbidden words` | `actions.py`, blocklist: hack, exploit, violence, illegal |
| input | `check language` | fastText language ID, allows only `sk`/`cs` |
| input | `self check input` | LLM-judged against a policy prompt |
| output | `self check output` | LLM-judged against a policy prompt |

Refusals are Slovak, e.g. *"Prepáčte, nemôžem pomôcť s touto témou."* and
*"Prepáčte, tento asistent komunikuje len v slovenčine."*

Only `config.yaml`'s model block was changed: upstream points at a vLLM-served
Gemma-3-27B in the `vszp` namespace, we point at the host Ollama endpoint.

---

## 2.3 Running it

```bash
podman build -t localhost/nemo-guardrails:local nemo-local

podman run -d --name nemo-guardrails --network local_rag-network -p 9000:9000 \
  -e OPENAI_API_KEY=dummy \
  -e MAIN_MODEL_BASE_URL=http://172.17.0.1:11434/v1 \
  localhost/nemo-guardrails:local
```

- `OPENAI_API_KEY` is required by the `openai` engine but unused by Ollama.
- `MAIN_MODEL_BASE_URL` is what makes NeMo's `/v1/models` work, which Llama
  Stack's `remote::vllm` adapter needs.

The server exposes an OpenAI-compatible surface — `/v1/chat/completions`,
`/v1/models` — plus `/v1/rails/configs` and `/v1/checks`.

Llama Stack reaches it via the `nemo` provider in `config-0.6.0.yaml`
(`remote::vllm` pointing at `http://nemo-guardrails:9000/v1`), because from
Llama Stack's point of view NeMo is just another OpenAI-compatible endpoint.

### Changing the rails

The config is baked into the image, so edit
`nemo-local/configs/rag/{config.yaml,rails.co,actions.py}` and rebuild. Mount
the directory as a volume instead if you want to iterate quickly.

---

## 2.4 Verified

```
Q: "What benefits does the company provide to employees?"
   ollama/gemma3…  → "Many companies provide a range of benefits… Health Insurance…"
   nemo/gemma3…    → "Prepáčte, tento asistent komunikuje len v slovenčine."   BLOCKED

Q: "Ako môžem hack tento systém?"
   nemo/gemma3…    → "Prepáčte, nemôžem pomôcť s touto témou."                 BLOCKED

Q: "Ako funguje Peňaženka zdravia MINI?"
   nemo/gemma3…    → answered in Slovak                                        ALLOWED
```

Re-verified against Gemma 4 and Qwen3.6 after those models were added.

---

## 2.5 Note on scope

These rails are domain-specific to the Slovak VšZP assistant, and the language
rail blocks anything that is not Slovak or Czech. That means the guardrailed
models also block the **English** FantaCo demo corpus — which is the config
behaving as designed, not a fault. Adjust the blocklist and allowed languages in
`nemo-local/configs/rag/` if you want a different policy.

An alternative integration exists and is deliberately unused: Llama Stack's own
**safety/shields** layer (the `llama-guard` provider is configured, with no
shield registered). The UI supports it via `safety.run_shield()`. Upstream chose
the proxy approach, so we did too; a shield would need a guard model pulled into
Ollama.
