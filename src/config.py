"""
Centrale configuratie voor de Proact Service Desk Assistant (lokale RAG-PoC).

Alles staat hier bij elkaar zodat je tijdens de demo in één bestand kunt laten
zien welke modellen en parameters je gebruikt. Pas de modelnamen hieronder aan
op wat je in LM Studio hebt gedownload (tabblad 'My Models' / `lms ls`).
"""

from pathlib import Path

# --- Mappen -----------------------------------------------------------------
# BASE_DIR = de projectmap (één niveau boven /src)
BASE_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = BASE_DIR / "documents"          # hier staan je KB-documenten (.md/.txt)
INDEX_PATH = BASE_DIR / "index.json"       # hier wordt de vector-index opgeslagen

# --- Modellen (moeten in LM Studio geladen/gedownload zijn) -----------------
# LLM dat de antwoorden genereert. Kies op basis van je VM-resources:
#   - weinig RAM/geen GPU : "qwen/qwen3-1.7b" of "llama-3.2-3b-instruct"
#   - comfortabel         : "qwen/qwen3-4b-2507"
LLM_MODEL = "qwen/qwen3-4b-2507"

# Embedding-model dat tekst omzet naar vectoren. Klein en snel, draait op CPU.
EMBEDDING_MODEL = "nomic-embed-text-v1.5"

# --- RAG-parameters ---------------------------------------------------------
CHUNK_SIZE = 800        # max. aantal tekens per chunk
CHUNK_OVERLAP = 120     # overlap tussen chunks (behoudt context op de grens)
TOP_K = 4               # aantal chunks dat als context wordt meegegeven
MIN_SCORE = 0.25        # minimale similarity; eronder = "niet in de KB gevonden"

# --- Systeemprompt ----------------------------------------------------------
# Dwingt het model om ALLEEN uit de meegegeven context te antwoorden en eerlijk
# te zijn als het antwoord er niet in staat. Dit voorkomt verzonnen antwoorden.
SYSTEM_PROMPT = """Je bent de Proact Service Desk Assistant.
Beantwoord de vraag UITSLUITEND op basis van de onderstaande context uit de
kennisbank. Regels:
- Staat het antwoord niet in de context? Zeg dan letterlijk: "Dat staat niet in
  de kennisbank; maak hiervoor een ticket aan voor de Service Desk."
- Verzin niets en gok niet.
- Antwoord kort, concreet en in het Nederlands, bij voorkeur in stappen.
- Noem aan het eind de bron(nen) die je hebt gebruikt."""
