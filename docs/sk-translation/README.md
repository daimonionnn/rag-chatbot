<!-- translated-from: 3fdaa91 -->
# Enterprise RAG Chatbot — lokálna reprodukcia

> **Slovenský preklad.** Zdroj: [`../../README.md`](../../README.md) v commite
> `7f56dd2`. Anglický originál je zdroj pravdy — ak sa rozchádzajú, platí on.
> Prehľad prekladov a ich aktuálnosť: [INDEX.md](INDEX.md).

Lokálne bežiaci RAG chatbot so safety guardrails a RAGAS evaluáciou, reprodukovaný
z troch upstream repozitárov na jedinej pracovnej stanici pomocou **rootless
podmanu** a **Ollamy na hoste** — bez OpenShiftu, bez Kubeflow, bez clustra.

> **Stavané a testované primárne pre slovenčinu.** Nič v stacku nie je
> výlučne slovenské — modely, embeddingy aj retrieval sú viacjazyčné a namieriť
> ho na anglický či iný korpus funguje — ale každé rozhodnutie tu padlo a každé
> číslo bolo namerané na slovenčine. Prejavuje sa to na konkrétnych miestach:
> embedding model sa vymenil za Qwen3-4B, pretože default `all-MiniLM-L6-v2` je
> anglocentrický a na slovenčine slabý; musela sa opraviť chyba v kódovaní názvov
> súborov, ktorá ticho zahadzovala dokumenty s `č ď ľ š ť ž` v názve; guardrails
> obsahujú jazykovú rail; a celá evaluácia beží na 182-otázkovom slovenskom
> korpuse. Pri inom jazyku čakaj, že setup pôjde, ale *merania* sa neprenesú —
> a ber do úvahy, že žiadna metrika tu nehodnotí kvalitu jazyka, v žiadnom jazyku
> (pozri [EVALUATION-LIMITS.md §4.4](EVALUATION-LIMITS.md)).

