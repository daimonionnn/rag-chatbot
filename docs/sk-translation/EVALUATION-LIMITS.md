<!-- translated-from: 37f150b -->
# 4 — Čo táto evaluácia **nemeria**

> **Slovenský preklad.** Zdroj:
> [`../../EVALUATION-LIMITS.md`](../../EVALUATION-LIMITS.md) v commite `37f150b`.
> Anglický originál je zdroj pravdy — ak sa rozchádzajú, platí on. Prehľad
> prekladov: [INDEX.md](INDEX.md).

Kritika RAGAS setupu z [EVALUATION.md](EVALUATION.md): kde sú čísla
dôveryhodné, kde zavádzajú a čo zmeniť.

Priebežne sa používajú dva štítky a ten rozdiel je podstatný:

- **MEASURED** (odmerané) — overené na tomto stacku, s uvedenými hodnotami.
- **REASONED** (odvodené) — argument z toho, ako sú metriky postavené, zatiaľ
  neotestovaný.

Sekcie 4.1–4.8 vznikli, keď prvý plný benchmark ešte bežal, voči 2-riadkovému
smoke testu. §4.9 bol zoznam toho, čo znovu skontrolovať, až budú reálne dáta.
§4.10, doplnená potom, je práve tá kontrola — výsledky prišli a jeden z nich
(duplicitné otázky s nezhodnými referenciami) sa ukázal ako **najkonkrétnejší
nález celého dokumentu**.

---

## 4.1 Modely dokážu rozlíšiť len štyri zo šiestich metrík

**MEASURED.** Vstupy, ktoré každá metrika naozaj spotrebuje:

| Metrika               | Používa `response`? | Vstupy                                    |
|-----------------------|---------------------|-------------------------------------------|
| `faithfulness`        | áno                 | response, retrieved_contexts, user_input  |
| `answer_relevancy`    | áno                 | response, user_input                      |
| `answer_similarity`   | áno                 | reference, response                       |
| `factual_correctness` | áno                 | reference, response                       |
| `context_precision`   | **nie**             | reference, retrieved_contexts, user_input |
| `context_recall`      | **nie**             | reference, retrieved_contexts, user_input |

`context_precision` a `context_recall` odpoveď nikdy nevidia. Retrieval je tu pre
každý model identický — rovnaký vector store, rovnaký embedding, rovnaké top-5 —
takže tie dve merajú **vrstvu retrievalu, nie model**, a pre všetky tri vyjdú
v podstate rovnako.

**Náprava:** reportovať ich raz, ako vlastnosť konfigurácie retrievalu, nie ako
stĺpec per model. Inak tabuľka šiestich metrík naznačuje šesť nezávislých
porovnaní, kým v skutočnosti sú štyri.

---

## 4.2 Benchmark je úloha „nájdi a skopíruj", nie úloha na uvažovanie

**MEASURED.** Zo 182 QA párov, skontrolovaných voči FAQ PDF, ktoré je *v*
naingestovanom korpuse:

```
otázok nájdených doslovne v FAQ PDF     : 180 (99 %)
referenčných odpovedí nájdených doslovne : 180 (99 %)
```

Ground-truth odpoveď je doslova prítomná v texte, ktorý retriever načíta. Vysoké
skóre je preto očakávaný výsledok funkčnej pipeline, nie dôkaz silného
uvažovania — a model s lepším uvažovaním nemá takmer čo predvádzať. Vysvetľuje to
aj takmer perfektné počiatočné hodnoty (faithfulness 1,000, context_recall 1,000,
medián lexikálneho prieniku s referenciou 1,00).

**Dôsledky**

- Sada nedokáže zoradiť modely podľa uvažovania, syntézy či zvládania
  protirečivých zdrojov, pretože nič z toho neprecvičuje.
- `context_recall ≈ 1,0` znamená, že FAQ chunk sa načítal. Nehovorí nič o kvalite
  retrievalu pri otázkach formulovaných inak než FAQ.
- Reálni používatelia nebudú otázky formulovať tak, ako ich formuluje FAQ.

