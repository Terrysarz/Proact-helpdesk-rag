# Proact Service Desk Assistant (lokale RAG-PoC)

Dit is mijn Proof-of-Concept voor een lokale helpdesk-chatbot voor Proact. Ik heb een
assistent gebouwd die vragen beantwoordt uit interne kennisbank-documenten en een
aantal Service Desk-handelingen zelf uitvoert. Alles draait 100% lokaal via LM Studio,
dus er gaat geen bedrijfsinformatie naar een externe clouddienst.

Ik heb dit gemaakt als automatisering van handmatig servicedeskwerk: wachtwoorden
resetten (waarbij het account ook wordt ontgrendeld), tickets aanmaken en software
uitrollen, allemaal via een chatgesprek dat gekoppeld is aan Active Directory.

## Wat ik heb gebouwd

- **Vragen beantwoorden uit de kennisbank (RAG)** met bronvermelding. Het antwoord
  streamt live binnen, waardoor het sneller aanvoelt.
- **Gespreksgeheugen**, zodat de bot eerdere berichten meeneemt en vervolgvragen de
  juiste context hebben.
- **Intent-router** die begroetingen, acties en onbekende vragen direct afhandelt
  zonder het trage taalmodel. Alleen een echte kennisvraag gaat naar het LLM.
- **Wachtwoordreset tegen on-prem Active Directory** (LDAPS): de bot zoekt de
  gebruiker op, ontgrendelt het account, zet een tijdelijk wachtwoord met geforceerde
  wijziging bij de volgende aanmelding, en mailt dat naar het geregistreerde adres.
  Het wachtwoord komt nooit in de chat te staan. Dat is een bewuste beveiligingskeuze.
- **Inloggen met een AD-account** in de chatbot, met autorisatie: een gebruiker kan
  alleen het eigen account resetten, een servicedesk-medewerker ook dat van anderen.
- **Ticket-intake** waarbij het taalmodel het onderwerp en de omschrijving uit het
  gesprek samenvat en ter bevestiging voorlegt, zodat de klant zich niet hoeft te
  herhalen. Bij een ingelogde gebruiker worden naam en bedrijf automatisch overgenomen,
  en een bevestiging wordt gemaild.
- **Zelfservice software**: een gebruiker kan via de chat een applicatie (Adobe Reader)
  aanvragen, controleren of die al klaarstaat, of weer laten verwijderen. De bot leest
  met het taalmodel wat er echt bedoeld wordt (aanvragen, controleren of verwijderen, en
  of het voor jezelf of iemand anders is), zet het account in of uit de bijbehorende
  AD-groep, en een GPO installeert of verwijdert de software bij de volgende aanmelding.
  Beschreven in `scripts/README-APP-DEPLOY.md`.
- **Nette foutafhandeling** met een duidelijke melding in plaats van een crash als de
  modelserver uit staat.
- **Klantgerichte interface** met een denk-indicator en klikbare links, zonder interne
  jargon in de antwoorden. De interne bronbestandsnamen toon ik niet aan de klant, alleen
  een nette publieke hulplink.
- **Officiële Microsoft-links** worden automatisch bij het antwoord meegestuurd.
- **Eigen kennisbank**: ik lees `.docx`, `.md` en `.txt` in; mijn eigen Word-documenten
  staan in `documents/` en worden met `ingest.py` verwerkt.

## Hoe het werkt

```
Documenten -> chunken -> embeddings (nomic-embed) -> vector-index (index.json)

Bericht -> intent-router -+- begroeting / actie / onbekend -> direct antwoord (geen LLM)
                          +- kennisvraag -> retrieval (+ geheugen) -> context+prompt -> LLM (qwen3-8b, streaming) -> antwoord + bron
```

De acties lopen in volgorde van wat is geconfigureerd: eerst Microsoft Graph (Entra ID),
dan on-prem Active Directory (LDAPS), dan SMTP, en anders een simulatie. In mijn lab
gebruik ik de Active Directory-route.

## Projectstructuur

| Bestand | Doel |
|---|---|
| `src/config.py` | Instellingen: modellen, RAG-parameters, SMTP, Graph, AD, app-catalogus, systeemprompt |
| `src/lmclient.py` | LM Studio-wrapper: LLM (incl. streaming), embeddings, cosine |
| `src/router.py` | Intent-herkenning (begroeting / reset / ticket / software / vraag) |
| `src/actions.py` | Ticket aanmaken, wachtwoordreset starten, software aanvragen |
| `src/ad.py` | On-prem Active Directory via LDAPS: zoeken, authenticeren, ontgrendelen, resetten, groep-lidmaatschap |
| `src/graph.py` | Optionele Microsoft Graph / Entra ID-integratie |
| `src/links.py` | Officiele Microsoft-hulplinks per onderwerp |
| `src/ingest.py` | Documenten (.md/.txt/.docx) naar chunks naar embeddings naar `index.json` |
| `src/rag.py` | Dispatcher, RAG en gespreksgeheugen |
| `src/app.py` | Web-UI (Flask) met streaming, acties, geheugen en login |
| `src/cli.py` | Chat in de terminal |
| `scripts/` | PowerShell voor de Windows Server-lab en de documentatie van de handmatige stappen |
| `documents/` | De kennisbank (klantgerichte artikelen) |
| `data/` | Wordt bij gebruik aangemaakt: tickets en actielog (staat in `.gitignore`) |

