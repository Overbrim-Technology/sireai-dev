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
from telegram import Update, InputFile, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ConversationHandler, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import google.generativeai as genai

from settings import (GEMINI_API_KEY, GEMINI_API_URL, TELEGRAM_BOT_TOKEN, ASSEMBLYAI_API_KEY, WEBHOOK_URL, PORT,
                      SUPPORTED_FORMATS, DEV_USER_IDS, ADMIN_USER_IDS, EXEC_IDS,
                      init_db_pool, pool
                      )

from exec_report_onboarding import (start, org_choice, org_name, first_name, surname, cancel,
                                    FIRST_NAME, SURNAME, ORG_CHOICE, ORG_NAME, START_KEYBOARD)
                                    
from exec_report_dev import reset_onboarding, promote_user, demote_user, get_user_roles, clear_user_roles_cache


load_dotenv()


# === SETUP LOGGING ===
logging.basicConfig(level=logging.INFO)

# === SETUP GEMINI ===
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")
# Load Whisper model once (large-v3)
# audiomodel = whisper.load_model("turbo")

# === SETUP DB ===
async def init_db():
    """Create tables with org-specific roles and indexes."""
    pool = await init_db_pool()

    schema_sql = """
    -- Organizations table
    CREATE TABLE IF NOT EXISTS organizations (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE NOT NULL
    );

    -- Users table
    CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        surname TEXT
    );

    -- Join table: users <-> organizations, with org-specific roles
    CREATE TABLE IF NOT EXISTS user_orgs (
        id SERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
        org_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,
        executive BOOLEAN DEFAULT FALSE,
        admin BOOLEAN DEFAULT FALSE,
        UNIQUE(user_id, org_id)
    );

    -- Updates table per org
    CREATE TABLE IF NOT EXISTS updates (
        id SERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(user_id),
        org_id INTEGER REFERENCES organizations(id),
        username TEXT,
        original_text TEXT,
        structured_text TEXT,
        image_path TEXT,
        timestamp TIMESTAMP DEFAULT NOW()
    );

    -- Visits log table
    CREATE TABLE IF NOT EXISTS visits (
        id SERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(user_id),
        visit_time TIMESTAMP DEFAULT NOW()
    );

    -- Indexes for faster lookups
    CREATE INDEX IF NOT EXISTS idx_user_orgs_user_id ON user_orgs(user_id);
    CREATE INDEX IF NOT EXISTS idx_user_orgs_org_id ON user_orgs(org_id);
    CREATE INDEX IF NOT EXISTS idx_updates_user_id ON updates(user_id);
    CREATE INDEX IF NOT EXISTS idx_updates_org_id ON updates(org_id);
    CREATE INDEX IF NOT EXISTS idx_visits_user_id ON visits(user_id);
    """

    async with pool.acquire() as conn:
        await conn.execute(schema_sql)
        print("✅ Database initialized with multi-org support and role flags per org.")

    return pool

# Onboarding
# === Start function (personalized + HTML) ===
async def start_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    user_data = await get_user_data(user_id)  # asyncpg version
    # user_data could be {"first_name": "...", "surname": "...", "orgs": ["Overbrim", "OtherOrg"]}

    if user_data:
        first_name = user_data.get("first_name", "Friend")
        orgs = user_data.get("orgs", [])
        org_display = orgs[0] if orgs else "Earth"

        await update.message.reply_text(
            f"🎉 Welcome back, <b>{first_name}</b> from <b>{org_display}</b>! 🚀\n\n"
            "Use the menu below to continue.",
            parse_mode="HTML",
            reply_markup=START_KEYBOARD
        )
        await show_main_menu(update, context)
        return ConversationHandler.END

    else:
        return await start(update, context)


async def org_name_wrapper(update, context):
    result = await org_name(update, context)  # asyncpg-aware org_name
    if result == "onboarding_complete":
        await update.message.reply_text(
            "🎉 You’re all set! Let's go Sire 👑!",
            reply_markup=ReplyKeyboardRemove()
        )
        await asyncio.sleep(0.3)
        await show_main_menu(update, context)
        return ConversationHandler.END
    elif result == "retry_org_name":
        return ORG_NAME
    return result


# === USER ROLES ===
async def is_admin(user_id: int, org_id: int) -> bool:
    """Check if a user is admin in a specific organization."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM user_orgs WHERE user_id=$1 AND org_id=$2 AND admin=TRUE",
            user_id, org_id
        )
    return row is not None

async def is_exec(user_id: int, org_id: int) -> bool:
    """Check if a user is executive in a specific organization."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM user_orgs WHERE user_id=$1 AND org_id=$2 AND executive=TRUE",
            user_id, org_id
        )
    return row is not None