**Náprava:** pridať (a) parafrázované otázky, (b) otázky, ktorých odpoveď sa
rozkladá cez viac dokumentov, (c) otázky odpovedateľné len z *iných* dokumentov
korpusu (`Program Vernosť+`) a (d) neodpovedateľné otázky, aby sa dalo merať
odmietnutie odpovede.

---

## 4.3 `answer_similarity` je voči faktom takmer slepá — odmerané

**MEASURED.** `answer_similarity` je kosínusová podobnosť embeddingov odpovede
a referencie. Keď sa reálna referenčná odpoveď rôzne poruší a každý variant sa
oskóruje voči originálu:

| Variant referenčnej odpovede                           | Skóre      | Penalizácia |
|--------------------------------------------------------|------------|-------------|
| identická                                              | 1.0000     | —           |
| malé gramatické chyby (zlé pádové koncovky)            | 0.9985     | 0.0015      |
| **`30 eur` → `300 eur`** (10× nesprávna suma)          | **0.9899** | 0.010       |
| **negovaná** (`Nie je spoplatnená` → `Je spoplatnená`) | **0.9943** | 0.006       |
| **negovaná** (`môžete` → `nemôžete`)                   | 0.9636     | 0.036       |
| `raz za rok` → `raz za mesiac`                         | 0.9547     | 0.045       |
| úplne nesprávny obsah (celkom iné miesto)              | 0.7856     | 0.214       |
| **správna odpoveď, ale napísaná po anglicky**          | **0.8293** | 0.171       |

Tie dva zvýraznené riadky treba čítať spolu:

> Odpoveď tvrdiaca **presný opak** pravdy, alebo s **desaťnásobne nesprávnou sumou
> v eurách**, dostane **0,99**. **Úplne správna** odpoveď napísaná po anglicky
> dostane **0,83**.

Takže na tejto metrike samotnej plynulý slovenský nezmysel prekoná správnu
odpoveď v nesprávnom jazyku o veľký kus. Je to dobre známa vlastnosť embeddingovej
podobnosti — negácia a čísla sú v nej zastúpené slabo — nie chyba tohto setupu,
ale rozhoduje o tom, ako sa tie čísla musia čítať:

**`answer_similarity` je kontrola plynulosti a témy, nie kontrola správnosti.**
Faktická záťaž leží celá na `factual_correctness` (rozklad na tvrdenia)
a `faithfulness` (podloženie na úrovni jednotlivých tvrdení). Ak tieto dve
s `answer_similarity` nesúhlasia, ver im, nie jej.

**Náprava:** prestať brať `answer_similarity` ako hlavný ukazovateľ kvality. Pre
doménu plnú súm, limitov a podmienok nároku pridať cielenú kontrolu: vytiahnuť
z odpovede a z referencie čísla, dátumy a negácie a porovnať ich presne.
Nesprávna suma má zlyhať nahlas, nie stáť 0,01.

---

## 4.4 Slovenčinu tu nemeria vôbec nič

Toto bola otázka, ktorá tento dokument vyvolala: *ako dobre tieto testy zistia, či
je slovenčina modelu správna, a mohol by byť malý gramatický kiks potrestaný
tvrdšie než plynulá lož?*

**MEASURED, a odpoveď má dve časti.**

**Žiadna metrika v sade nemá kvalitu jazyka ako cieľ.** Ani jedna neskóruje
gramatiku, morfológiu, register či plynulosť. Správnosť slovenčiny jednoducho nie
je súčasťou merania.

**Konkrétna obava — že gramatika je potrestaná tvrdšie než lož — neplatí, ale
realita nie je o nič uspokojivejšia.** Z tabuľky v §4.3: gramatické chyby stoja
**0,0015**, negovaný fakt stojí **0,006–0,036**. Lož je teda penalizovaná viac —
ale obe hodnoty sú v šume. Skutočná deformácia je inde:

| Druh chyby                              | Penalizácia v `answer_similarity` |
|-----------------------------------------|-----------------------------------|
| rozbitá gramatika, správny obsah        | 0.0015                            |
| perfektná gramatika, negovaný fakt      | 0.006                             |
| perfektná gramatika, 10× nesprávna suma | 0.010                             |
| **správny obsah, nesprávny jazyk**      | **0.171**                         |

