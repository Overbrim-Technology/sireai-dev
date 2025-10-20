import sqlite3
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ConversationHandler, CallbackQueryHandler, ContextTypes
)

DB_PATH = "work_updates.db"

# States for onboarding
# ORG_CHOICE, ORG_NAME = range(2)

# First screen
START_KEYBOARD = ReplyKeyboardMarkup([["▶️ Start"]], resize_keyboard=True, one_time_keyboard=False)
join_create_org = [["Join Organization", "Create Organization"]]

# # === START COMMAND ===
# async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     user_id = update.effective_user.id
#     username = update.effective_user.username or update.effective_user.first_name

#     conn = sqlite3.connect(DB_PATH)
#     cursor = conn.cursor()
#     cursor.execute("SELECT org FROM users WHERE user_id=?", (user_id,))
#     row = cursor.fetchone()
#     conn.close()

#     if row:
#         # ✅ Returning user → greet + show inline main menu
#         await update.message.reply_text(
#             f"👋 Welcome back {username}! You're registered under <b>{row[0]}</b>.",
#             parse_mode="HTML",
#             reply_markup=START_KEYBOARD
#         )

#         keyboard = [
#             [InlineKeyboardButton("📄 Last Update", callback_data="last_update")],
#             [InlineKeyboardButton("📜 Recent Updates", callback_data="recent_updates")],
#             [InlineKeyboardButton("📝 Send Update", callback_data="send_update")],
#             [InlineKeyboardButton("🔄 More Options", callback_data="more_options_exec")]
#         ]
#         await update.message.reply_text(
#             "Here’s your main menu:",
#             reply_markup=InlineKeyboardMarkup(keyboard)
#         )

#         return ConversationHandler.END

#     else:
#         # ✅ New user → ReplyKeyboard for registration
#         reply_keyboard = [["Join Organization", "Create Organization"]]
#         await update.message.reply_text(
#             "👋 Welcome! Please select an option:",
#             reply_markup=ReplyKeyboardMarkup(
#                 reply_keyboard,
#                 one_time_keyboard=True,
#                 resize_keyboard=True
#             )
#         )
#         return ORG_CHOICE

# # === HANDLE ORG CHOICE ===
# async def org_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     text = update.message.text
#     if text == "Create Organization":
#         await update.message.reply_text(
#             "Great! Please enter the name of your new organization:",
#             reply_markup=ReplyKeyboardRemove()
#         )
#         context.user_data["choice"] = "create"
#         return ORG_NAME

#     elif text == "Join Organization":
#         await update.message.reply_text(
#             "Please enter the name of the organization you want to join:",
#             reply_markup=ReplyKeyboardRemove()
#         )
#         context.user_data["choice"] = "join"
#         return ORG_NAME

#     else:
#         await update.message.reply_text("Please pick one of the options.")
#         return ORG_CHOICE


# # === HANDLE ORG NAME ===
# async def org_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     org_name = update.message.text.strip()
#     choice = context.user_data.get("choice")
#     user_id = update.effective_user.id
#     username = update.effective_user.username or update.effective_user.first_name

#     conn = sqlite3.connect(DB_PATH)
#     cursor = conn.cursor()

#     if choice == "create":
#         # create org if not exists
#         cursor.execute("INSERT OR IGNORE INTO organizations (name) VALUES (?)", (org_name,))
#         cursor.execute(
#             "INSERT OR REPLACE INTO users (user_id, username, org) VALUES (?, ?, ?)",
#             (user_id, username, org_name)
#         )
#         conn.commit()
#         await update.message.reply_text(
#             f"✅ Organization *{org_name}* created and you are registered!",
#             parse_mode="Markdown"
#         )

#     elif choice == "join":
#         cursor.execute("SELECT name FROM organizations WHERE name=?", (org_name,))
#         row = cursor.fetchone()
#         if row:
#             cursor.execute(
#                 "INSERT OR REPLACE INTO users (user_id, username, org) VALUES (?, ?, ?)",
#                 (user_id, username, org_name)
#             )
#             conn.commit()
#             await update.message.reply_text(
#                 f"✅ You’ve joined organization *{org_name}*.",
#                 parse_mode="Markdown"
#             )
#         else:
#             await update.message.reply_text(
#                 f"❌ Organization *{org_name}* does not exist. Please try again."
#             )
#             conn.close()
#             return ORG_NAME

