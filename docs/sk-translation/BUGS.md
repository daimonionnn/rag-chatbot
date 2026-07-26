<!-- translated-from: ddb460e -->
# Chyby, pasce a opravy

> **Slovenský preklad.** Zdroj: [`../../BUGS.md`](../../BUGS.md) v commite
> `ddb460e`. Anglický originál je zdroj pravdy — ak sa rozchádzajú, platí on.
> Prehľad prekladov: [INDEX.md](INDEX.md).

Všetko, čo bolo treba zdiagnostikovať, aby tento stack bežal, cez všetky tri fázy.
Zoskupené podľa príčiny, nie podľa fázy, pretože tie isté príčiny sa opakujú.

Väčšinu stráveného času vysvetľujú dva vzory:

1. **Nepripnuté závislosti.** Každý upstream tu deklaruje aspoň jednu závislosť
   bez hornej hranice verzie. V deň vydania boli správne a dnes sa resolvnú na
   niečo nekompatibilné. Šesť samostatných zlyhaní nižšie je práve toto.
2. **Ticho prehltnuté výnimky.** Dve zlyhania hlásili *úspech* alebo *prázdnu
   chybu*, pričom nerobili vôbec nič. Tieto sú tie drahé: nič nevyzerá rozbité,
   takže sa dajú nájsť len tak, že si overíš, či daná vec naozaj robí svoju prácu.

Každá chyba v sekcii A je opravená patchom aplikovaným pri builde, takže plná
funkčnosť upstreamu — vrátane všetkých šiestich RAGAS metrík — je dostupná.

---

## A. Skutočné chyby v upstreame, opatchované

### A1. Non-latin-1 názvy súborov ticho zlyhávajú pri ingestione — **kritické pre slovenčinu**

`llama-stack 0.6.0`, `providers/inline/files/localfs/files.py`:

```python
headers={"Content-Disposition": f'attachment; filename="{file_obj.filename}"'}
```

Hodnoty HTTP hlavičiek sú latin-1, takže akýkoľvek názov súboru so znakom nad
U+00FF spôsobil, že Starlette vyhodila `UnicodeEncodeError`. llama-stack ju
zachytil počas priloženia súboru do vector storu a nahlásil `status: failed`
s **prázdnym `last_error`** — čítalo sa to presne ako problém s parsovaním PDF,
a to isté PDF pod ASCII názvom sa naingestovalo bez problému.

Hranica latin-1 je hranicou zlyhania, čo je pre slovenčinu nepríjemné:

| Znaky               | V latin-1? | Výsledok      |
|---------------------|------------|---------------|
| `á é í ó ú ý ô ä`   | áno        | naingestované |
| `č ď ľ ĺ ň ŕ š ť ž` | **nie**    | ticho zlyhalo |

Takže *väčšina* slovenských názvov súborov sa rozbila, kým niekoľko fungovalo —
ľahko sa to dá mylne prečítať ako náhoda. Nájdené bisekciou po jednom znaku, kým
sa hranica neukázala presne na U+00FF.

**Oprava:** [`llamastack-local-image/patch-content-disposition.py`](../../llamastack-local-image/patch-content-disposition.py)
generuje hlavičku podľa RFC 5987/6266 (`filename*=utf-8''<pct-encoded>`), teda
presne to, čo robí samotná `FileResponse` v Starlette. Názvy súborov si diakritiku
zachovajú od začiatku do konca.

### A2. RAGAS embeddings zablokujú eval job

`llama-stack-provider-ragas`, `inline/wrappers_inline.py` — upstream si to sám
označuje `TODO`:

```python
def embed_query(self, text):
    # TODO: propose a way to configure BaseRagasEmbeddings to use sync or async
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(self.aembed_query(text))
```

ragas je riadený z worker threadu (`asyncio.to_thread`), takže
`get_event_loop()` vráti loop *servera*, ktorý už beží →
`RuntimeError: This event loop is already running`, a celý job zlyhá.

