import os
from dotenv import load_dotenv

load_dotenv()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ======================
# MODEL SETTINGS
# ======================

MODEL_PROVIDER = "gemini"  # "gemini" albo "local"

GEMINI_MODEL = "gemini-2.5-flash-native-audio-latest"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# jeśli kiedyś przejdziesz na lokalny model (np. ollama)
LOCAL_MODEL_NAME = "llama3"

# ======================
# MEMORY SETTINGS
# ======================

# ile ostatnich wiadomości trzymamy (RAM)
SHORT_TERM_MEMORY_LIMIT = 15

# pliki pamięci
STORAGE_DIR = os.path.join(BASE_DIR, "storage")

CONVERSATIONS_FILE = os.path.join(STORAGE_DIR, "conversations.json")
ENTITY_MEMORY_FILE = os.path.join(STORAGE_DIR, "jarvis_memory.json")
EPISODIC_MEMORY_FILE = os.path.join(STORAGE_DIR, "summaries.json")

# ======================
# AUDIO SETTINGS
# ======================

INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000

# próg wykrycia mowy (barge-in)
VOLUME_THRESHOLD = 0.012

# ======================
# SERVER SETTINGS
# ======================

HOST = "0.0.0.0"
PORT = 8000

# ======================
# DATABASE SETTINGS (Nowe!)
# ======================
DB_NAME = os.getenv("DB_NAME", "jarvis_db")
DB_USER = os.getenv("DB_USER", "jarvis_db_user")
DB_PASS = os.getenv("DB_USER_PASS", "Start$123")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")

# URL dla SQLAlchemy (PostgreSQL)
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"