async def is_none(user_id: int) -> bool:
    """Check if a user is not part of any organization."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM user_orgs WHERE user_id=$1 LIMIT 1",
            user_id
        )
    return row is None

async def get_all_admin_ids() -> list[int]:
    """Return a list of all user_ids who are admin in any org."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT user_id FROM user_orgs WHERE admin=TRUE")
        return [r["user_id"] for r in rows]

async def get_admin_org_ids(user_id: int) -> list[int]:
    """Return a list of org IDs where the user is admin."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT org_id FROM user_orgs WHERE user_id=$1 AND admin=TRUE",
            user_id
        )
        return [r["org_id"] for r in rows]


async def get_user_data(telegram_id: int) -> dict | None:
    async with pool.acquire() as conn:

        # Fetch user core data
        user = await conn.fetchrow(
            """
            SELECT id, first_name, surname
            FROM users
            WHERE telegram_id = $1
            """,
            telegram_id
        )

        if not user:
            return None

        user_id = user["id"]

        # Fetch user organizations (may be many)
        org_rows = await conn.fetch(
            """
            SELECT o.name
            FROM organizations o
            JOIN user_orgs uo ON o.id = uo.org_id
            WHERE uo.user_id = $1
            """,
            user_id
        )

        org_list = [r["name"] for r in org_rows]

        # Log visit
        await conn.execute(
            "INSERT INTO visits (user_id, visit_time) VALUES ($1, $2)",
            user_id,
            datetime.utcnow()
        )

        return {
            "first_name": user["first_name"],
            "surname": user["surname"],
            "organizations": org_list
        }


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
        "Limit each section to no more than 4 bullet points and each point to 9 words or less"
        "Format your response in HTML suitable for Telegram's HTML parse mode. "
        "Follow this exact template:\n\n"
        f"<b>Date:</b> {today}\n\n"
        "<b>Progress:</b>\n"
        "• [Concise bullet point 1]\n"
        "• [Concise bullet point 2]\n"
        "• [Concise bullet point 3]\n"
        "• [etc., up to 4 points]\n\n"
        "<b>Incidence/Delay:</b>\n"
        "• [Concise bullet point 1]\n"
        "• [etc., or '• None.' if no issues]\n\n"
        "Ensure the response is clear, concise, and quick to read. Use no extra commentary.\n\n"
        f"Text: {text}"
    )
    response = model.generate_content(prompt)
    return response.text.strip()

# === STORE IN DB ===
async def save_update(user_id: int, username: str, org_id: int, original_text: str, structured_text: str, image_path: str | None):
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO updates 
                (user_id, username, org_id, original_text, structured_text, image_path)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            user_id,
            username,
            org_id,
            original_text,
            structured_text,
            image_path
        )

# Track user states
user_state = {}

# First screen
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
    # Determine user and chat
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

    # Get active organization for this user (assume stored in user_data)
    org_id = context.user_data.get("active_org_id")
    if org_id is None:
        await chat.reply_text("⚠ Please select an organization first to manage updates.")
        return

    # Admin check per org
    if not await is_admin(user_id, org_id):
        print(f"Unauthorized clear attempt by user {user_id} for org {org_id}")
        await chat.reply_text("🚫 You are not authorized to clear updates for this organization.")
        return

    # Ask for confirmation
    keyboard = [
        [InlineKeyboardButton("✅ Yes, clear all", callback_data=f"confirm_clear:{org_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_clear")]
    ]
    await chat.reply_text(
        "⚠ Are you sure you want to delete ALL updates and images for this organization?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# === CONFIRMATION HANDLER (ADMIN ONLY) ===
async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    choice = query.data

    if choice != "confirm_clear":
        await query.edit_message_text("❌ Cancelled.")
        await show_main_menu(update, context)
        return

    # 🚨 Admin Authorization
    admin_orgs = await get_admin_org_ids(user_id)
    if not admin_orgs:
        await query.edit_message_text("🚫 You are not an admin of any organization.")
        return

    # 🔥 Delete updates ONLY for these orgs
    org_tuple = tuple(admin_orgs)

    async with pool.acquire() as conn:

        # 1. Get image paths first (before deleting)
        image_rows = await conn.fetch(
            "SELECT image_path FROM updates WHERE org_id = ANY($1)",
            org_tuple
        )
        image_paths = [row["image_path"] for row in image_rows if row["image_path"]]

        # 2. Delete the updates
        result = await conn.execute(
            "DELETE FROM updates WHERE org_id = ANY($1)",
            org_tuple
        )

    # 🧹 Delete images from disk
    removed = 0
    failed = 0
    for path in image_paths:
        if os.path.exists(path):
            try:
                os.remove(path)
                removed += 1
            except:
                failed += 1

    await query.edit_message_text(
        f"🗑 Cleared updates for <b>{len(admin_orgs)}</b> organization(s).\n"
        f"🖼 Deleted {removed} images ({failed} failed).",
        parse_mode="HTML"
    )

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
        transcript = transcribe_audio_assemblyai(file_path)
        transcribed_text = transcript.strip()

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
    if not update.message:
        return

    user_id = update.message.from_user.id
    username = update.message.from_user.username or ""
    msg_source = update.message

    # Only process if user is in update mode
    if user_state.get(user_id) != "awaiting_update":
        return

    # --- Fetch active organization for this user ---
    org_id = context.user_data.get("active_org_id")
    if not org_id:
        await msg_source.reply_text("⚠️ Please select an organization first to send an update.")
        return

    image_path = None

    # --- Handle image ---
    if msg_source.photo:
        file = await msg_source.photo[-1].get_file()
        image_path = f"{user_id}_{datetime.now().timestamp()}.jpg"
        await file.download_to_drive(image_path)

    # --- Decide text ---
    if override_text:
        text = override_text
    elif msg_source.caption:
        text = msg_source.caption
    else:
        text = msg_source.text or ""

    if not text.strip() and not image_path:
        await msg_source.reply_text("⚠️ Please send some text, audio, or an image with a caption.")
        return

    structured = structure_text(text) if text.strip() else "[No text provided]"

    # --- Save update in Postgres ---
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO updates (user_id, org_id, username, original_text, structured_text, image_path)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            user_id, org_id, username, text, structured, image_path
        )

    # Confirmation message
    await msg_source.reply_text(f"✅ Here's your structured update:\n\n{structured}")

    # Reset state
    user_state.pop(user_id, None)

    # Show role-based main menu again
    await show_main_menu(update, context)


# === Get Updates ===
# === /get_updates COMMAND (with images) ===
async def get_updates(update_or_query, context: ContextTypes.DEFAULT_TYPE, limit=3):
    # Determine chat object
    if hasattr(update_or_query, "message") and update_or_query.message:
        chat = update_or_query.message
    elif hasattr(update_or_query, "callback_query") and update_or_query.callback_query:
        query = update_or_query.callback_query
        chat = query.message
        await query.answer()
    else:
        return

    user_id = chat.from_user.id

    # --- Determine active organization for this user ---
    org_id = context.user_data.get("active_org_id")
    if not org_id:
        await chat.reply_text("⚠ Please select an organization first to view updates.")
        return

    # --- Fetch latest updates for this org ---
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT u.username, upd.structured_text, upd.timestamp, upd.image_path
            FROM updates upd
            JOIN users u ON upd.user_id = u.user_id
            WHERE upd.org_id = $1
            ORDER BY upd.timestamp DESC
            LIMIT $2
            """,
            org_id, limit
        )

    if not rows:
        await chat.reply_text("No updates recorded yet for this organization.")
        return

    # Send updates oldest-first
    for row in reversed(rows):
        await send_executive_update(
            chat,
            username=row["username"],
            timestamp=row["timestamp"],
            structured_text=row["structured_text"],
            image_path=row["image_path"],
        )
        await asyncio.sleep(0.2)  # avoid spamming too quickly

    # Return to main menu
    await show_main_menu(update_or_query, context)


async def send_executive_update(chat, username, timestamp, structured_text, image_path=None):
    """Send a nicely formatted executive-style update with optional image."""
    message_text = (
        f"👤 <b>@{username}</b>\n"
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

    await init_db_pool()

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
    # === WEBHOOK CONFIG ===
    port = int(os.getenv("PORT", PORT))
    await app.bot.delete_webhook()
    await app.bot.set_webhook(WEBHOOK_URL)

    print(f"🚀 Webhook set at {WEBHOOK_URL} listening on port {port}...")

    # 👇 FIXED PART
    # run_webhook() tries to close loop internally — Render keeps it alive.
    # So we just run the internal webhook startup manually:
    await app.initialize()
    await app.start()
    await app.updater.start_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=WEBHOOK_URL,
    )

    print("✅ Webhook server running. Waiting for Telegram updates...")

    # Keep it running forever
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())