# Proact Service Desk Assistant (lokale RAG-PoC)

Dit is mijn Proof-of-Concept voor een helpdesk-chatbot voor Proact. De chatbot beantwoordt
vragen uit een kennisbank en voert een aantal Service Desk-handelingen zelf uit: een
wachtwoord resetten, een ticket aanmaken en software aanvragen, controleren of verwijderen.
Het taalmodel draait via LM Studio, dus er gaat geen data naar een externe clouddienst.

## Wat ik heb gebouwd

- Een kennisbank-chatbot (RAG) die antwoorden streamt en vervolgvragen begrijpt dankzij gespreksgeheugen.
- Een router die begroetingen, acties en onbekende vragen direct afhandelt, zonder het taalmodel.
- Inloggen met een Active Directory-account.
- Een wachtwoordreset tegen on-prem Active Directory (LDAPS).
- Een ticket-intake die het onderwerp uit het gesprek samenvat.
- Zelfservice voor Adobe Reader (aanvragen, controleren, verwijderen) via een AD-groep en een GPO.
- Een Active Directory-testomgeving (domein `lab.proact.local`, domaincontroller DC01) die ik met
  scripts in `scripts/` heb opgezet: domaincontroller, OU met 10 testgebruikers, serviceaccount met
  beperkte rechten en LDAPS.
- Een eigen kennisbank van 8 artikelen in `documents/`.

## Hoe het werkt

```
documents/ -> chunks -> embeddings -> index.json

bericht -> router -+- begroeting, actie of onbekend -> direct antwoord
                   +- kennisvraag -> retrieval -> LLM (streaming) -> antwoord
```

**Kennisvragen.** `ingest.py` leest `.md`, `.txt` en `.docx`, knipt de tekst in chunks van 800
tekens (120 overlap) en slaat per chunk een embedding op in `index.json`. Bij een vraag zoek ik
de 3 beste chunks op cosinus-gelijkenis. Is de beste score lager dan 0,35, dan zegt de bot dat
het antwoord niet in de kennisbank staat en biedt hij een ticket aan. Anders gaan de chunks, de
laatste berichten en de vraag naar het model (`qwen/qwen3-8b`), dat het antwoord streamt. Het
denkblok van het model wordt weggefilterd. Bij het antwoord toon ik een officiële
Microsoft-link (`links.py`), geen interne bestandsnamen.

**Router.** `router.py` herkent op trefwoorden een begroeting, een wachtwoordreset en een ticket.
Bij software-onderwerpen leest het taalmodel wat de gebruiker bedoelt (aanvragen, controleren,
verwijderen of iets anders, en voor jezelf of iemand anders). Werkt dat niet, dan gebruikt de
router trefwoorden.

**Inloggen.** De gebruiker logt in met een AD-account. De bot doet een LDAP-bind met dat
account en haalt naam, bedrijf en e-mailadres op met het serviceaccount. De server houdt de
sessie bij in een HttpOnly-cookie (verloopt na 8 uur zonder activiteit). Na 5 mislukte
pogingen in 5 minuten blokkeert de login, per IP-adres en per gebruikersnaam.

**Wachtwoordreset.** Alleen ingelogd. Een gebruiker kan alleen het eigen account resetten, een
account in `AD_AGENTS` ook die van anderen. De bot zoekt de gebruiker in AD, ontgrendelt het
account en zet een tijdelijk wachtwoord met `pwdLastSet=0`, zodat het bij de volgende
aanmelding gewijzigd moet worden. Dat wachtwoord gaat per e-mail naar het adres dat in AD staat
en komt nooit in de chat.

**Ticket.** Het taalmodel vat het probleem uit het gesprek samen tot een onderwerp en een
omschrijving, en de gebruiker bevestigt dat. Naam en bedrijf komen uit de login, het
telefoonnummer vraagt de bot. Het ticket komt in `data/tickets.json`, elke actie in
`data/action_log.jsonl`. Is SMTP ingesteld, dan komt er een bevestigingsmail.

**Software.** `config.py` koppelt een applicatie aan een AD-groep (Adobe Reader aan
`App-AdobeReader`). De bot zet het eigen account in of uit die groep, of controleert alleen
of het lid is. Een GPO met security-filtering op die groep installeert Reader bij de
volgende aanmelding. Bij het verwijderen draait op de client een geplande taak
(`Uninstall-AdobeReader.ps1`, als SYSTEM, bij aanmelden) die Reader de-installeert als de
gebruiker niet meer in de groep zit. Voor iemand anders biedt de bot een ticket aan.
De uitleg staat in `scripts/README-APP-DEPLOY.md`.

