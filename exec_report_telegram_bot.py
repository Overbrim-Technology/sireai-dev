import os
import asyncio
import sqlite3
import logging
import requests
import time
# import whisper
import assemblyai as aai
from datetime import datetime
from dotenv import load_dotenv
from functools import lru_cache
from telegram import Update, InputFile, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ConversationHandler, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import google.generativeai as genai

from exec_report_onboarding import (start, org_choice, org_name, first_name, surname, cancel,
                                    FIRST_NAME, SURNAME, ORG_CHOICE, ORG_NAME, START_KEYBOARD)
                                    
from exec_report_dev import reset_onboarding, promote_user, demote_user, get_user_roles, clear_user_roles_cache

# === CONFIGURATION ===
load_dotenv()
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
DB_PATH = "work_updates.db"
aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY")
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")


# === SETUP LOGGING ===
logging.basicConfig(level=logging.INFO)

# === SETUP GEMINI ===
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")
# Load Whisper model once (large-v3)
# audiomodel = whisper.load_model("turbo")

# === SETUP DB ===
# def init_db():
#     conn = sqlite3.connect(DB_PATH)
#     cursor = conn.cursor()
#     cursor.execute("""
#         CREATE TABLE IF NOT EXISTS organizations (
#             id INTEGER PRIMARY KEY AUTOINCREMENT,
#             name TEXT UNIQUE
#         )
#     """)
#     cursor.execute("""
#         CREATE TABLE IF NOT EXISTS users (
#             user_id INTEGER PRIMARY KEY,
#             username TEXT,
#             org TEXT,
#             FOREIGN KEY(org) REFERENCES organizations(name)
#         )
#     """)
#     cursor.execute("""
#     CREATE TABLE IF NOT EXISTS updates (
#         id INTEGER PRIMARY KEY AUTOINCREMENT,
#         user_id INTEGER,
#         username TEXT,
#         organization TEXT,
#         original_text TEXT,       -- raw input (user text or transcription)
#         structured_text TEXT,     -- AI-cleaned / structured version
#         image_path TEXT,
#         timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
#     )
#     """)
#     conn.commit()
#     conn.close()
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Organizations
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
    """)

    # Users
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,         -- Telegram user ID
            username TEXT,                       -- Telegram username
            first_name TEXT,
            surname TEXT,
            org TEXT,
            executive INTEGER DEFAULT 0,         -- Boolean (0 = False, 1 = True)
            admin INTEGER DEFAULT 0,             -- Boolean (0 = False, 1 = True)
            FOREIGN KEY(org) REFERENCES organizations(name)
        )
    """)

    # Updates
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            organization TEXT,
            original_text TEXT,       -- raw input (user text or transcription)
            structured_text TEXT,     -- AI-cleaned / structured version
            image_path TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)

    # Visits
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            visit_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)

    conn.commit()
    conn.close()


# === DB MIGRATION ===
def migrate_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # === USERS TABLE MIGRATION ===
    cursor.execute("PRAGMA table_info(users)")
    user_columns = [col[1] for col in cursor.fetchall()]

    if "first_name" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
    if "surname" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN surname TEXT")
    if "executive" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN executive INTEGER DEFAULT 0")
    if "admin" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN admin INTEGER DEFAULT 0")

    # === UPDATES TABLE MIGRATION ===
    cursor.execute("PRAGMA table_info(updates)")
    update_columns = [col[1] for col in cursor.fetchall()]

    # Add missing user_id column
    if "user_id" not in update_columns:
        cursor.execute("ALTER TABLE updates ADD COLUMN user_id INTEGER")

    # Add missing organization column
    if "organization" not in update_columns:
        cursor.execute("ALTER TABLE updates ADD COLUMN organization TEXT")

    # Backfill organization where possible
    cursor.execute("""
        UPDATE updates
        SET organization = (
            SELECT org FROM users WHERE users.user_id = updates.user_id
        )
        WHERE organization IS NULL
    """)

    conn.commit()
    conn.close()
    print("Database migration & backfill complete.")