## Stappen die ik heb doorlopen om het draaiend te krijgen

1. **LM Studio** geinstalleerd en de server gestart op poort 1234, met de modellen
   `qwen/qwen3-8b` en `nomic-embed-text-v1.5`. Het model is instelbaar via de
   omgevingsvariabele `LLM_MODEL`. Om het rekenwerk sneller te maken draai ik het model
   op een aparte machine (Apple Silicon) en wijs ik de chatbot daarheen met `LMSTUDIO_HOST`.
2. **Python-omgeving** opgezet en de index opgebouwd:
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   python src/ingest.py        # eenmalig de kennisbank indexeren
   python src/app.py           # http://127.0.0.1:5000
   ```
3. **Active Directory-lab** opgezet met de scripts in `scripts/` (domaincontroller,
   OU, gebruikers, serviceaccount) en de chatbot via LDAPS gekoppeld.
4. **Instellingen** als omgevingsvariabelen gezet (nooit in de code), zie hieronder.
5. **Zelfservice software** ingericht (installeren en verwijderen via een AD-groep en
   GPO), beschreven in `scripts/README-APP-DEPLOY.md`.

Dingen die ik heb getest: *Hoe reset ik mijn wachtwoord?*, *Reset mijn wachtwoord*,
*Maak een ticket voor een kapotte printer*, *Ik wil Adobe Reader*, *Heb ik al toegang
tot Adobe?* en *Verwijder Adobe weer*.

## Instellingen (omgevingsvariabelen)

Ik zet gevoelige gegevens als omgevingsvariabelen, nooit in de broncode. Deze staan
bij mij in een `ad.env`-bestand dat buiten Git blijft (`.gitignore`). De AD- en
e-mailvariabelen zijn optioneel voor de applicatie (zonder deze draait alles in
simulatie), maar in mijn PoC heb ik ze wel ingesteld zodat de resets en mails echt
werken. Voorbeeld:

```bash
# On-prem Active Directory (LDAPS)
export AD_SERVER=192.168.2.10
export AD_BASE_DN='DC=lab,DC=proact,DC=local'
export AD_BIND_DN='CN=svc-chatbot,OU=ProactLab,DC=lab,DC=proact,DC=local'
export AD_BIND_PASSWORD=<serviceaccount-wachtwoord>
export AD_AGENTS=terry.sarpong        # mag ook andere accounts resetten

# E-mail (reset-melding naar het geregistreerde adres)
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=<mijn-adres>
export SMTP_PASS=<gmail-app-wachtwoord>
export RESET_NOTIFY_OVERRIDE=<vangnet-inbox>

# Optioneel: ander model of een externe LM Studio-host
export LLM_MODEL=qwen/qwen3-8b
export LMSTUDIO_HOST=192.168.2.27:1234   # LM Studio op een andere machine (bv. een Mac)
```

Zonder deze variabelen wordt de reset-mail gesimuleerd in plaats van echt verstuurd, en
draait het model lokaal in plaats van op een externe host.

## Beveiligingskeuzes die ik heb gemaakt

- Het wachtwoord staat nooit in de chat. Bij een reset wordt een tijdelijk wachtwoord
  gemaild naar het geregistreerde adres, met verplichte wijziging bij de volgende
  aanmelding (`pwdLastSet=0`). In productie zou ik dit vervangen door een eenmalige
  self-destruct link.
- Autorisatie op de reset: zonder inloggen kan het niet, een gewone gebruiker kan
  alleen zichzelf resetten, een servicedesk-medewerker ook anderen.
- Het serviceaccount heeft alleen de rechten die het nodig heeft (reset, ontgrendelen,
  groep-lidmaatschap), gedelegeerd op de OU.
- Reset-meldingen gaan naar een geregistreerd adres, zodat er nooit per ongeluk mail
  naar een echt `@proact.nl`-adres gaat.

## Vertrouwelijkheid

- Alle verwerking (embeddings en LLM) gebeurt lokaal, zonder externe API's.
- De kennisbank-documenten zijn klantgericht en bevatten geen interne gegevens.
- De `data/`-map (tickets en actielog) en `ad.env` (geheimen) staan in `.gitignore`.