#     conn.close()

#     # ✅ After successful registration → show inline main menu
#     keyboard = [
#         [InlineKeyboardButton("📄 Last Update", callback_data="last_update")],
#         [InlineKeyboardButton("📜 Recent Updates", callback_data="recent_updates")],
#         [InlineKeyboardButton("📝 Send Update", callback_data="send_update")],
#         [InlineKeyboardButton("⚙️ More Options", callback_data="more_options_exec")]
#     ]
#     await update.message.reply_text(
#         "🎉 You’re all set! Use the menu below:",
#         reply_markup=InlineKeyboardMarkup(keyboard)
#     )

#     return ConversationHandler.END


# # === CANCEL HANDLER ===
# async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     await update.message.reply_text(
#         "Onboarding cancelled.",
#         reply_markup=ReplyKeyboardRemove()
#     )
#     return ConversationHandler.END


# === DB INIT ===
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            org TEXT,
            FOREIGN KEY(org) REFERENCES organizations(name)
        )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS updates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        organization TEXT,
        original_text TEXT,       -- raw input (user text or transcription)
        structured_text TEXT,     -- AI-cleaned / structured version
        image_path TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

# === Start onboarding ===
ORG_CHOICE, ORG_NAME, FIRST_NAME, SURNAME = range(4)
# First screen
START_KEYBOARD = ReplyKeyboardMarkup([["▶️ Start"]], resize_keyboard=True, one_time_keyboard=False)

# === START COMMAND ===
# async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     user_id = update.effective_user.id
#     username = update.effective_user.username or update.effective_user.first_name

#     conn = sqlite3.connect(DB_PATH)
#     cursor = conn.cursor()
#     cursor.execute("SELECT org FROM users WHERE user_id=?", (user_id,))
#     row = cursor.fetchone()
#     conn.close()

#     if row:
#         # ✅ Returning user → greet + show inline main menu
#         await update.message.reply_text(
#             f"👋 Welcome back {username}! You're registered under <b>{row[0]}</b>.",
#             parse_mode="HTML",
#             reply_markup=START_KEYBOARD
#         )

#         keyboard = [
#             [InlineKeyboardButton("📄 Last Update", callback_data="last_update")],
#             [InlineKeyboardButton("📜 Recent Updates", callback_data="recent_updates")],
#             [InlineKeyboardButton("📝 Send Update", callback_data="send_update")],
#             [InlineKeyboardButton("🔄 More Options", callback_data="more_options_exec")]
#         ]
#         await update.message.reply_text(
#             "Here’s your main menu:",
#             reply_markup=InlineKeyboardMarkup(keyboard)
#         )

#         return ConversationHandler.END

#     else:
#         # ✅ New user → ReplyKeyboard for registration
#         reply_keyboard = [["Join Organization", "Create Organization"]]
#         await update.message.reply_text(
#             "👋 Welcome! Please select an option:",
#             reply_markup=ReplyKeyboardMarkup(
#                 reply_keyboard,
#                 one_time_keyboard=True,
#                 resize_keyboard=True
#             )
#         )
#         return ORG_CHOICE

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome! Let's get you set up.\n\n"
        "Please enter your <b>First Name</b>:",
        parse_mode="HTML"
    )
    return FIRST_NAME

# === Collect first name ===
async def first_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["first_name"] = update.message.text.strip()
    await update.message.reply_text("Great! Now enter your *Surname*:", parse_mode="Markdown")
    return SURNAME

# === Collect surname ===
async def surname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["surname"] = update.message.text.strip()

    await update.message.reply_text(
        "Would you like to *Join* an existing organization or *Create* a new one?",
        reply_markup=ReplyKeyboardMarkup(join_create_org, resize_keyboard=True),
        parse_mode="Markdown"
    )
    return ORG_CHOICE