# Onboarding
# === Start function (personalized + HTML) ===
async def start_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # 🔎 Replace with your actual DB query
    user_data = get_user_data(user_id)  
    # Example structure: {"first_name": "Rotimi", "surname":"Olasehinde", "org_name": "Overbrim"}

    if user_data:
        # 🎉 Already registered user
        first_name = user_data.get("first_name", "Friend")
        org_name = user_data.get("org_name", "Earth")

        await update.message.reply_text(
            f"🎉 Welcome back, <b>{first_name}</b> from <b>{org_name}</b>! 🚀\n\n"
            "Use the menu below to continue.",
            parse_mode="HTML",
            reply_markup=START_KEYBOARD
        )
        await show_main_menu(update, context)
        return ConversationHandler.END

    else:
        # 👋 New user onboarding
        return await start(update, context)

async def org_name_wrapper(update, context):
    result = await org_name(update, context)
    if result == "onboarding_complete":
        await update.message.reply_text("🎉 You’re all set! Let's go Sire 👑!", reply_markup=ReplyKeyboardRemove())

        # Small delay helps ensure Telegram processes the keyboard removal first
        await asyncio.sleep(0.3)

        await show_main_menu(update, context)
        return ConversationHandler.END
    elif result == "retry_org_name":
        return ORG_NAME
    return result


# === USER ROLES ===
def is_admin(user_id: int) -> bool:
    return get_user_roles(user_id)["admin"]

def is_exec(user_id: int) -> bool:
    return get_user_roles(user_id)["executive"]

# not registered i.e new users
def is_none(user_id: int) -> bool:
    return get_user_roles(user_id)["none"]

def get_all_admin_ids() -> list:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE admin = 1")
    rows = cursor.fetchall()
    conn.close()
    return [int(row[0]) for row in rows if row[0].isdigit()]