Metrika reaguje ~17× silnejšie na to, *v akom jazyku si odpovedal*, než na to,
*či bola odpoveď pravdivá*. A robí to zo nesprávneho dôvodu: nie preto, že by
hodnotila jazyk, ale preto, že iný jazyk je iná povrchová forma.

Praktické dôsledky pre produkt smerujúci na slovenských používateľov:

- Model odpovedajúci **plynulou češtinou** alebo kostrbatou, ale pochopiteľnou
  slovenčinou by skóroval dobre. Nič to neoznačí.
- Model odpovedajúci **správne po anglicky** by bol penalizovaný — ale ako
  vedľajší efekt, nie podľa jazykového pravidla, a nie dosť konzistentne, aby sa
  na to dalo spoľahnúť.
- **Gramatická kvalita je fakticky netestovaná.** Pre zákaznícky orientovaného
  asistenta je to reálna diera, keďže používatelia hodnotia práve to.

**Náprava — dve lacné doplnenia:**

1. **Detekcia jazyka na výstupe.** NeMo image už obsahuje fastText
   (`lid.176.ftz`) pre vstupnú rail; spusti rovnakú kontrolu na vygenerovaných
   odpovediach a reportuj podiel tých, ktoré sú po slovensky. Tým sa skryté
   zlyhanie zmení na číslo. Pozor na výhradu z [BUGS.md](BUGS.md) B1: fastText pri
   akejkoľvek výnimke ticho vráti „allowed", takže tú kontrolu treba tvrdo
   asertovať, nie jej veriť.
2. **Samostatné skóre plynulosti/gramatiky.** Krátka LLM-hodnotená rubrika
   (gramatika, morfológia, prirozdenosť, 1–5) prebehnutá cez odpovede, držaná
   *oddelene* od RAGAS čísel. Nesmie sa zliať do jedného ukazovateľa kvality,
   pretože plynulosť a faktická presnosť sa vymieňajú odlišne a majú zostať
   viditeľné ako dve osi.

**REASONED výhrada k obom:** judge je všeobecný multilingválny model, nie
slovenský natívny evaluátor, a jeho schopnosť posudzovať slovenské tvrdenia je
sama neoverená. Každá metrika, ktorá ide cez judge-a, tú neistotu dedí — vrátane
práve navrhovaného skóre plynulosti. Jediný spôsob, ako to kalibrovať, je vzorka
ohodnotená človekom.

---

## 4.5 Judge je jeden zo súťažiacich

**REASONED.** V súlade s upstream PoC hodnotí `gemma3:27b-it-fp16` všetky behy,
vrátane svojich vlastných odpovedí. U LLM-as-judge je zdokumentované, že
zvýhodňujú výstupy podobné vlastnému štýlu, takže gemma3 má štrukturálnu výhodu
neznámej veľkosti.

**Náprava:** krížové hodnotenie. Oskórovať odpovede každého modelu každým
z troch judge modelov a reportovať maticu. Ak sa poradie modelu zmení podľa
judge-a, poradie je o judge-ovi, nie o modeli.

**Odteraz nosné, 2026-07-27.** Táto výhrada prestala byť teoretická vo chvíli, keď
[EVALUATION.md §3.9](EVALUATION.md) položila na stôl poradie. gemma3 je prvá a
metrika, ktorú vyhráva najpresvedčivejšie — `factual_correctness`, +0.045 nad
druhým — je skórovaná judge-om, ktorým je gemma3. Poradie aj confound ukazujú tým
istým smerom, čo je presne prípad, pred ktorým táto sekcia varuje.

**MEASURED, 2026-08-01, a hypotéza bola nesprávna poučným spôsobom.** Všetky tri
modely boli preskórované na stratifikovanej podmnožine 40 riadkov judge-om
`anthropic/claude-opus-5` — judge-om, ktorý nie je jedným zo súťažiacich, čím
žiadny lokálny model byť nemôže. Plné čísla a metóda:
[EVALUATION.md §3.10](EVALUATION.md).