| Upstream | Čo z neho preberáme |
|-----|-----|
| [`Sheryl-shiyi/RAG`](https://github.com/Sheryl-shiyi/RAG) (fork Red Hat `rh-ai-quickstart/RAG`) | samotný chatbot: Llama Stack + Streamlit UI + ingestion |
| [`Sheryl-shiyi/Nemo-guardrial-deployment`](https://github.com/Sheryl-shiyi/Nemo-guardrial-deployment) | vstupné/výstupné safety rails |
| [`Sheryl-shiyi/proj-poc-RAGAS`](https://github.com/Sheryl-shiyi/proj-poc-RAGAS) + [`llama-stack-provider-ragas`](https://github.com/Sheryl-shiyi/llama-stack-provider-ragas) | metodika a engine evaluácie |

Ani jeden z nich nebeží na pracovnej stanici tak, ako je dodaný, a prvý z nich
nebeží **vôbec** — pozri [BUGS.md](BUGS.md).

Sú **referencované, nie vendorované**: nič v nich nemeníme, sú v gitignore a každá
adaptácia žije vedľa nich (compose override, lokálne postavený image, patche
aplikované pri builde — pozri [Štruktúra](#štruktúra)). Keďže `BUGS.md`
a `EVALUATION.md` citujú presné čísla riadkov a chovanie z konkrétnych commitov,
`./fetch-upstream.sh` naklonuje všetky štyri **pripnuté na commity, voči ktorým
bolo všetko overené**, a nie na to, čo upstream obsahuje práve dnes:

```bash
./fetch-upstream.sh
```

Opakované spustenie nič nerobí, keď sú klony na pripnutých commitoch; ak sa pin
niekedy zmení, skript klon odplytčí (`unshallow`) a presunie.

---

## Dokumentácia

|     | Dokument                                         | Obsah |
|-----|--------------------------------------------------|-----|
| 1   | **[SETUP.md](SETUP.md)**                         | Lokálne spustiteľný setup: prerekvizity, Llama Stack image, ktorý staviame, modely, ingestion, každodenná prevádzka |
| 2   | **[GUARDRAILS.md](GUARDRAILS.md)**               | NeMo Guardrails ako transparentný proxy, samotné rails a ako UI vystavuje prepínač rails zap/vyp |
| 3   | **[EVALUATION.md](EVALUATION.md)**               | RAGAS evaluácia cez TrustyAI llama-stack provider, metriky a harness |
| 4   | **[EVALUATION-LIMITS.md](EVALUATION-LIMITS.md)** | Čo evaluácia **nemeria** — odmerané slepé miesta (fakty vs. plynulosť, slovenčina netestovaná) a backlog zlepšení podľa priority |
| 5   | **[SLOVAK-EVAL.md](SLOVAK-EVAL.md)**             | Či modely brzdí samotná slovenčina — paralelné sk/en porozumenie a rubrika na gramatiku, teda diera pomenovaná v §4.4 |
| —   | **[BUGS.md](BUGS.md)**                           | Každá chyba a pasca, na ktorú sme v projekte narazili, spolu s opravou |

---

## Architektúra

```
                host (Linux, NVIDIA RTX PRO 6000 Blackwell, 96 GB VRAM)
  ┌───────────────────────────────────────────────────────────────────────┐
  │  ollama serve  (0.0.0.0:11434)                                        │
  │    LLM         gemma3 27B · gemma4 31B · qwen3.6 27B · llama3.2 3B    │
  │    embeddings  qwen3-embedding 4B (dim 2560)                          │
  └───────▲───────────────────────────────────▲───────────────────────────┘
          │ priamo                            │ cez proxy
  ┌───────┴───────────────────┐   ┌───────────┴──────────────┐
  │ rag-llamastack  :8321      │   │ nemo-guardrails  :9000   │
  │ Llama Stack 0.6.0          │   │ vstupné + výstupné rails │
  │  inference · vector_io      │   └──────────────────────────┘
  │  files · agents · safety    │
  │  eval (TrustyAI RAGAS)      │◄──── harness v rag-eval/
  └───────▲────────────────────┘
          │ 0.6.0 API
  ┌───────┴────────────────────┐
  │ rag-ui  :8501  (Streamlit) │   výber modelu = model × rails zap/vyp
  └────────────────────────────┘
```

Vektorové dáta sú v OpenAI-štýlových vector stores (pod kapotou FAISS). Ollama
obsluhuje aj chat LLM, aj embedding model; všetko ostatné beží v rootless podman
kontajneroch na sieti `local_rag-network`.

---

## Rýchly štart

Predpokladá, že jednorazový setup z [SETUP.md](SETUP.md) je hotový (podman,
Ollama, lokálne postavený Llama Stack image, stiahnuté modely).

```bash
./fetch-upstream.sh   # 0. pripnuté upstream klony (pozri "Upstream" vyššie)
./start-stack.sh      # 1-3. Ollama na hoste + nemo-guardrails + llamastack + rag-ui
```

`start-stack.sh` naštartuje **všetky** časti — Ollamu na hoste, NeMo Guardrails
proxy aj kontajnery llamastack/rag-ui — a je **idempotentný**: spustí len to, čo
ešte nebeží. Po uvoľnení VRAM (keď kontajnery zastavíš, aby si uvolnil miesto pre
niečo iné) tak vráti všetko jedným príkazom namiesto toho, aby si si musel
pamätať, koľko tých častí vlastne je. Presne tomuto zlyhaniu má predchádzať:
zabudnutý zastavený `nemo-guardrails`, kým Ollama a llamastack bežali, spôsobil,
že **každý** model `nemo/*` v UI odpovedal generickou chybou HTTP 500 — a nikde
nebolo vidieť, že chýbajúcim dielikom je guardrails kontajner (pozri
[BUGS.md](BUGS.md)).

`./stop-stack.sh` je zrkadlový obraz a jeho skutočnou úlohou je **vrátiť GPU**: do
VRAM sa naraz zmestí len jeden model triedy 27B, takže čokoľvek iné, čo kartu
chce, potrebuje tieto váhy najprv vyložiť. Zastaviť kontajnery nestačí — váhy drží
Ollama na *hoste*, takže ich skript vyloží explicitne a výsledok potom overí proti
`nvidia-smi`, namiesto aby ho predpokladal: vypíše, koľko sa reálne uvoľnilo, a
pomenuje proces, ktorý kartu prípadne stále drží.

```bash
./stop-stack.sh                 # všetko dole, VRAM uvoľnená
./stop-stack.sh --keep-ollama   # uvoľní VRAM, server nechá bežať
```

Kým beží evaluačný job, odmietne sa spustiť — plný benchmark trvá ~12 h a celý čas
komunikuje s Ollamou aj llamastackom — pokiaľ nedostane `--force`.

Dokumenty načítaj raz (nie je to súčasť `start-stack.sh` — opakovaný ingestion
nevytvorí no-op, ale duplicitné vector stores):

```bash
.client06-venv/bin/python ingest-0.6.0.py                       # demo korpus
.client06-venv/bin/python ingest-0.6.0.py http://localhost:8321 docs/data/vszp vszp
```

Otvor **<http://localhost:8501>**.

```bash
curl -s http://localhost:8321/v1/health                          # {"status":"OK"}
curl -s http://localhost:8321/v1/models                          # LLM + embeddings
curl -s http://localhost:8321/v1/vector_stores                   # naingestované korpusy
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8501   # UI -> 200
```

---

## Štruktúra

```
llamastack-local-image/   Llama Stack 0.6.0 image, ktorý staviame, jeho run config
                         a dva patche zdrojov aplikované pri builde
nemo-local/              image NeMo Guardrails servera a jeho rails config
rag-eval/                RAGAS harness (run_rag.py -> score_ragas.py)
ingest-0.6.0.py          ingestion dokumentov cez 0.6.0 Files/Vector-Stores API
compose-model-override.yml  prepisuje model hardcodovaný v upstreame a pri štarte
                            kontajnera aplikuje patch-max-tokens-slider.py na
                            rag-ui — samotný klon RAG/ sa nikdy nemení
patch-max-tokens-slider.py  opravuje slider "Max Tokens" v UI (pozri BUGS.md D10)
fetch-upstream.sh        klonuje štyri repozitáre nižšie, pripnuté na overené commity
start-stack.sh           štartuje Ollamu na hoste + nemo-guardrails + llamastack/rag-ui;
                        idempotentný, bezpečne spustiteľný kedykoľvek
stop-stack.sh            zastaví všetky štyri a vyloží modely, aby uvoľnil VRAM;
                        výsledok overí, počas evaluácie sa odmietne spustiť
RAG/ nemo-guardrails/ ragas-poc/ ragas-provider/   upstream klony (v gitignore)
docs/                    interné dokumenty (v gitignore, okrem sk-translation/)
```

V upstream klonoch sa nič nemení. Každá adaptácia žije vedľa nich: compose
override, lokálne postavený image otagovaný názvom, ktorý upstream compose
očakáva, a patche inštalovaných balíkov aplikované pri builde.