# === Handle org choice ===
async def org_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    context.user_data["choice"] = choice.lower().split()[0]  # "join" or "create"

    if choice == "Join Organization":
        await update.message.reply_text(
            "Please enter the name of the organization you want to join:",
            reply_markup=ReplyKeyboardRemove()
        )
        return ORG_NAME

    elif choice == "Create Organization":
        # ✅ Allow any user to create org
        await update.message.reply_text(
            "Great! Please enter the name of your new organization:",
            reply_markup=ReplyKeyboardRemove()
        )
        return ORG_NAME

    else:
        await update.message.reply_text("Please pick one of the options.")
        return ORG_CHOICE

# === Handle org name and finalize ===
async def org_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    org_name = update.message.text.strip()
    user_id = update.message.from_user.id
    username = update.message.from_user.username or ""
    first_name = context.user_data.get("first_name", "")
    surname = context.user_data.get("surname", "")
    choice = context.user_data.get("choice")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # === Handle follow-up actions after retry ===
    # If user tapped a retry option, update choice accordingly
    if org_name.lower().startswith("join existing"):
        context.user_data["choice"] = "join"
        await update.message.reply_text(
            "🔁 Great! Please enter the name of the organization you'd like to join:",
            parse_mode="HTML", reply_markup=ReplyKeyboardRemove()
        )
        conn.close()
        return "retry_org_name"

    elif org_name.lower().startswith("create new"):
        context.user_data["choice"] = "create"
        await update.message.reply_text(
            "✨ Awesome! Please enter a new unique name for your organization:",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
        conn.close()
        return "retry_org_name"

    elif org_name.lower().startswith("try again"):
        await update.message.reply_text(
            "🔁 Please re-enter the correct organization name:",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
        conn.close()
        return "retry_org_name"

    if choice == "create":
        try:
            cursor.execute("INSERT INTO organizations (name) VALUES (?)", (org_name,))
            conn.commit()
            await update.message.reply_text(f"✅ Organization *{org_name}* created successfully!",
                                            parse_mode="Markdown",reply_markup=ReplyKeyboardRemove())
        except sqlite3.IntegrityError:
            await update.message.reply_text(
                f"⚠️ The organization <b>{org_name}</b> already exists.\n\n"
                "Would you like to <b>join</b> it instead or <b>create</b> a different one?",
                parse_mode="HTML",
                reply_markup=ReplyKeyboardMarkup(
                    join_create_org,
                    resize_keyboard=True
                )
            )
            conn.close()
            return "retry_org_name"

        # ✅ Mark creator as executive + admin
        cursor.execute("""
            INSERT INTO users (user_id, username, org, first_name, surname, executive, admin)
            VALUES (?, ?, ?, ?, ?, 1, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                org=excluded.org,
                first_name=excluded.first_name,
                surname=excluded.surname,
                executive=1,
                admin=1
        """, (user_id, username, org_name, first_name, surname))

    elif choice == "join":
        cursor.execute("SELECT id FROM organizations WHERE name=?", (org_name,))
        if not cursor.fetchone():
            await update.message.reply_text(
                "⚠️ Organization not found. Please check the name or create a new one.",
                parse_mode="HTML",
                reply_markup=ReplyKeyboardMarkup(
                    [["Try Again", "Create New Organization"]],
                    resize_keyboard=True
                )
            )
            conn.close()
            return "retry_org_name"
        await update.message.reply_text(f"🎉 Welcome {first_name}! You’ve successfully joined {org_name}.",
                                        reply_markup=ReplyKeyboardRemove())
        # await update.message.reply_text(f"✅ You’ve successfully joined *{org_name}*!", parse_mode="Markdown")

        cursor.execute("""
            INSERT INTO users (user_id, username, org, first_name, last_name)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                org=excluded.org,
                first_name=excluded.first_name,
                surname=excluded.surname
        """, (user_id, username, org_name, first_name, surname))

    conn.commit()
    conn.close()
    # await update.message.reply_text("🎉 You’re all set! Use ▶️ Start to access the main menu.")
    return "onboarding_complete"


# === Cancel flow ===
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Setup cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# === MAIN APP ===
def main():
    init_db()
    import os
    from dotenv import load_dotenv
    load_dotenv()
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ORG_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, org_choice)],
            ORG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, org_name)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("resetonboarding", reset_onboarding))
    app.run_polling()


if __name__ == "__main__":
    main()
