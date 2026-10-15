# Proact Service Desk Assistant — lokale RAG-PoC (v3)

Een helpdesk-chatbot die vragen beantwoordt uit interne kennisbank-documenten én
eenvoudige Service Desk-acties kan uitvoeren. Alles draait **100% lokaal** via
LM Studio — er gaat geen bedrijfsinformatie naar een externe clouddienst.

## Wat kan hij

- **Vragen beantwoorden uit de kennisbank** (RAG) met bronvermelding; het antwoord
  **streamt live binnen** (voelt sneller).
- **Gespreksgeheugen** — de bot onthoudt eerdere berichten, zodat vervolgvragen
  (&ldquo;en als dat niet lukt?&rdquo;) de juiste context hebben.
- **Intent-router** — begroetingen, acties en onbekende vragen worden direct
  afgehandeld, **zonder** het trage taalmodel. Alleen een echte kennisvraag gaat
  naar het LLM.
- **Acties:**
  - *Wachtwoordreset starten* — stuurt een **reset-link** naar het geregistreerde
    e-mailadres (gemaskeerd getoond). **Nooit** een wachtwoord in de chat of per
    e-mail — dat is een bewuste beveiligingskeuze.
  - *Ticket aanmaken* — schrijft een ticket naar `data/tickets.json`.
- **Onbekende vraag** → de bot biedt meteen aan er een ticket voor aan te maken.
- **Nette foutafhandeling** — duidelijke melding i.p.v. een crash als de server uit staat.
- **Strakke, Claude-achtige interface** met &ldquo;denk&rdquo;-indicator en klikbare links.
- **Klantgericht** — vriendelijke antwoorden voor eindgebruikers, zonder interne jargon.
- **Officiële Microsoft-links** worden automatisch bij het antwoord meegestuurd.
- **Eigen kennisbank** — `.docx`, `.md` en `.txt` worden ingelezen; zet je eigen
  Word-documenten in `documents/` en draai `ingest.py`.

## Hoe het werkt

```
Documenten ─▶ chunken ─▶ embeddings (nomic-embed) ─▶ vector-index (index.json)

Bericht ─▶ intent-router ─┬─ begroeting / actie / onbekend ─▶ direct antwoord (geen LLM)
                          └─ kennisvraag ─▶ retrieval (+ geheugen) ─▶ context+prompt ─▶ LLM (qwen3, streaming) ─▶ antwoord + bron
```

## Projectstructuur

| Bestand | Doel |
|---|---|
| `src/config.py` | Instellingen: modellen, RAG-parameters, SMTP (via omgevingsvariabelen), systeemprompt |
| `src/lmclient.py` | LM Studio-wrapper: LLM (incl. streaming), embeddings, cosine |
| `src/router.py` | Intent-herkenning (begroeting / reset / ticket / vraag) |
| `src/actions.py` | Acties: ticket aanmaken, wachtwoordreset starten (reset-mail via SMTP) |
| `src/links.py` | Officiële Microsoft-hulplinks per onderwerp |
| `src/ingest.py` | Documenten (.md/.txt/.docx) → chunks → embeddings → `index.json` |
| `src/rag.py` | Dispatcher + RAG + gespreksgeheugen |
| `src/app.py` | Web-UI (Flask) met streaming, acties en geheugen |
| `src/cli.py` | Chat in de terminal |
| `documents/` | De kennisbank (voorbeeldartikelen; vervangbaar) |
| `data/` | Wordt bij gebruik aangemaakt: tickets + actielog (`.gitignore`) |

## Installatie & gebruik (kort)

1. **LM Studio** op de VM, beide modellen geladen en de server gestart (poort 1234):
   `qwen/qwen3-4b-2507` + `nomic-embed-text-v1.5`.
2. **Python:**
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   python src/ingest.py        # eenmalig
   python src/app.py           # http://127.0.0.1:5000
   ```

Probeer: *Hoe reset ik mijn wachtwoord?* · *Reset mijn wachtwoord* · *Maak een ticket voor een kapotte printer*.

## Echt e-mail versturen (optioneel)

Standaard wordt de reset-mail **gesimuleerd**. Wil je 'm echt laten versturen, zet
dan SMTP-gegevens als **omgevingsvariabelen** (nooit in de code!) vóór je `app.py` start:

```bash
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=jouwadres@gmail.com
export SMTP_PASS=<app-wachtwoord>        # Gmail: App Password (vereist 2FA)
export RESET_BASE_URL=https://reset.proact.local/reset
python src/app.py
```

Voor testen zonder echte bezorging is een service als Mailtrap of een lokale
debug-SMTP handig. De e-mail bevat altijd een **reset-link**, geen wachtwoord.

## Vertrouwelijkheid

- Alle verwerking (embeddings + LLM) gebeurt lokaal; geen externe API's.
- Documenten zijn generiek/fictief. Echte bedrijfsdocumenten alleen in een **private**
  repo of lokaal (`documents/` in `.gitignore`). De acties zijn **gesimuleerd**;
  alleen de reset-mail wordt echt verstuurd als je SMTP instelt.

## Mogelijke uitbreidingen

- PDF/DOCX inlezen; vector-database (Chroma/FAISS); echte Graph-integratie achter de
  reset (met autorisatie); logging van onbeantwoorde vragen om KB-hiaten te vinden.
