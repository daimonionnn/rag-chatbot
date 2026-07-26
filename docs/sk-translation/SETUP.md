<!-- translated-from: ddb460e -->
# 1 — Lokálne spustiteľný setup

> **Slovenský preklad.** Zdroj: [`../../SETUP.md`](../../SETUP.md) v commite
> `ddb460e`. Anglický originál je zdroj pravdy — ak sa rozchádzajú, platí on.
> Prehľad prekladov: [INDEX.md](INDEX.md).

Ako sa chatbot z [`Sheryl-shiyi/RAG`](https://github.com/Sheryl-shiyi/RAG)
(fork Red Hat blueprintu `rh-ai-quickstart/RAG`) rozbehal na tejto pracovnej
stanici. Guardrails sú v [GUARDRAILS.md](GUARDRAILS.md), evaluácia
v [EVALUATION.md](EVALUATION.md) a každá chyba, na ktorú sme cestou narazili,
v [BUGS.md](BUGS.md).

Cieľ: zostať tak blízko upstreamu, ako sa dá — rovnaká architektúra, rootless
podman, Ollama na hoste, vlastné `frontend/` UI z repozitára — a pritom dostať
chatbota, ktorý naozaj funguje.

---

## 1.1 Prečo upstream repozitár nemôže bežať tak, ako je dodaný

Jeho tri časti mieria na tri nekompatibilné verzie Llama Stacku:

| Komponent                      | Pripnutá verzia | API, ktorým hovorí |
|--------------------------------|-----------------|-----|
| `frontend/` (UI)               | **0.6.0**       | OpenAI-štýlové `vector_stores`, `responses`, `conversations`, `chat.completions` |
| compose image v `deploy/local` | 0.2.9           | staré `vector_dbs`, `inference.chat_completion` |
| `ingestion-service/`           | 0.2.22          | staré `vector_dbs`, `rag-tool/insert` |

Skutočný 0.2.9 server odpovie UI chybou **HTTP 426 („aktualizuj klienta")**, a keď
sa kontrola verzie vypne, jeho volania jednoducho vrátia **404** — tie
OpenAI-štýlové endpointy pred 0.6.0 neexistujú.

Navyše image, ktorý compose súbor pomenúva
(`llamastack/distribution-ollama:0.2.9`), je v **privátnom** Docker Hub
namespace: registry nedá pull scope ani prihlásenému účtu a neexistuje mirror na
quay.io ani ghcr.io.

**Riešenie: zladiť všetko na 0.6.0**, teda na verziu, na ktorú mieri UI, a ten
server si postaviť sami. UI používame nezmenené; upstream compose súbor nikdy
neupravujeme.

---

## 1.2 Prerekvizity na hoste

Raz bolo potrebné root:

```bash
sudo apt-get update
sudo apt-get install -y podman uidmap slirp4netns fuse-overlayfs passt
```

Bez rootu:

```bash
uv tool install podman-compose                       # ~/.local/bin/podman-compose
curl -fsSL https://ollama.com/install.sh | sudo sh   # Ollama + CUDA runtime
```

`uv`, `docker` a NVIDIA driver (v595 / CUDA 13.2, potrebný pre Blackwell) tu už
boli. Rootless podman navyše potrebuje dostupný Docker Hub pre base images —
Ubuntu žiadny predvolený registry nedodáva, takže
`~/.config/containers/registries.conf`:

```toml
unqualified-search-registries = ["docker.io"]
short-name-mode = "permissive"
```

```bash
podman login docker.io      # potrebné aj pre verejné base images ako python:3.12-slim
```

### Ollama musí počúvať na všetkých rozhraniach

Štandardná systemd unit sa viaže na `127.0.0.1`, kam rootless kontajnery
nedovidia. Spusti ju na `0.0.0.0`, so zastropovaným kontextom (pozri
[1.3](#13-modely)):

```bash
sudo systemctl stop ollama
OLLAMA_HOST=0.0.0.0:11434 OLLAMA_KEEP_ALIVE=60m OLLAMA_CONTEXT_LENGTH=32768 \
    nohup ollama serve > ~/development/rag-chatbot/ollama-serve.log 2>&1 &
```

Kontajnery ju potom nájdu na `http://172.17.0.1:11434` (gateway bridge siete).

---

## 1.3 Modely

```bash
ollama pull gemma3:27b-it-fp16       # 54 GB  plná presnosť
ollama pull gemma4:31b-it-bf16       # 62 GB  pridáva tool calling + thinking
ollama pull qwen3.6:27b-mtp-bf16     # 55 GB  tool calling + thinking
ollama pull qwen3-embedding:4b-fp16  #  8 GB  embeddings, dim 2560
```

Ollama pre gemma3 27b nezverejňuje tag `bf16` (len pre 270m), takže `-fp16` je jej
nekvantizovaný 16-bitový build. Varianty `q8_0` (~30 GB) existujú ako záloha, ak
by bola VRAM natesno.

### Zaregistrované modely

Každý LLM je vystavený dvakrát — priamo a cez guardrails proxy — takže výber
modelu v UI vyberá **model × rails zap/vyp** v jednom ovládacom prvku:

| Model v UI                                    | Tools / Agent mode | Thinking | VRAM (100 % GPU) |
|-----------------------------------------------|--------------------|----------|------------------|
| `ollama/gemma3:27b-it-fp16` · `nemo/…`        | ✗                  | ✗        | 55.0 GB          |
| `ollama/gemma4:31b-it-bf16` · `nemo/…`        | ✓                  | ✓        | 63.7 GB          |
| `ollama/qwen3.6:27b-mtp-bf16` · `nemo/…`      | ✓                  | ✓        | 53.6 GB          |
| `ollama/llama3.2:3b-instruct-fp16` · `nemo/…` | ✓                  | ✗        | 6.4 GB           |

Gemma 3 nezvláda tool calling (`ollama show` hlási len `completion, vision`),
takže **Agent mode** v UI a každé volanie `responses` nesúce nástroj
`file_search` na nej zlyhá s `500 … does not support tools`. Priamy RAG to
neovplyvňuje. Gemma 4 aj Qwen3.6 zvládajú oboje.

Do VRAM sa naraz zmestí **len jeden veľký model**, takže prepnutie v UI stojí
reload (~8 s teplý, ~30 s studený). Ollama si automaticky zaregistruje čokoľvek,
čo je stiahnuté, takže pridanie modelu si vyžaduje len reštart llamastacku —
žiadny rebuild image.

### Kontext musí byť zastropovaný

Ollama automaticky nadimenzuje KV cache tak, aby zaplnila dostupnú VRAM: pri 3B
modeli si zvolila 256K kontext a zabrala ~77 GB. Pri 54–64 GB váh by to skončilo
na OOM, takže server beží s `OLLAMA_CONTEXT_LENGTH=32768` — čo je stále výrazne
viac, než tento RAG potrebuje (`max_tokens_in_context` je 4000).

### Ak model skončí na CPU

Umiestnenie si over, nehádaj — `size_vram` oproti `size`:

```bash
curl -s http://localhost:11434/api/ps | python3 -m json.tool
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
```

Ollama rozhoduje o rozdelení GPU/CPU **v čase načítania**, podľa VRAM voľnej práve
vtedy, a to rozhodnutie si drží. Ak VRAM drží niečo iné (tu to bol `llama-server`
z LM Studia, 73,5 GB pre Qwen s 256K kontextom), model sa načíta prevažne do RAM
a beží pomaly — pričom `ollama ps` ho spokojne uvádza ako načítaný. Uvolni VRAM,
potom `ollama stop <model>` a načítaj znovu.

### Hygiena disku

Zrušené sťahovanie po sebe nechá dáta a Ollama nemá príkaz na prune. Zmaž
`~/.ollama/models/blobs/*-partial*` a tiež každý blob, na ktorý neodkazuje žiadny
manifest v `~/.ollama/models/manifests/` — takto sa tu uvolnilo 98 GB.
Naimportovať už stiahnutý GGUF namiesto opakovaného sťahovania **nefunguje**, ak
je GGUF rozdelený na časti (`ollama create` zlyhá s `split GGUF … has 1 shards,
expected 2`), a knižničný build je aj tak bezpečnejší, lebo obsahuje chat
template, od ktorého tool calling závisí.

---

## 1.4 Lokálny Llama Stack 0.6.0 image

Stavaný z [`llamastack-local-image/`](../../llamastack-local-image/) a otagovaný
názvom, ktorý očakáva upstream compose, takže `podman-compose.yml` zostáva
nedotknutý:

```bash
podman build -f llamastack-local-image/Containerfile-0.6.0 \
  -t docker.io/llamastack/distribution-ollama:0.2.9 llamastack-local-image
```

- **`Containerfile-0.6.0`** — python:3.12-slim, závislosti providerov a
  `llama-stack` / `llama-stack-api` / `llama-stack-client` všetky pripnuté na
  **0.6.0**. Pripnuté musia byť všetky tri: llama-stack deklaruje
  `llama-stack-api` bez hornej hranice, takže nepripnutá inštalácia stiahne
  nekompatibilnú novšiu verziu.
- **`config-0.6.0.yaml`** — orezaný run config odvodený od `starter`: ollama
  inference (priamo + cez NeMo), Qwen3 embeddings, FAISS vector_io, localfs
  files + pypdf, meta-reference agents (OpenAI responses/conversations),
  llama-guard safety, tool runtime pre rag/websearch a TrustyAI RAGAS eval
  provider. Tréningový stack scoring/post_training/batches je vypustený.
- **dva patche aplikované pri builde** na inštalované balíky, oba vysvetlené
  v [BUGS.md](BUGS.md): non-latin-1 názvy súborov a event loop v RAGAS
  embeddings.

Starší `Containerfile` / `run.yaml` v tom adresári sú opustený pokus o 0.2.9,
ponechaný pre referenciu.

### Výber modelu

Upstream compose má hardcodované `INFERENCE_MODEL: llama3.2:3b-instruct-fp16`,
takže model sa mení cez
[`compose-model-override.yml`](../../compose-model-override.yml), nie jeho
úpravou. Ten súbor nastavuje aj `EMBEDDING_MODEL`, čo je to, čo aktivuje RAGAS
provider.

---

## 1.5 Ingestion

Kontajner `ingestion-service` z repozitára mieri na 0.2.x API `vector_dbs`, ktoré
0.6.0 UI nečíta, takže ho **nepoužívame**. Namiesto neho
[`ingest-0.6.0.py`](../../ingest-0.6.0.py) načítava dokumenty cez 0.6.0
Files + Vector-Stores API — chunking (pypdf) aj embedding robí server.

```bash
# jeden vector store na každý podadresár (demo korpus FantaCo)
.client06-venv/bin/python ingest-0.6.0.py

# všetko do jedného storu — to, čo potrebuje evaluačný korpus
.client06-venv/bin/python ingest-0.6.0.py http://localhost:8321 docs/data/vszp vszp
```

Chunking je 512 tokenov s overlapom 64 a embeddings sú Qwen3-4B (dim 2560), oboje
zhodné s pôvodným PoC. Qwen3 je tu ale aj jednoducho správna voľba:
all-MiniLM-L6-v2 je anglocentrický a na slovenčinu slabý. all-MiniLM zostáva
zaregistrovaný, aby staršie 384-rozmerné stores zostali použiteľné.

Názvy súborov sa posielajú tak, ako sú, vrátane diakritiky — prečo si to
vyžadovalo patch, je v zázname o Content-Disposition v [BUGS.md](BUGS.md).

Dokumenty sa dajú pridávať aj interaktívne zo stránky **Upload** v UI.

---

## 1.6 Každodenná prevádzka

`./start-stack.sh` z koreňa repozitára naštartuje všetko (Ollamu na hoste,
`nemo-guardrails`, `llamastack`, `rag-ui`) a je idempotentný — bezpečne
spustiteľný kedykoľvek, aj po zastavení kontajnerov kvôli uvolneniu VRAM pre
niečo iné.

Ak chceš `llamastack`/`rag-ui` riadiť ručne:

```bash
cd RAG/deploy/local && export PATH="$HOME/.local/bin:$PATH"

OLLAMA_URL=http://172.17.0.1:11434 TAVILY_SEARCH_API_KEY=disabled \
  podman-compose -f podman-compose.yml -f ../../../compose-model-override.yml \
  up -d llamastack rag-ui

podman-compose ps
podman logs -f rag-llamastack
podman-compose down          # named volume a Ollama prežijú
```

`make start` obchádzame: spúšťa aj nekompatibilný 0.2.x kontajner
`rag-ingestion` a jeho Makefile sa interaktívne pýta na Tavily kľúč. Explicitné
zdvihnutie `llamastack rag-ui` je tu ekvivalent.

### Reštart llamastacku

`podman rm -f rag-llamastack` zlyhá, kým existuje `rag-ui` — podman vynucuje
compose `depends_on` ako závislosť kontajnerov. Odstráň najprv `rag-ui`, potom
llamastack, a potom oba zdvihni.

---

## 1.7 Známe kozmetické problémy

- **`rag-llamastack` ukazuje `(starting)` / unhealthy** v `podman ps` — compose
  healthcheck testuje `/`, ktoré vracia 404, namiesto `/v1/health`. Server je
  v poriadku.
- **`llamastack -> HTTP 000` hneď po štarte** — potrebuje ~30 s na nabehnutie
  (torch, sentence-transformers). Radšej polluj `/v1/health`, než predpokladať
  zlyhanie.
- Pomocné venvs v koreni projektu sa dajú zmazať, ak treba miesto; potrebný je
  len `.client06-venv`, pre ingestion a evaluačné skripty.