Izolovalo sa to čisto: `faithfulness` (len LLM) dobehla, kým
`answer_relevancy` / `answer_similarity` a spol. všetky zomreli — pretože sync
cesta LLM wrappera vyhadzuje `NotImplementedError`, čím ragas núti na async cestu,
zatiaľ čo embeddings wrapper nabízí tento rozbitý sync most.

**Oprava:** [`llamastack-local-image/patch-ragas-embeddings-loop.py`](../../llamastack-local-image/patch-ragas-embeddings-loop.py)
si loop zachytí pri konštrukcii a koroutiny odovzdáva cez
`asyncio.run_coroutine_threadsafe` — správny primitív na volanie do loopu z iného
threadu.

### A3. `factual_correctness` zabije eval job

Ten istý súbor, cyklus zbierajúci výsledky:

```python
for metric_name in [m.name for m in metrics]:
    metric_scores = result[metric_name]
```

ragas nekľúčuje skóre vždy čistým názvom metriky (`ragas/evaluation.py`):

```python
if isinstance(m, ModeMetric):
    key = f"{m.name}(mode={m.mode})"
else:
    key = m.name
```

`FactualCorrectness` je `ModeMetric` s `mode="f1"`, takže jej skutočný kľúč je
`factual_correctness(mode=f1)` a celý job zomrie na
`KeyError: 'factual_correctness'`. Čisto nezhoda konvencie pomenovania — samotná
metrika je v poriadku.

**Oprava:** [`llamastack-local-image/patch-ragas-mode-metrics.py`](../../llamastack-local-image/patch-ragas-mode-metrics.py)
vyhľadá kľúč tak, ako ho ragas zapísal (čistý názov → `<name>(mode=…)` →
akýkoľvek `<name>(…)`), pričom stále reportuje pod čistým názvom. Tým sa získa
šiesta metrika, takže je dostupná plná sada metrík z PoC.

Všetky tri patche sú idempotentné a **zhodia build**, ak upstream zdroj už
nesedí — takže nemôžu pri upgrade ticho prestať platiť.

---

## B. Tiché zlyhania (žiadna chyba, funkcia len chýba)

### B1. fastText + NumPy 2 úplne vyradia jazykovú rail

`nemo-local/configs/rag/actions.py`:

```python
except Exception:
    return "allowed"
```

fastText stále volá `np.array(..., copy=False)`, čo NumPy 2 odmieta
s `ValueError`. Každé `predict()` teda vyhodilo výnimku, holý `except` ju zmenil
na `"allowed"` a jazyková rail **nikdy nič nezablokovala**, pričom vyzerala
úplne zdravo. Priamo pozorované: anglický vstup preplával railou, ktorej celým
zmyslom je ho odmietnuť.

**Oprava:** `numpy<2` pripnuté v `nemo-local/Containerfile`. Následne overené, že
angličtina skóruje `blocked` (lang=en, conf 0,911) a slovenčina `allowed`.

### B2. Pozri tiež A1

`status: failed` s prázdnym `last_error` je tá istá trieda problému: zlyhanie
bolo nahlásené, ale bez akejkoľvek informácie — a vierohodne vyzerajúce
vysvetlenie (zlé PDF) bolo nesprávne.

---

## C. Nepripnuté / rozbehnuté závislosti

Na C1–C3 a C6 sa narazilo pri pokuse reprodukovať image 0.2.9, čo je dôvod, prečo
sa ten pokus opustil v prospech zladenia na 0.6.0.

### C1. `llama stack build` inštaluje `llama-stack` nepripnutý

Jeho generovaný Containerfile stiahne, čo je práve aktuálne — 0.7.x namiesto
staväného 0.2.9. Entrypoint `llama_stack.distribution.server.server` v 0.7.x už
neexistuje, takže kontajner by ani nenaštartoval.

**Oprava:** pripnúť verziu, ktorá sa stavia.

### C2. `datasets` sa resolvne na 1.1.1, z roku 2020

Stiahnutý tranzitívne počas pokusu o 0.2.9. Zlyhá pri štarte servera na
`AttributeError: module 'pyarrow' has no attribute 'PyExtensionType'`.

**Oprava:** vynútiť `datasets>=3`.