Víťaz každej metriky je pod neutrálnym judge-om nezmenený a náskok gemma3 na
`factual_correctness` nad gemma4 sa **rozšíri** z +0.065 na +0.109. Confound teda
bol skutočný, ale mieril opačne: gemma3 hodnotiaca samu seba svoj margin
*podhodnocovala*, nie vyrábala. Obava, ktorú táto sekcia vzniesla, bola
oprávnená — záver, ktorého sa obávala, nie.

Čo neprežilo, je časť, o ktorú sa nikto nebál — alebo tak to aspoň vyzeralo pri
dvoch judge-och. gemma4 a qwen3.6 delilo na `factual_correctness` +0.064 pod
gemma3 a **+0.004** pod neutrálnym judge-om, čo sa čítalo tak, že druhé miesto je
artefakt.

**Tretí judge to opravil** ([EVALUATION.md §3.11](EVALUATION.md), 2026-08-02).
Pod qwen3.6 je tá istá dvojica oddelená o +0.0995 — naprieč tromi judge-mi teda
odstup siaha od remízy po desať bodov, kým poradie sa neprevráti ani raz.
Neutrálny judge bol outlier, nie rozhodca, a zovšeobecniť z neho bola tá istá
chyba, pred akou táto sekcia varuje, o úroveň vyššie.

**Self-preference sa tu nedá detegovať vôbec.** qwen3.6 hodnotí vlastné odpovede
0.6188 — najnižšia hodnota v celej matici — a je na seba trikrát prísnejšia než
na súperov. gemma3 hodnotí samu seba o +0.0195 vyššie než neutrálny judge, čo je
pod rozlíšením vzorky 0.025. Ani jeden z modelov, ktoré hodnotili vlastnú prácu,
si neprihral.

Čo to stále nezatvára. Neutrálny judge je promptovaný cez chat completions, kým
lokálni používajú raw text completions (BUGS.md A4), takže „iný judge" a „iné
zarámovanie" sú navzájom confoundnuté. A traja judge-ovia nie sú náhodná vzorka
judge-ov — dvaja z nich sú súťažiaci — takže „self-preference sa nedá detegovať"
je tvrdenie o týchto troch, pri rozlíšení vzorky 0.025.

---

## 4.6 Jeden beh, takže malé rozdiely nič neznamenajú

**REASONED.** Všetko beží raz, pri `temperature 0`. To rozptyl znižuje, ale
neodstraňuje: judge rozkladá tvrdenia a vydáva verdikty a tie cesty nie sú
bit-stabilné. Neexistuje opakovanie, kontrola seedu ani interval spoľahlivosti,
takže **rozdiel jedného či dvoch bodov medzi modelmi nie je interpretovateľný.**

**Náprava:** preskórovať odpovede jedného modelu 3–5× a rozptyl brať ako šumový
prah. Potom reportovať len rozdiely, ktoré ho presahujú. Lacná verzia: opakovať na
40 riadkoch namiesto 182.

**Čiastočne vyriešené, 2026-07-27.** Experiment thinking vs. bez thinkingu
([EVALUATION.md §3.8](EVALUATION.md)) dodal šumový prah ako vedľajší produkt, bez
akýchkoľvek nákladov navyše. Prehnal oba thinking modely znova proti rovnakému
judge-ovi a **rovnakým načítaným kontextom, prevzatým bajt po bajte**, takže
`context_precision` a `context_recall` — ktoré skórujú retrieval, nie odpoveď —
nemali čo reálne merať. Čímkoľvek sa pohli, je judge nesúhlasiaci sám so sebou:

| Retrieval metrika | gemma4 Δ | qwen3.6 Δ |
|-------------------|---------:|----------:|
| context_precision | −0.0014  | −0.0063   |
| context_recall    | −0.0027  | +0.0000   |

Na tomto harnesse je teda **|Δ| zhruba do 0.006 šum**, a to, že sa `context_recall`
pre qwen3.6 zreprodukoval na cifru presne, ukazuje, že samotná pipeline je
stabilná. Aplikované na tabuľku v §3.7 to stačí na zabitie menších medzimodelových
rozdielov a na potvrdenie tých väčších — a jedno zistenie to už preklasifikovalo:
zmena `factual_correctness` u gemma4 bez thinkingu (−0.0051) sa najprv čítala ako
slabý signál a proti tomuto prahu je to šum.