def get_user_data(user_id: int) -> dict | None:
    """
    Fetch user details (first_name, org_name) from DB.
    Also logs the visit timestamp if the user exists.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 🔹 Adjust column names if needed
    cursor.execute("SELECT first_name, surname, org FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()

    if row:
        first_name, surname, org_name = row

        # ✅ Log visit
        timestamp = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO visits (user_id, visit_time) VALUES (?, ?)",
            (user_id, timestamp)
        )
        conn.commit()

        conn.close()
        return {"first_name": first_name, "surname": surname, "org_name": org_name}

    conn.close()
    return None

# def is_admin(user_id: int) -> bool:
#     return str(user_id) in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",")

# def is_exec(user_id: int) -> bool:
#     return str(user_id) in os.getenv("EXEC_IDS", "").split(",")

# === File Types ===
def is_supported_file(filename: str) -> bool:
    """Check if file has a supported audio extension."""
    _, ext = os.path.splitext(filename)
    return ext.lower() in SUPPORTED_FORMATS


# === STRUCTURE TEXT ===
def structure_text(text: str) -> str:
    today = datetime.now().strftime("%d %b %Y")

    prompt = (
        "You are a helpful assistant that structures work updates for busy executives. "
        "Limit each section to no more than 5 bullet points and each point to 10 words or less"
        "Format your response in HTML suitable for Telegram's HTML parse mode. "
        "Follow this exact template:\n\n"
        f"<b>Date:</b> {today}\n\n"
        "<b>Progress:</b>\n"
        "• [Concise bullet point 1]\n"
        "• [Concise bullet point 2]\n"
        "• [Concise bullet point 3]\n"
        "• [etc., up to 5 points]\n\n"
        "<b>Incidence/Delay:</b>\n"
        "• [Concise bullet point 1]\n"
        "• [etc., or '• None.' if no issues]\n\n"
        "Ensure the response is clear, concise, and quick to read. Use no extra commentary.\n\n"
        f"Text: {text}"
    )
    response = model.generate_content(prompt)
    return response.text.strip()

# === STORE IN DB ===
# def save_update(telegram_id, username, original_text, structured_text, image_path=None):
#     conn = sqlite3.connect(DB_PATH)
#     cursor = conn.cursor()
#     cursor.execute('''
#     INSERT INTO updates (telegram_id, username, original_text, structured_text, image_path)
#     VALUES (?, ?, ?, ?, ?)
#     ''', (telegram_id, username, original_text, structured_text, image_path))
#     conn.commit()
#     conn.close()
def save_update(user_id, username, organization, original_text, structured_text, image_path=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO updates (user_id, username, organization, original_text, structured_text, image_path)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, username, organization, original_text, structured_text, image_path))
    conn.commit()
    conn.close()

# Track user states
user_state = {}

# First screen
# START_KEYBOARD = ReplyKeyboardMarkup(
#     [["▶️ Start"]],
#     resize_keyboard=True,
#     one_time_keyboard=False
# )

# === MAIN MENU BUTTONS ===
# MAIN_MENU = ReplyKeyboardMarkup(
#     [["✏️ Send Update", "📋 Get Updates", "🗑 Clear Updates"]],
#     resize_keyboard=True
# )

# === /start START COMMAND ===
# async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     keyboard = [[KeyboardButton("▶️ Start")]]
#     await update.message.reply_text(
#         "👋 Welcome! Tap '▶️ Start' to begin.",
#         reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
#     )

async def handle_start_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)

# === More Options Menu ===
async def more_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if is_exec(user_id):
        keyboard = [[KeyboardButton("📝 Send Update")]]
        if is_admin(user_id):
            keyboard.append([KeyboardButton("🗑️ Clear Updates")])
        keyboard.append([KeyboardButton("📋 Main Menu")])

        reply_markup = ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
            one_time_keyboard=True
        )

        await update.message.reply_text("🔄 More Options:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("🚫 Not authorized for more options.")

# === AFTER START PRESSED ===
# async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     user_state.pop(update.message.from_user.id, None)  # Reset state
#     await update.message.reply_text(
#         "✅ Ready! Please choose an option:",
#         reply_markup=MAIN_MENU
#     )                                 

async def show_main_menu(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    """Show menu according to role and reset state."""
    global user_state

    if hasattr(update_or_query, "message") and update_or_query.message:
        user_id = update_or_query.message.from_user.id
        chat = update_or_query.message
    elif hasattr(update_or_query, "callback_query") and update_or_query.callback_query:
        user_id = update_or_query.callback_query.from_user.id
        chat = update_or_query.callback_query.message
    else:
        return

    # ✅ Reset state
    user_state.pop(user_id, None)

    # Build role-based inline menu
    if is_exec(user_id):
        buttons = [
            [InlineKeyboardButton("📄 Last Update", callback_data="last_update")],
            [InlineKeyboardButton("📜 Recent Updates", callback_data="recent_updates")],
            [InlineKeyboardButton("🔄 More Options", callback_data="more_options_exec")],
        ]
    else:
        buttons = [
            [InlineKeyboardButton("📝 Send Update", callback_data="send_update")],
            [InlineKeyboardButton("📄 Last Update", callback_data="last_update")],
            [InlineKeyboardButton("📜 Recent Updates", callback_data="recent_updates")],
        ]

    markup = InlineKeyboardMarkup(buttons)

    # ✅ Always show menu at bottom
    if hasattr(update_or_query, "callback_query") and update_or_query.callback_query:
        # Delete the old inline menu to avoid clutter
        try:
            await update_or_query.callback_query.message.delete()
        except Exception:
            pass  # ignore if already deleted
        await chat.reply_text("📋 Main Menu", reply_markup=markup)
    else:
        await chat.reply_text("📋 Main Menu", reply_markup=markup)

# async def show_main_menu(update_or_query, context: ContextTypes.DEFAULT_TYPE):
#     """Show menu according to role and reset state."""
#     global user_state

#     # if getattr(update_or_query, "callback_query", None):
#     #     # Inline button press
#     #     user_id = update_or_query.callback_query.from_user.id
#     #     chat = update_or_query.callback_query.message
#     # else:
#     # Normal text message
#     user_id = update_or_query.message.from_user.id
#     chat = update_or_query.message

#     # ✅ Reset state
#     user_state.pop(user_id, None)

#     # Build role-based inline menu
#     if is_exec(user_id):
#         reply_keyboard = [
#             [KeyboardButton("📄 Last Update")],
#             [KeyboardButton("📜 Recent Updates")],
#             [KeyboardButton("🔄 More Options")],
#             [KeyboardButton("▶️ Start")]
#         ]
#     else:
#         reply_keyboard = [
#             [KeyboardButton("📝 Send Update")],
#             [KeyboardButton("📜 Recent Updates")],
#             [KeyboardButton("▶️ Start")]
#         ]

#     # Always show Start in ReplyKeyboardMarkup
#     # reply_keyboard = ReplyKeyboardMarkup(
#     #     [[KeyboardButton("▶️ Start")]],
#     #     resize_keyboard=True
#     # )

#     markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)

#     # Always reply with the menu
#     # await chat.reply_text("📋 Main Menu:", reply_markup=markup)

#     # if edit_message:
#     #     await update_or_query.callback_query.edit_message_text(
#     #         "📋 Main Menu:",
#     #         reply_markup=InlineKeyboardMarkup(inline_keyboard)
#     #     )
#     #     # Send separate reply keyboard
#     #     await context.bot.send_message(
#     #         chat_id=user_id,
#     #         text="Use ▶️ Start to restart anytime.",
#     #         reply_markup=reply_keyboard
#     #     )
#     # else:
#     #     await update_or_query.message.reply_text(
#     #         "📋 Main Menu:",
#     #         reply_markup=InlineKeyboardMarkup(inline_keyboard)
#     #     )
#     #     await update_or_query.message.reply_text(
#     #         "Use ▶️ Start to restart anytime.",
#     #         reply_markup=reply_keyboard
#     #     )

# ===== CALLBACKS =====
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    user_id = query.from_user.id

    # if action == "start":
    #     await show_main_menu(update, context)

    if action == "more_options_exec":
        keyboard = [[InlineKeyboardButton("📝 Send Update", callback_data="send_update")]]
        if is_admin(user_id):
            keyboard.append([InlineKeyboardButton("🗑️ Clear Updates", callback_data="clear_updates")])
        keyboard.append([InlineKeyboardButton("📋 Main Menu", callback_data="main_menu")])
        await query.edit_message_text("🔄 More Options:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == "last_update":
        await get_updates(update, context, limit=1)

    elif action == "recent_updates":
        await get_updates(update, context, limit=3)

    elif action == "send_update":
        await send_update(update, context)

    elif action == "clear_updates":
        if is_admin(user_id):
            await clear_updates(update, context)
        else:
            await query.edit_message_text("🚫 You are not authorized to clear updates.")
    
    elif action == "main_menu":
        await show_main_menu(update, context)

    else:
        # Fallback for unexpected callback_data
        print(f"DEBUG: Unhandled callback data = {action}")
        await query.edit_message_text("⚠️ Unknown action. Returning to main menu...")
        await show_main_menu(update, context)

# === SEND UPDATE FLOW ===
async def send_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle both message and callback cases
    if update.message:
        user_id = update.message.from_user.id
        chat = update.message
    elif update.callback_query:
        user_id = update.callback_query.from_user.id
        chat = update.callback_query.message
        # Answer the callback so it doesn’t spin
        await update.callback_query.answer()
    else:
        return
    
    user_state[user_id] = "awaiting_update"

    # Inline "Cancel" button (won’t send text into chat)
    keyboard = [
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_update")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await chat.reply_text(
        "📝 Please send your update now \n"
        "as text 📜 or audio 🎙.\n\n"
        "You can also attach an image 📷.",
        reply_markup=reply_markup
    )

# async def send_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     user_id = update.message.from_user.id
#     user_state[user_id] = "awaiting_update"

#     # Build a small reply keyboard (optional – can also just accept free text/audio)
#     keyboard = [
#         [KeyboardButton("❌ Cancel")]
#     ]

#     reply_markup = ReplyKeyboardMarkup(
#         keyboard, resize_keyboard=True, one_time_keyboard=True
#     )

#     await update.message.reply_text(
#         "📝 Please send your update now \n"
#         "as text 📜 or audio 🎙.\n\n"
#         "You can also attach an image 📷.",
#         reply_markup=reply_markup
#     )

# === CLEAR UPDATES (ADMIN ONLY) ===
async def clear_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle both callback and command cases
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        chat = query.message
    elif update.message:
        user_id = update.message.from_user.id
        chat = update.message
    else:
        return

    if not is_admin(user_id):
        print(f"Unauthorized clear attempt by user {user_id}")
        await chat.reply_text("🚫 You are not authorized to clear updates.")
        return

    # Reset only this admin's state
    user_state.pop(user_id, None)

    keyboard = [
        [InlineKeyboardButton("✅ Yes, clear all", callback_data="confirm_clear")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_clear")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await chat.reply_text(
        "⚠ Are you sure you want to delete ALL updates and images?",
        reply_markup=reply_markup
    )

# === CONFIRMATION HANDLER (ADMIN ONLY) ===
async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    choice = query.data

    print(f"DEBUG: handle_confirmation triggered with choice = {choice}")

    # ✅ Authorization check
    if not is_admin(user_id):
        print(f"Unauthorized clear attempt by user {user_id}")
        await query.edit_message_text("🚫 You are not authorized to clear updates.")
        await show_main_menu(update, context)
        return

    if choice == "confirm_clear":
        image_paths = []
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT image_path FROM updates")
            image_paths = cursor.fetchall()
            cursor.execute("DELETE FROM updates")
            deleted_count = cursor.rowcount
            conn.commit()
            print(f"Cleared {deleted_count} updates from DB")
        except Exception as e:
            print(f"Error clearing updates: {e}")
        finally:
            if conn:
                conn.close()

        # Delete images from disk
        removed, failed = 0, 0
        for img in image_paths:
            if img[0] and os.path.exists(img[0]):
                try:
                    os.remove(img[0])
                    removed += 1
                except Exception as e:
                    failed += 1
                    print(f"Failed to delete {img[0]}: {e}")

        # Clear all user states
        user_state.clear()

        await query.edit_message_text(
            f"🗑 Cleared {deleted_count} updates.\n"
            f"🖼 Deleted {removed} images ({failed} failed)."
        )
        await show_main_menu(update, context)

    elif choice == "cancel_clear":
        await query.edit_message_text("❌ Cancelled.")
        await show_main_menu(update, context)

# === HANDLE TEXT, AUDIO + IMAGE ===
def transcribe_audio_assemblyai(audio_source: str):
    # base_url = "https://api.assemblyai.com"

    # headers = {
    #     "authorization": ASSEMBLYAI_API_KEY,
    # }

    # with open("./my-audio.mp3", "rb") as f:
    #     response = requests.post(base_url + "/v2/upload",
    #                         headers=headers,
    #                         data=f)

    # audio_url = response.json()["upload_url"]
    # data = {
    # "audio_url": audio_url,
    # "speech_model": "universal"
    # }

    # url = base_url + "/v2/transcript"
    # response = requests.post(url, json=data, headers=headers)

    # transcript_id = response.json()['id']
    # polling_endpoint = base_url + "/v2/transcript/" + transcript_id

    # for _ in range(60):
    #     transcription_result = requests.get(polling_endpoint, headers=headers).json()
    #     transcript_text = transcription_result['text']

    #     if transcription_result['status'] == 'completed':
    #         return transcript_text

    #     elif transcription_result['status'] == 'error':
    #         raise RuntimeError(f"Transcription failed: {transcription_result['error']}")

    #     else:
    #         time.sleep(3)
    """
    Transcribe local or remote audio using AssemblyAI.
    Supports mp3, wav, m4a, flac, ogg, webm.
    """
    try:
        # 🧠 Detect if input is URL or local file
        if audio_source.startswith("http://") or audio_source.startswith("https://"):
            print(f"Transcribing from URL: {audio_source}")
        else:
            if not os.path.exists(audio_source):
                raise FileNotFoundError(f"File not found: {audio_source}")
            if not is_supported_file(audio_source):
                raise ValueError(
                    f"Unsupported file type: {audio_source}\n"
                    f"Supported formats: {', '.join(SUPPORTED_FORMATS)}"
                )
            print(f"Transcribing local file: {audio_source}")

        # 🪄 Configure and transcribe
        config = aai.TranscriptionConfig(
            speech_model=aai.SpeechModel.universal
        )

        transcriber = aai.Transcriber(config=config)
        transcript = transcriber.transcribe(audio_source)

        # 🧾 Check for errors
        if transcript.status == "error":
            raise RuntimeError(f"Transcription failed: {transcript.error}")

        print("\n Transcription successful:\n")
        print(transcript.text)
        return transcript.text

    except Exception as e:
        print("Error in transcription:", e)
        return None

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ensure we actually got a valid message
    if not update.message:
        return

    message = update.message

    # Get audio/voice file_id safely
    file_id = None
    if message.voice:
        file_id = message.voice.file_id
    elif message.audio:
        file_id = message.audio.file_id

    if not file_id:
        await message.reply_text("⚠️ Please send a voice note 🎙 or audio file 🎵.")
        return

    # Build unique temp filename (avoid clashes if multiple audios come in)
    file_path = f"temp_audio_{message.from_user.id}_{message.message_id}.ogg"

    # Download audio file
    try:
        file = await context.bot.get_file(file_id)
        await file.download_to_drive(file_path)
    except Exception as e:
        print(f"Error downloading audio: {e}")
        await message.reply_text("⚠️ Failed to download audio. Please try again.")
        return

    await message.reply_text("📢 Processing your audio...")

    try:
        # transcriber = aai.Transcriber()
        # transcript = transcriber.transcribe(file_path)
        # # Transcription with AssemblyAI
        # transcriber = aai.Transcriber()
        # # Run the blocking transcription in a separate thread
        # loop = asyncio.get_running_loop()
        # transcript = await loop.run_in_executor(None, transcriber.transcribe, file_path)
        # transcript = await context.application.run_in_executor(None, transcriber.transcribe, file_path)
        transcript = transcribe_audio_assemblyai(file_path)
        transcribed_text = transcript.strip()
        # result = transcribe_audio_assemblyai(file_path)

        # Transcription with Whisper
        # result = audiomodel.transcribe(file_path)
        # Get Transcribed Text
        # transcribed_text = result.get("text", "").strip()

        if not transcribed_text:
            await message.reply_text("⚠️ I couldn't understand that audio. Please try again.")
            return

        # Reuse your text handler with override
        await handle_message(update, context, override_text=transcribed_text)

    except Exception as e:
        print(f"Error in transcription: {e}")
        await message.reply_text("An error occurred while processing your audio.")
    finally:
        # Clean up file
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Failed to remove temp file {file_path}: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE, override_text=None):
    # Determine the source (message only, we don’t handle callbacks here)
    if not update.message:
        return

    user_id = update.message.from_user.id
    username = update.message.from_user.username
    msg_source = update.message

    # ✅ Only process if user is in update mode
    if user_state.get(user_id) != "awaiting_update":
        return

    # --- Fetch organization for this user ---
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT org FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await msg_source.reply_text("⚠️ You are not registered under any organization.")
        return

    organization = row[0]
    image_path = None

    # --- Handle image ---
    if msg_source.photo:
        file = await msg_source.photo[-1].get_file()
        image_path = f"{user_id}_{datetime.now().timestamp()}.jpg"
        await file.download_to_drive(image_path)

    # --- Decide what text to use ---
    if override_text:  # from audio transcription
        text = override_text
    elif msg_source.caption:  # from image caption
        text = msg_source.caption
    else:
        text = msg_source.text or ""

    if not text.strip() and not image_path:
        await msg_source.reply_text("⚠️ Please send some text, audio, or an image with a caption.")
        return

    # --- Process text into structured format ---
    structured = structure_text(text) if text.strip() else "[No text provided]"

    save_update(
        user_id=user_id,
        username=username,
        organization=organization,
        original_text=text,
        structured_text=structured,
        image_path=image_path
    )

    # Send the structured update confirmation
    await msg_source.reply_text(f"✅ Here's your structured update:\n\n{structured}")

    # Reset state after update
    user_state.pop(user_id, None)

    # Show role-based main menu again
    await show_main_menu(update, context)

# === Get Updates ===
# === /get_updates COMMAND (with images) ===
async def get_updates(update_or_query, context: ContextTypes.DEFAULT_TYPE, limit=3):
    # Handle both message and callback cases
    if hasattr(update_or_query, "message") and update_or_query.message:
        chat = update_or_query.message
    else:
        query = update_or_query.callback_query
        chat = query.message

    print("DEBUG: get_updates triggered from:", type(chat))

    # Fetch latest updates
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username, structured_text, timestamp, image_path "
        "FROM updates ORDER BY timestamp DESC LIMIT ?",
        (limit,)
    )
    rows = cursor.fetchall()
    rows.reverse()  # Show oldest first
    conn.close()

    if not rows:
        await chat.reply_text("No updates recorded yet.")
        return

    # Send each update
    for username, structured_text, timestamp, image_path in rows:
        await send_executive_update(
            chat,  # works whether it's a Message or CallbackQuery.message
            username=username,
            timestamp=timestamp,
            structured_text=structured_text,
            image_path=image_path,
        )
        await asyncio.sleep(0.2)  # avoid spamming too quickly

    # Return to the correct main menu
    await show_main_menu(update_or_query, context)

async def send_executive_update(chat, username, timestamp, structured_text, image_path=None):
    """Send a nicely formatted executive-style update with optional image."""
    message_text = (
        f"👤 **@{username}**\n"
        f"{structured_text}"
    )

    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            await chat.reply_photo(
                photo=InputFile(img_file),
                caption=message_text,
                parse_mode="HTML"
            )
    else:
        await chat.reply_text(message_text, parse_mode="HTML")


# === MAIN FUNCTION ===
async def main():
    init_db()
    migrate_db()
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Conversation for org selection
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_wrapper),
                    MessageHandler(filters.TEXT & filters.Regex(r"^▶️ Start$"), start_wrapper),
                    MessageHandler(filters.TEXT & filters.Regex(r"^start over$"), start_wrapper)
        ],
        states={
            FIRST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, first_name)],
            SURNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, surname)],
            ORG_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, org_choice)],
            ORG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, org_name_wrapper)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)
    
    # === COMMANDS ===
    # === INLINE MENU CALLBACKS ===
    app.add_handler(CallbackQueryHandler(show_main_menu, pattern="^main_menu$"))
    # app.add_handler(CallbackQueryHandler(get_updates, pattern="^(last_update|recent_updates)$"))
    app.add_handler(CallbackQueryHandler(send_update, pattern="^send_update$"))
    app.add_handler(CallbackQueryHandler(more_options, pattern="^more_options$"))
    app.add_handler(CallbackQueryHandler(show_main_menu, pattern="^cancel_update$"))
    app.add_handler(CallbackQueryHandler(clear_updates, pattern="^clear_updates$"))
    app.add_handler(CallbackQueryHandler(handle_confirmation, pattern="^(confirm_clear|cancel_clear)$"))

    # Generic fallback for other callback_data
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Dev Only commands
    app.add_handler(CommandHandler("resetonboarding", reset_onboarding))
    app.add_handler(CommandHandler("promote_user", promote_user))
    app.add_handler(CommandHandler("demote_user", demote_user))

    # === MESSAGE INPUTS (actual updates from users) ===
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))

    # Run the bot
    # app.run_polling()

    # === WEBHOOK SETUP ===
    # Render will provide PORT in environment variables
    port = int(os.getenv("PORT", PORT))

    # Remove any old webhook before setting new one
    await app.bot.delete_webhook()
    await app.bot.set_webhook(WEBHOOK_URL)

    print(f"🚀 Webhook set at {WEBHOOK_URL} listening on port {port}...")

    # Start webhook server (non-blocking)
    await app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=WEBHOOK_URL,
        stop_signals=None,
    )



if __name__ == "__main__":
    asyncio.run(main())