### C3. `llama-stack 0.6.0` deklaruje `llama-stack-api` bez hranice

Resolvne sa na 0.7.2 a CLI sa potom ani nenačíta:
`ImportError: cannot import name 'agents' from 'llama_stack_api'`.

**Oprava:** pripnúť všetky tri llama-stack balíky na 0.6.0.

### C4. `ragas 0.4.3` deklaruje svoju langchain trojicu bez hraníc

`langchain`, `langchain-core` aj `langchain-community` sú bez hraníc;
langchain-community sa resolvne na 0.4.2, kde modul, ktorý ragas importuje, už
nie je — `ModuleNotFoundError: langchain_community.chat_models.vertexai`. ragas sa
tak neimportuje vôbec.

**Oprava:** `langchain-community>=0.3,<0.4`.

### C5. Chýbajúci `greenlet`

Označené v dokumentácii samotného providera: `inline/files/localfs` hlási chybu
„greenlet not found".

**Oprava:** `greenlet==3.2.4`.

### C6. `trl` si tahá `liger_kernel`

Počas pokusu o 0.2.9 zhodil `ModuleNotFoundError: liger_kernel` štart cez
provider `post_training`.

**Oprava:** tréningové providery sa z run configu vypustili úplne — RAG chatbot
z nich nepotrebuje ani jeden.

---

## D. Rozchod API / configu

### D1. UI odmietnuté s HTTP 426

`Client version 0.6.0 is not compatible with server version 0.2.9` — repozitár
pripína UI klienta na 0.6.0 voči 0.2.9 server image.

**Oprava:** zladiť server na 0.6.0. Samotné `LLAMA_STACK_DISABLE_VERSION_CHECK=1`
nestačí — pozri D2.

### D2. S vypnutou kontrolou verzie volania UI vracajú 404

`vector_stores`, `responses`, `conversations` ani `chat/completions` pred 0.6.0
neexistujú, takže utíšenie kontroly zlyhanie len posunie.

**Oprava:** to isté ako D1 — zladiť server, nie kontrolu prelepiť.

### D3. `You must provide a URL … to use vLLM`, hoci config ju obsahuje

`remote::vllm` v 0.6.0 očakáva `base_url`. Záložný run-config z upstreamu používa
starší kľúč `url:`, ktorý sa ticho ignoruje.

**Oprava:** použiť `base_url`.

### D4. `Embedding model 'X' not found`

Chyba vypíše `['sentence-transformers/sentence-transformers/…']` — pretože
`vector_stores.default_embedding_model` sa vyhľadáva ako `provider_id/model_id`,
takže `model_id` musí zopakovať vlastnú cestu k modelu daného providera.

**Oprava:** odkazovať sa plným identifikátorom.

### D5. `nemoguardrails` odmieta config

Hlási „0.21-style LangChain conventions": verzia ≥0.23 premenovala
`openai_api_base` na `base_url`.

**Oprava:** premenovať kľúč.

### D6. NeMo `/v1/models` vracia `MAIN_MODEL_BASE_URL is not set`

Čo rozbije výpis modelov v llama-stacku — ten endpoint potrebuje upstream base URL
v prostredí.

**Oprava:** nastaviť `MAIN_MODEL_BASE_URL`.

### D7. NeMo vracia `Internal server error`, log ukazuje `model 'rag' not found`

Pole `model` z chat requestu sa preposiela do Ollamy, takže posielať tam *config
id* je nesprávne.

**Oprava:** posielať skutočný názov modelu; config prichádza
z `--default-config-id`.

### D8. Presunuté do A3