Stále to nie je plná náprava. Je to jedno párované porovnanie na model, nie tých
3–5 opakovaní vyššie, takže dáva rád veľkosti a nie interval spoľahlivosti,
a nehovorí nič o šume konkrétne na `answer_relevancy` či `factual_correctness` —
teda na tých dvoch metrikách, kde judge robí najviac práce a je teda najskôr
najmenej stabilný.

---

## 4.7 Veci, ktoré sa nemerajú vôbec

| Diera                            | Prečo je podstatná |
|----------------------------------|-----|
| **Guardrailovaná cesta**         | Hodnotí sa len `ollama/*`. Cesta `nemo/*` — tá so safety rails a najbližšia produkcii — sa neskóruje nikdy, takže kvalitatívna aj latenčná cena rails je neznáma. |
| **Latencia, VRAM, priepustnosť** | 64 GB model, ktorý je citeľne pomalší za +1 bod, je zlý produkčný kompromis, ale sada z toho nevidí nič. Rýchlosť generovania aj VRAM sú per model známe (pozri [SETUP.md](SETUP.md)) a patria do tej istej tabuľky ako skóre. |
| **Správne odmietnutie odpovede** | Keď retrieval mine, povedať „toto v dokumentoch nie je" je správne chovanie — jedna odpoveď gemma3 to presne urobila. Voči referencii obsahujúcej reálny obsah jej `factual_correctness` dá 0, teda rovnako ako sebavedomej výmyselnine. Čestné odmietnutie a halucinácia sú v týchto číslach nerozlíšiteľné. |
| **Konfigurácia retrievalu**      | `top_k=5`, chunk 512/overlap 64 sú fixne na hodnotách z PoC a nikdy sa nemenili, takže nie je známe, či je retrieval úzkym hrdlom. |
| **Režim `factual_correctness`**  | Beží na predvolenom `mode=f1`, ktorý balansuje precision a recall. Pre túto doménu je precision (nevymýšľať nároky) pravdepodobne dôležitejšia než recall a ten režim si zaslúži vedomú voľbu. |

---

## 4.8 Backlog zlepšení, podľa priority

Preusporiadané po tom, ako §4.10 priniesla odmeraný výsledok: oprava datasetu
teraz prevažuje nad všetkým, keďže dokázateľne hýbe číslami viac než akýkoľvek
nájdený rozdiel medzi modelmi.

0. **Opraviť tých 23 duplicitných otázok s úzkou referenciou** (§4.10.2). Odmerane
   stláča `factual_correctness` viac než akýkoľvek rozdiel medzi modelmi
   v benchmarku, a to u všetkých troch modelov — absolútnym číslam sa teda nedá
   veriť, kým sa to neopraví. Poradie na tom ale **nestojí**: §4.10.5 odmerala, že
   odstránenie tých riadkov nemení žiadneho víťaza. Opraviť to treba kvôli číslam,
   nie kvôli záveru.
1. **Šumový prah** z opakovaných behov (§4.6, §4.10.1). Bez neho nie je ani jeden
   z nájdených 3–5 bodových rozdielov obhájiteľný ako skutočný.
2. **Detekcia jazyka na výstupe** pri každej odpovedi (§4.4). Najlacnejšia
   zostávajúca položka, zatvára najväčšie slepé miesto pre slovenský produkt.
3. **Kontrola presnej zhody čísel, dátumov a negácií** (§4.3). Mení najslabšie
   miesto celej sady na tvrdý signál.
4. **Pridať latenciu + VRAM** do výsledkovej tabuľky (§4.7, §4.10.3). gemma4
   stála 4,5× čas generovania gemma3 za pár bodov `faithfulness` — reálny
   produkčný kompromis, ktorý súčasná tabuľka úplne skrýva.
5. **Reportovať retrieval metriky raz**, nie per model (§4.1). Odstráni zavádzajúci
   stĺpec — pri dvoch z troch modelov potvrdene bit-presne rovnaký.