## Projectstructuur

| Bestand | Doel |
|---|---|
| `src/app.py` | Flask-webinterface met streaming, login en sessies |
| `src/rag.py` | Dispatcher, RAG en gespreksgeheugen |
| `src/flow_ticket.py` | Ticket-intake: onderwerp vaststellen, bevestigen en aanmaken |
| `src/flow_software.py` | Software aanvragen, controleren en verwijderen via een AD-groep |
| `src/flow_account.py` | Wachtwoordreset: aanbod, bevestiging en uitvoering |
| `src/flow_common.py` | Gedeelde hulpjes: antwoordvarianten, voornaam, ja/nee lezen |
| `src/router.py` | Intent-herkenning op trefwoorden |
| `src/lmclient.py` | LM Studio: LLM, embeddings, intent- en ticketsamenvatting |
| `src/actions.py` | Ticket, wachtwoordreset en software aanvragen, controleren en verwijderen |
| `src/ad.py` | Active Directory via LDAPS: zoeken, inloggen, ontgrendelen, resetten, groepen |
| `src/ingest.py` | Documenten naar chunks, embeddings en `index.json` |
| `src/links.py` | Officiële Microsoft-hulplinks per document |
| `src/config.py` | Instellingen, app-catalogus en systeemprompt |
| `src/responder.py` | Laat het model uitkomsten van acties in eigen woorden zeggen; controleert of de feiten kloppen, anders de vaste tekst |
| `src/cli.py` | Chat in de terminal |
| `tests/eval_set.py` | Kleine testset: routering, ja/nee lezen, ticketflow, controle op de verwoording |
| `test_ad.py` | Test de koppeling met AD |
| `scripts/` | `01-Install-AD-DC.ps1` (domaincontroller), `02-Setup-Lab.ps1` (OU, gebruikers, serviceaccount, LDAPS), `03-Setup-AppDeploy.ps1` (groep, share, GPO), `Uninstall-AdobeReader.ps1`, `README-APP-DEPLOY.md` |
| `documents/` | De kennisbank |
| `data/` | Tickets en actielog, ontstaat bij gebruik (staat in `.gitignore`) |

## Installeren en starten

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python src/ingest.py        # kennisbank indexeren, opnieuw na elke wijziging in documents/
python src/app.py           # http://127.0.0.1:5000
```

LM Studio moet draaien met een antwoordmodel en een embedding-model. De app laadt de index
bij het starten, dus start de app opnieuw na een nieuwe `ingest`.

## Instellingen

Instellingen staan als omgevingsvariabelen in `ad.env`, dat buiten Git blijft (`.gitignore`).

```bash
# Active Directory (LDAPS), de waarden staan in de uitvoer van scripts/02-Setup-Lab.ps1
export AD_SERVER=192.168.2.10
export AD_BASE_DN='DC=lab,DC=proact,DC=local'
export AD_BIND_DN='CN=svc-chatbot,OU=ProactLab,DC=lab,DC=proact,DC=local'
export AD_BIND_PASSWORD=<serviceaccount-wachtwoord>
export AD_AGENTS=terry.sarpong        # mag ook andere accounts resetten

# E-mail
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=<mijn-adres>
export SMTP_PASS=<gmail-app-wachtwoord>
export RESET_NOTIFY_OVERRIDE=<vangnet-inbox>   # lab: alle meldingen naar dit adres

# Model en LM Studio
export LLM_MODEL=qwen/qwen3-8b
export EMBEDDING_MODEL=<naam van het embedding-model in LM Studio>
export LMSTUDIO_HOST=192.168.2.27:1234        # LM Studio op een andere machine
export LLM_PHRASING=true                      # model verwoordt uitkomsten van acties (false = vaste teksten)
export LLM_READ_REPLIES=true                  # model leest vrije ja/nee-antwoorden
export MIN_SCORE=0.66                          # onder deze score: niet in de kennisbank
export SURE_SCORE=0.75                        # boven deze score: direct antwoorden; ertussen beoordeelt het model
export LLM_RELEVANCE=true                     # model beoordeelt vragen in het twijfelgebied
export LLM_QUICK_TIMEOUT=15                   # seconden; daarna valt de bot terug op trefwoorden
export PORT=5000                              # poort van de webserver (waitress)
```

Zonder AD- en SMTP-variabelen draaien de acties in simulatie.