Bolo to „eval job zomiera na `KeyError: 'factual_correctness'`". Keď sa ukázalo, že
je to opraviteľná chyba providera, nie rozchod configu, presunulo sa to do
[A3](#a3-factual_correctness-zabije-eval-job). Číslo je ponechané ako stub, aby
existujúce odkazy nemierili na nesprávny záznam.

### D9. `Unknown metric: answer_correctness`

Varovanie, po ktorom nasleduje zlyhaný job. Premenované v ragas 0.4.x.

**Oprava:** používať aktuálne názvy metrík.

### D10. Slider „Max Tokens": nedosiahnuteľný strop a default, ktorý vyprázdňuje odpovede

Za jedným ovládacím prvkom sú dve nezávislé príčiny.

**(a) Strop je lož.** `st.slider(label, min, max, value, step)` dáva len hodnoty
dosiahnuteľné krokovaním od `min`, takže upstream `(1, 4096, 512, 64)` končí na
`1 + 63*64 = 4033` — ďalší krok, 4097, by prekročil deklarovaných 4096.

**(b) Strop kryje reasoning, nie len odpoveď.** Na OpenAI-kompatibilnej ceste
`max_tokens` limituje reasoning + content *spolu*. Namerané na gemma4
s `max_tokens=200`: reasoning spotreboval celý budget, `content` sa vrátil ako
`""` s `finish_reason=length` — prázdna odpoveď, žiadna chyba. Bez stropu gemma4
spotrebuje 1686–2168 completion tokenov na odpoveď, z toho ~900 na reasoning,
takže default 512 sedel hlboko v pásme, kde sa thinking modely vyprázdňujú.

**Oprava:** `(0, 24576, 16384, 128)` — každá hranica je presný násobok kroku, takže
strop je dosiahnuteľný, a obe sa zmestia do kontextového budgetu. Pozor, že
`max_tokens` si delí `OLLAMA_CONTEXT_LENGTH` (32768) s promptom (~434 tokenov na
načítaný chunk), takže strop 32000 by sa **nikdy** nezmestil, ani pri Top K=5,
a spôsobil by, že Ollama ticho zahodí načítané chunky. Aplikované pri štarte
kontajnera skriptom `patch-max-tokens-slider.py`.

---

## E. Pasce prostredia a prevádzky

### E1. Container image je privátny

`llamastack/distribution-ollama:0.2.9` nedá pull scope ani prihlásenému účtu
a nemá mirror na quay/ghcr. Zdiagnostikované dekódovaním Docker Hub tokenu:
`access: []` pre tento repozitár, kým `grafana/grafana` vrátil normálny pull
grant — takže to bol repozitár, nie naše prihlasovacie údaje.

### E2. Žiadny predvolený registry

Ubuntu v `registries.conf` nenastavuje `unqualified-search-registries`, takže
krátke názvy images z compose súboru sa nedajú vôbec resolvnúť.

### E3. Ollama sa viaže na loopback

Systemd unit počúva na `127.0.0.1`, kam rootless kontajnery nedovidia. Spusti ju
na `0.0.0.0`.

### E4. Ollama zaplní VRAM KV cache

Automaticky dimenzuje kontext podľa dostupnej VRAM — 3B model si zabral **77 GB**.
Model o veľkosti 54–64 GB by potom skončil na OOM. Zastropuj
`OLLAMA_CONTEXT_LENGTH`.

### E5. Tichý offload na CPU

Iný proces (LM Studio, držiace 73,5 GB) nechal príliš málo VRAM, takže Ollama
umiestnila na GPU len 37 % modelu a zvyšok bežal na CPU — pričom `ollama ps` ho
stále uvádzal ako načítaný. Porovnaj `size_vram` so `size`; rozdelenie sa
rozhoduje v čase načítania a drží sa.

### E6. Rozdelený (sharded) GGUF sa nedá naimportovať

`ollama create` zlyhá s `split GGUF … has 1 shards, expected 2`, takže model už
stiahnutý cez LM Studio sa nedal využiť. Knižničný build je aj tak bezpečnejšia
voľba: obsahuje chat template, od ktorého tool calling závisí.

### E7. Zrušené sťahovania nechávajú odpad na disku

Ollama nemá príkaz na prune. `blobs/*-partial*` plus bloby, na ktoré neodkazuje
žiadny manifest, dali dokopy **98 GB**.

### E8. Zabíjanie sťahovania si vyžaduje pozornosť

Prvý `kill` zasiahol len wrapper proces a nechal bežať druhý `ollama pull` — dve
sťahovania si potom delili linku. Skontroluj cez `pgrep -af`.

### E9. podman `depends_on` blokuje odstránenie

`podman rm -f rag-llamastack` zlyhá, kým existuje `rag-ui`. Najprv odstráň
závislé kontajnery.

### E10. `pkill -f` môže zabiť vlastný shell

Vzor sa nachádza v argv samotného volajúceho príkazu, takže
`pkill -f "ollama pull"` matchol a zabil shell, ktorý ho spustil. Použi port
(`fuser -k`) alebo regex, ktorý sa nemôže matchnúť sám na seba.

### E11. Jeden zastavený kontajner rozbije časť modelov, bez lokálnej stopy

`nemo-guardrails` bol zastavený (spolu so všetkým ostatným), aby sa uvolnila VRAM
pre benchmark, a potom sa naštartovali len `llamastack`/`rag-ui`. Ollama aj každý
model `ollama/*` fungovali bez problémov; každý model `nemo/*` v UI odpovedal
`HTTP 500`, pričom nič v logoch samotného chatbota neukazovalo na to, že „guardrails
kontajner nebeží" — zlyhanie sa prejaví o jednu vrstvu ďalej od svojej príčiny.

**Oprava:** `./start-stack.sh` (koreň repozitára) naštartuje všetky štyri časti
spolu a je bezpečne spustiteľný kedykoľvek.

### E12. Relatívny zdroj bind-mountu v compose *override* sa resolvne inde

`compose-model-override.yml` (koreň repozitára) deklaroval
`volumes: [./patch-max-tokens-slider.py:...]`. podman-compose resolvol `./` voči
adresáru **základného** compose súboru (`RAG/deploy/local`), nie voči adresáru
samotného override súboru. Tam tá cesta neexistovala, takže podman namiesto chyby
ticho bind-mountol automaticky vytvorený **prázdny adresár** — a kontajner sa
zacyklil na `python /tmp/patch-....py` s výrazne nepomáhajúcim
`can't find '__main__' module in '/tmp/patch-....py'`, čo je spôsob, akým Python
hovorí „toto je adresár, nie skript". Ešte horšie, ten prázdny adresár vznikol
*vnútri pripnutého, gitignorovaného klonu `RAG/`*.

**Oprava:** pre zdroje bind-mountov deklarované v override súbore používať
absolútnu cestu.

---

## F. Limity schopností modelov (nie chyby, ale rozbíjajú funkcie)

- **Gemma 3 nemá tool calling.** `ollama show` hlási len `completion, vision`,
  takže Agent mode v UI aj každé volanie `responses` s nástrojom `file_search`
  zlyhá s `500 … does not support tools`. Priamy RAG to neovplyvňuje.
  Gemma 4 31B a Qwen3.6 27B hlásia `tools` (aj `thinking`) a fungujú.
- **all-MiniLM-L6-v2 je anglocentrický.** Pre demo FantaCo v pohode, na slovenčinu
  slabý. Nahradený embeddingmi Qwen3-4B (dim 2560), čo zároveň sedí s pôvodným
  PoC.

---

## G. Korekcie urobené cestou

Zaznamenané preto, že prvé vysvetlenie bolo v každom prípade nesprávne — a to
nesprávne pritom vyzeralo vierohodne:

- Tie dve PDF, ktoré zlyhali pri ingestione, sa najprv zvalili na **názvy súborov
  s diakritikou vo všeobecnosti**. Nesprávne dvojnásobne: skutočným znakom bola
  en-dash (U+2013) a názov súboru s jediným slovenským `í` sa naingestoval bez
  problému. Skutočné pravidlo (hranicu latin-1, A1) odhalila až bisekcia po
  jednotlivých znakoch.
- Potom padlo podozrenie, že tie zlyhávajúce PDF **nemajú textovú vrstvu**.
  Nesprávne: `pypdf` z nich vytiahol 13 222 a 2 131 znakov — viac než z niekoľkých
  súborov, ktoré prešli.
- O „Gemma 4 31B" som spočiatku pochyboval, či vôbec existuje (knowledge cutoff).
  Existuje; jedno overenie v registry to vyriešilo.