6. ~~**Krížové hodnotenie na podmnožine 40 otázok** (§4.5).~~ **Hotové — plná
   matica 3×3, 2026-08-02** ([EVALUATION.md §3.11](EVALUATION.md)).
   `factual_correctness` radí gemma3 > gemma4 > qwen3.6 pod všetkými tromi
   judge-mi; self-preference sa nedá detegovať ani u jedného modelu, ktorý
   hodnotil sám seba; jediné nerobustné poradie je výhra gemma4 na
   `faithfulness`, ktorú tretí judge prevracia. Ďalej to už nemá zmysel tlačiť —
   zvyšná neistota je v datasete (body 0 a 7), nie v judge-ovi.
7. **Rozšíriť testovaciu sadu**: parafrázy, otázky cez viac dokumentov,
   neodpovedateľné otázky (§4.2). Najväčšia zmena a tá, ktorá by z benchmarku
   urobila meranie uvažovania namiesto kopírovania.
8. **Oskórovať cestu `nemo/*`** (§4.7), aby sa dala vyčísliť cena guardrails.
9. **Kalibrácia človekom** na malej vzorke (§4.4), aby sa judge vôbec overil.

---

## 4.9 Čo sa skontrolovalo a ako to vyšlo

- **Vyšli `context_precision` / `context_recall` naozaj rovnako?** Áno.
  `context_recall` bola medzi gemma3 a gemma4 **bit-presne rovnaká** (0,9960 =
  0,9960); qwen3.6 sa líšila až na štvrtom desatinnom mieste (0,9932). §4.1
  potvrdená.
- **Sú rozdiely menšie než niekoľko bodov?** Áno, na tých štyroch metrikách, ktoré
  niečo znamenajú: najviac 5-bodový odstup (`factual_correctness`, gemma3 vs
  qwen3.6). Zhodné s čítaním „úloha nájdi a skopíruj" z §4.2 — a prečo ani ten
  odstup nie je plne dôveryhodný, je v §4.10.1.
- **Nesúhlasí `answer_similarity` s `factual_correctness`?** Často a výrazne — na
  jednotlivých riadkoch až o 0,95 bodu. Pozri §4.10.2: rozpracovaný príklad nie je
  zvláštnosť metriky, ale **chyba datasetu**.
- **Unikol thinking modelom reasoning do odpovede?** Nie. Riadok
  `NOTE: stripped inline reasoning` z `run_rag.py` sa nevypísal ani raz zo 546
  generovaní (182 × 3 modely). Čo namiesto toho znamená ich čas generovania
  navyše, je v §4.10.3.
- **Vyhráva gemma3 o vlások?** Áno, na dvoch zo štyroch skutočných metrík, o 3–5
  bodov — dosť málo na to, aby obava o sebahodnotenie z §4.5 bola živá, nie
  poznámka pod čiarou. Odvtedy krížovo overené (§4.5, 2026-08-01): výhra je
  skutočná a pod neutrálnym judge-om margin rastie. Skutočná nebola gemma4
  na druhom mieste.

Kompletné čísla: [EVALUATION.md §3.7](EVALUATION.md).

---

## 4.10 Potvrdené voči reálnemu benchmarku

### 4.10.1 Šumový prah neexistuje a rozdiely sú presne tam, kde by na tom záležalo

Obava z §4.6 zostáva nevyriešená: pri jednom behu na model neexistuje odmeraná
distribúcia, voči ktorej by sa 3–5 bodový rozdiel dal porovnať. Nájdené rozdiely
(`factual_correctness`: gemma3 0,889 vs qwen3.6 0,801; `answer_similarity`: 0,963
vs 0,891) sú presne tej veľkosti, kde záleží, či sú signál alebo šum judge-a — a
tento beh tie dve veci rozlíšiť nedokáže. Poradie v §EVALUATION.md 3.7 ber ako
naznačujúce, nie rozhodujúce, kým nebudú opakované behy.

### 4.10.2 Chyba datasetu, nie zvláštnosť metriky: duplicitné otázky s nezhodnými referenciami

Najkonkrétnejší nález celého behu. Zo 182 otázok je **23 (46 riadkov, 25 %
datasetu) doslovných duplikátov** — tá istá otázka sa objavuje dvakrát, raz
zameraná na *Peňaženku zdravia MINI* a raz na *MAXI*, pričom každá má referenčnú
odpoveď, ktorá uvádza pravidlo len pre svoj vlastný produkt:

