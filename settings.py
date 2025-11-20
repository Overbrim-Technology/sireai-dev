import os
from dotenv import load_dotenv

import assemblyai as aai
import asyncpg


# === CONFIGURATION ===
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
pool: asyncpg.pool.Pool = None

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TELEGRAM_BOT_TOKEN}"
PORT = int(os.getenv("PORT", 8080))

# Read admin IDs from .env and split into a list of integers
DEV_USER_IDS = [int(x) for x in os.getenv("DEV_USER_IDS", "").split(",") if x]
ADMIN_USER_IDS = [int(x.strip()) for x in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if x.strip()]
EXEC_IDS = [int(x) for x in os.getenv("EXEC_IDS", "").split(",") if x]
# Allowed audio file extensions
SUPPORTED_FORMATS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm"}

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY")
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")


# Connection Factory
async def init_db_pool():
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return pool