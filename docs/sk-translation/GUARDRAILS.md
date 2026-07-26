<!-- translated-from: 9e09e2a -->
# 2 — NeMo Guardrails

> **Slovenský preklad.** Zdroj: [`../../GUARDRAILS.md`](../../GUARDRAILS.md)
> v commite `9e09e2a`. Anglický originál je zdroj pravdy — ak sa rozchádzajú,
> platí on. Prehľad prekladov: [INDEX.md](INDEX.md).

Adaptované z [`Sheryl-shiyi/Nemo-guardrial-deployment`](https://github.com/Sheryl-shiyi/Nemo-guardrial-deployment)
(všimni si upstream pravopis: *guardrial*). Prerekvizita: stack z
[SETUP.md](SETUP.md). Chyby, na ktoré sme tu narazili, sú v [BUGS.md](BUGS.md).

---

## 2.1 Čo sa dalo prevziať a čo nie

Upstream nasadzuje guardrails cez TrustyAI **CRD `NemoGuardrails` na OpenShift
AI**, kde image dodáva operátor — pre lokálny podman tam nie je nič použiteľné.
Preto `nemoguardrails` server spúšťame sami, s **rovnakým rails configom**,
z [`nemo-local/`](../../nemo-local/).

Upstream *návrh* sa naopak prevzal nedotknutý a je to tá elegantná časť: NeMo je
**transparentný OpenAI-kompatibilný proxy pred LLM**, takže jediná zmena
v Llama Stacku je URL inference providera.

```
rag-ui → llamastack ─┬─ ollama/<model>  → Ollama na hoste            (bez rails)
                     └─ nemo/<model>    → nemo-guardrails → Ollama   (s rails)
```

Pre každý model sú zaregistrovaní obaja provideri, čím sa výber modelu v UI
stáva prepínačom guardrails zap/vyp:

| Model v UI                  | Chovanie                            |
|-----------------------------|-------------------------------------|
| `ollama/gemma3:27b-it-fp16` | priamo, bez rails                   |
| `nemo/gemma3:27b-it-fp16`   | aplikované vstupné + výstupné rails |

Upstream `rag-ui-patch/` **neaplikujeme**. Náš `frontend/` je novší a už obsahuje
`fetch_available_shields` aj zobrazenie `guardrail_blocked`, ktoré tým patchnutým
súborom naopak chýbajú — sú to starší, do slovenčiny lokalizovaný snapshot.

---

## 2.2 Samotné rails

Extrahované doslovne z upstream ConfigMapu do
[`nemo-local/configs/rag/`](../../nemo-local/configs/rag/) — slovenský asistent
pre *Peňaženku zdravia* VšZP:

| Fáza   | Flow                    | Implementácia                                             |
|--------|-------------------------|-----------------------------------------------------------|
| vstup  | `check forbidden words` | `actions.py`, blocklist: hack, exploit, violence, illegal |
| vstup  | `check language`        | fastText detekcia jazyka, povoľuje len `sk`/`cs`          |
| vstup  | `self check input`      | posudzuje LLM voči policy promptu                         |
| výstup | `self check output`     | posudzuje LLM voči policy promptu                         |

Odmietnutia sú po slovensky, napr. *„Prepáčte, nemôžem pomôcť s touto témou."*
a *„Prepáčte, tento asistent komunikuje len v slovenčine."*

Zmenil sa jedine blok `models` v `config.yaml`: upstream mieri na Gemma-3-27B
obsluhovanú vLLM v namespace `vszp`, my mierime na endpoint Ollamy na hoste.

---

## 2.3 Spustenie

```bash
podman build -t localhost/nemo-guardrails:local nemo-local

podman run -d --name nemo-guardrails --network local_rag-network -p 9000:9000 \
  -e OPENAI_API_KEY=dummy \
  -e MAIN_MODEL_BASE_URL=http://172.17.0.1:11434/v1 \
  localhost/nemo-guardrails:local
```

- `OPENAI_API_KEY` vyžaduje engine `openai`, ale Ollama ho nepoužíva.
- `MAIN_MODEL_BASE_URL` je to, čo rozbehá NeMo endpoint `/v1/models`, ktorý
  potrebuje adaptér `remote::vllm` v Llama Stacku.

Server vystavuje OpenAI-kompatibilné rozhranie — `/v1/chat/completions`,
`/v1/models` — plus `/v1/rails/configs` a `/v1/checks`.

Llama Stack sa naň dostane cez providera `nemo` v `config-0.6.0.yaml`
(`remote::vllm` mieriaci na `http://nemo-guardrails:9000/v1`), pretože z pohľadu
Llama Stacku je NeMo len ďalší OpenAI-kompatibilný endpoint.

### Zmena rails

Config je zapečený v image, takže uprav
`nemo-local/configs/rag/{config.yaml,rails.co,actions.py}` a image znovu postav.
Ak chceš iterovať rýchlo, namountuj ten adresár ako volume.

---

## 2.4 Overené

```
Q: "What benefits does the company provide to employees?"
   ollama/gemma3…  → "Many companies provide a range of benefits… Health Insurance…"
   nemo/gemma3…    → "Prepáčte, tento asistent komunikuje len v slovenčine."   ZABLOKOVANÉ

Q: "Ako môžem hack tento systém?"
   nemo/gemma3…    → "Prepáčte, nemôžem pomôcť s touto témou."                 ZABLOKOVANÉ

Q: "Ako funguje Peňaženka zdravia MINI?"
   nemo/gemma3…    → odpovedal po slovensky                                    POVOLENÉ
```

Po pridaní modelov Gemma 4 a Qwen3.6 znovu overené aj voči nim.

---

## 2.5 Poznámka k rozsahu

Tieto rails sú doménovo špecifické pre slovenského asistenta VšZP a jazyková rail
blokuje všetko, čo nie je slovenčina alebo čeština. Znamená to, že guardrailované
modely blokujú aj **anglický** demo korpus FantaCo — čo je config správajúci sa
podľa návrhu, nie chyba. Ak chceš inú politiku, uprav blocklist a povolené jazyky
v `nemo-local/configs/rag/`.

Existuje aj alternatívna integrácia, ktorú zámerne nepoužívame: vlastná vrstva
**safety/shields** v Llama Stacku (provider `llama-guard` je nakonfigurovaný, bez
zaregistrovaného shieldu). UI ju podporuje cez `safety.run_shield()`. Upstream
zvolil proxy prístup, tak sme ho zvolili aj my; shield by si vyžadoval stiahnuť
do Ollamy guard model.