```
idx 39  (MINI):  reference = "…z Peňaženky zdravia MINI je možné zaslať iba na účty registrované na Slovensku."
idx 123 (MAXI):  reference = "…z Peňaženky zdravia MAXI je možné zaslať iba na účty registrované na Slovensku."
```

gemma3 aj qwen3.6 odpovedali na **oba** výskyty identicky a úplne: *„Finančné
príspevky z Peňaženky zdravia MINI a MAXI je možné zaslať iba na účty registrované
na Slovensku."* Nie je to halucinácia — načítaný kontext doslova obsahuje
MAXI-špecifickú FAQ položku potvrdzujúcu to isté pravidlo, takže odpoveď je plne
podložená. `faithfulness` jej dala **1,0 vo všetkých štyroch kombináciách**
(2 modely × 2 indexy) a podloženie tak správne rozpoznala.

`factual_correctness` dala *tomu istému textu odpovede* **1,0 na idx 39 a 0,0 na
idx 123**, a to u oboch modelov. Jej porovnávanie tvrdení je dvojsmerné voči
*referencii*, nie voči korpusu: na idx 123 sa tvrdenie o „MINI" nedá overiť voči
referencii, ktorá MINI nikdy nespomína, takže sa berie ako nepodložené — a správna,
podložená odpoveď dostane nulu.

Nie je to ojedinelý prípad. V priemere cez všetky tri modely je
`factual_correctness` na tých 46 duplicitných riadkoch merateľne nižšia než na
136 unikátnych:

| Model   | riadky s duplicitnou otázkou | riadky s unikátnou otázkou | rozdiel |
|---------|-----------------------------:|---------------------------:|--------:|
| gemma3  | 0.831                        | 0.908                      | −0.077  |
| gemma4  | 0.818                        | 0.853                      | −0.035  |
| qwen3.6 | 0.781                        | 0.807                      | −0.026  |

Každý model stráca na tých chybných 25 % datasetu viac, než sú skutočné rozdiely
medzi modelmi v §EVALUATION.md 3.7 (3–5 bodov). **Najväčšou pákou na tieto čísla
nie je model, judge ani metrika — je to oprava (alebo odstránenie) tých 23
duplicitných otázok s úzkou referenciou**, a to je niečo, čo sa žiadnym ladením
promptu ani modelu obísť nedá.

**Náprava:** buď zliať každý pár MINI/MAXI do jednej referencie, ktorá pravidlo
uvádza všeobecne (je to napokon to isté pravidlo), alebo z každého duplikátu
zahodiť tú užšiu polovicu. Než sa z `factual_correctness` vyvodí akýkoľvek záver,
treba to opraviť a beh zopakovať.

### 4.10.3 Čas navyše u thinking modelov je latencia, nie kontaminácia

gemma4 potrebovala na vygenerovanie 182 odpovedí 76 min proti 17 min u gemma3
(4,5×) a 41 min u qwen3.6, pričom produkovala odpovede podobnej veľkosti (medián
268 vs 248 znakov) — teda nie proporčne dlhší výstup. Spolu s nulovým počtom
nájdených tagov `<think>` v ktorejkoľvek odpovedi to zodpovedá tomu, že Ollama
reasoning tokeny vykonáva (a účtuje), ale tie sa nikdy nedostanú do poľa
`content` — nie tomu, že by viditeľný reasoning kontaminoval hodnotený text. Dobrá
správa pre férovosť porovnania; zlá pre každého, kto plánuje latenciu — stĺpec
latencia/VRAM navrhovaný v §4.7 by to zachytil okamžite a stále tam nie je.

### 4.10.4 Dĺžka odpovede kopíruje odstup od referencie

