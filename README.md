# Proact Service Desk Assistant — lokale RAG-PoC

Een helpdesk-chatbot die vragen beantwoordt op basis van interne
kennisbank-documenten. Alles draait **100% lokaal** via LM Studio — er gaat geen
bedrijfsinformatie naar een externe clouddienst. Dat is bewust, met het oog op
vertrouwelijkheid van bedrijfsdata.

## Hoe het werkt (RAG)

```
Documenten ─▶ chunken ─▶ embeddings (nomic-embed) ─▶ vector-index (index.json)

Vraag ─▶ embedden ─▶ top-k similarity ─▶ context in prompt ─▶ LLM (qwen3) ─▶ antwoord + bron
```

Het model mag **alleen** antwoorden uit de meegegeven context. Staat het antwoord
niet in de kennisbank, dan verwijst de bot naar een ticket in plaats van te gokken.

## Projectstructuur

| Bestand | Doel |
|---|---|
| `src/config.py` | Alle instellingen: modelnamen, chunk-grootte, top-k, systeemprompt |
| `src/lmclient.py` | Wrapper rond de LM Studio SDK (LLM + embeddings + cosine) |
| `src/ingest.py` | Documenten → chunks → embeddings → `index.json` |
| `src/rag.py` | Retrieval + prompt + antwoord met bronvermelding |
| `src/cli.py` | Chat in de terminal (simpele demo) |
| `src/app.py` | Web-UI (Flask) met chat + zichtbare bronnen |
| `documents/` | De kennisbank (voorbeeld-artikelen; vervang door die van je bedrijf) |

## Installatie op de Proxmox-VM (Rocky Linux)

1. **LM Studio installeren** op de VM. LM Studio heeft een GUI nodig — jouw
   Rocky-VM met xrdp is daarvoor prima. (Headless kan ook via `lms server start`.)

2. **Modellen downloaden** in LM Studio (of via CLI):
   ```bash
   lms get qwen/qwen3-4b-2507
   lms get nomic-ai/nomic-embed-text-v1.5
   ```
   > Weinig RAM / geen GPU-passthrough? Zet in `config.py` `LLM_MODEL` op een
   > kleiner model, bijv. `qwen/qwen3-1.7b`. Het embedding-model draait prima op CPU.

3. **LM Studio server starten** (in de app: tabblad *Developer* → *Start Server*,
   of `lms server start`). De Python-SDK verbindt hiermee op de localhost.

4. **Python-omgeving** (op dezelfde VM):
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

## Gebruik

```bash
# 1) Index bouwen (eenmalig, en opnieuw na het wijzigen van documenten)
python src/ingest.py

# 2a) Chatten in de terminal
python src/cli.py

# 2b) OF de web-UI starten
python src/app.py
# open http://127.0.0.1:5000  (of http://<VM-IP>:5000 vanaf je laptop)
```

## Vanaf GitHub draaien (optioneel)

Je kunt dit project op GitHub zetten en op de VM clonen in plaats van de zip te
kopiëren.

Eenmalig een repo maken en pushen (op je eigen machine, in de projectmap):

```bash
git init
git add .
git commit -m "Proact Service Desk Assistant - lokale RAG PoC"
git branch -M main
git remote add origin https://github.com/<jouw-gebruiker>/proact-helpdesk-rag.git
git push -u origin main
```

Op de VM clonen en draaien:

```bash
sudo apt install -y git
git clone https://github.com/<jouw-gebruiker>/proact-helpdesk-rag.git
cd proact-helpdesk-rag
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python src/ingest.py
python src/app.py
```

Wat **niet** in Git terechtkomt (staat al in `.gitignore`): de virtuele omgeving,
caches en de gegenereerde `index.json`. De modellen en LM Studio zitten sowieso
niet in de repo; die blijven op de VM.

> **Let op vertrouwelijkheid:** de meegeleverde documenten zijn generiek. Vervang
> je ze door echte bedrijfsdocumenten, zet de repo dan op **private** of houd die
> documenten lokaal (voeg `documents/` toe aan `.gitignore`). Push nooit
> vertrouwelijke data naar een publieke repo.

## Vertrouwelijkheid

- Alle verwerking (embeddings + LLM) gebeurt lokaal op de VM; geen externe API's.
- De meegeleverde documenten zijn **generiek/fictief**. Vervang ze pas door echte
  bedrijfsdocumenten als de VM en opslag voldoen aan het interne beleid, en deel
  nooit klant-specifieke of vertrouwelijke data in een omgeving die daar niet
  voor is goedgekeurd.

## Mogelijke uitbreidingen (voor de "complexiteit" en toekomst)

- PDF/DOCX-ondersteuning bij het inlezen (nu .md/.txt).
- Vervang de JSON-index door een vector-database (bijv. Chroma/FAISS) voor meer documenten.
- Conversatiegeheugen (meerdere vragen achter elkaar met context).
- Logging van vragen zonder antwoord, om hiaten in de kennisbank te vinden.