Medián dĺžky odpovede rastie monotónne s metrikami, ktoré merajú blízkosť
k referencii: gemma3 (248 znakov) skóruje najvyššie na `answer_similarity` /
`factual_correctness`; qwen3.6 (355 znakov) skóruje najvyššie na
`answer_relevancy` a najnižšie na metrikách porovnávajúcich s referenciou. Zhodné
s §4.2 a §4.3: dlhšie, rozvinutejšie (a pravdepodobne skutočne užitočnejšie)
odpovede sa od úsečnej FAQ-referencie lexikálne odchyľujú aj vtedy, keď sú rovnako
dobre podložené. Je to ten istý mechanizmus ako v §4.10.2, len pôsobiaci plynule
namiesto binárnej chyby datasetu — ďalší dôvod, prečo sa `answer_similarity`
a `factual_correctness` nemajú čítať ako posledné slovo o kvalite bez metrík
plynulosti a relevantnosti vedľa nich.


### 4.10.5 Dala by iná sada otázok iného víťaza? Odmerané

§4.10.1 namietala, že pri jednom behu na model neexistuje rozdelenie, voči
ktorému by sa dal 3–5 bodový rozdiel posúdiť. Existuje, a nepotrebuje opakovaný
beh: per-riadkové skóre už samo je vzorka, takže jej prevzorkovanie odpovie na
to, koľko z poradia je *sada otázok* a nie modely.

Dva testy, oba na plnom behu súdenom gemma3.

**Odstránenie duplikátov nemení žiadneho víťaza.** Po odobratí všetkých 46
duplicitných riadkov (§4.10.2) a preradení na zvyšných 136 unikátnych:

| Metrika             | všetky riadky          | bez duplikátov      |
|---------------------|------------------------|---------------------|
| factual_correctness | gemma3 (náskok +0.046) | gemma3 (**+0.058**) |
| answer_similarity   | gemma3                 | gemma3              |
| faithfulness        | gemma4                 | gemma4              |
| answer_relevancy    | qwen3.6                | qwen3.6             |

Náskok gemma3 *rastie*, čo sedí so zistením §4.10.2, že práve tie riadky ju
penalizovali najviac. Defekt datasetu teda deformuje absolútne čísla bez toho,
aby sa dotkol poradia.

**Bootstrap cez otázky.** 10 000 prevzorkovaní s vrátením zo 136 unikátnych
otázok, so záznamom, ktorý model zakaždým vyhral:

| Metrika             | gemma3      | gemma4     | qwen3.6    |
|---------------------|------------:|-----------:|-----------:|
| factual_correctness | **100,0 %** | 0,0 %      | 0,0 %      |
| answer_similarity   | **100,0 %** | 0,0 %      | 0,0 %      |
| faithfulness        | 20,9 %      | **78,3 %** | 0,9 %      |
| answer_relevancy    | 0,0 %       | 17,6 %     | **82,4 %** |

**Dve výhry gemma3 neprehrali ani raz v desaťtisíc prevzorkovaniach.** Nie sú
teda šťastným ťahom otázok.

Nestabilné sú výhry tých druhých. `faithfulness` pripadne gemma3 zhruba
v jednom prevzorkovaní z piatich — a je to tá istá metrika, ktorej víťaza podľa
§3.11 prevracia zmena judge-a. Dve nezávislé perturbácie, vzorka otázok a judge,
ukazujú na ten istý výsledok. „gemma4 je najvernejšia" treba považovať za
nepodložené ani jednou z tých ciest.

**Na čo to neodpovedá.** Bootstrap prevzorkováva *túto* zásobu, takže hovorí
o „inej vzorke podobných otázok", nie o „inom druhu otázok". §4.2 odmerala, že
99 % otázok aj ich referenčných odpovedí sa doslovne nachádza v ingestovanom
PDF — je to úloha „nájdi a skopíruj". Sada postavená na parafrázach, otázkach cez
viac dokumentov a neodpovedateľných otázkach by mohla preusporiadať všetko a
žiadne prevzorkovanie súčasnej sady to nevidí. gemma3 vyhráva v produkovaní textu
najbližšieho stručnej FAQ referencii; to bolo odmerané, a nie je to to isté
tvrdenie ako „gemma3 je najlepší model".

**Dôsledok pre backlog.** Bod 0 (oprava duplikátov) ostáva prvý kvôli absolútnym
číslam, ktoré preukázateľne deformuje — ale teraz vieme, že pre poradie **nie je**
nosný. Skutočná expozícia poradia je bod 7, rozšírenie testovacej sady.
