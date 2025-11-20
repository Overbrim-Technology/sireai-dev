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


# === DB INIT ===
# === Start onboarding ===
ORG_CHOICE, ORG_NAME, FIRST_NAME, SURNAME = range(4)
# First screen
START_KEYBOARD = ReplyKeyboardMarkup([["▶️ Start"]], resize_keyboard=True, one_time_keyboard=False)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome! I am SireAI \n" \
        "Before we begin, let's get you set up.\n\n"
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

    # === Handle follow-up actions after retry ===
    if org_name.lower().startswith("join existing"):
        context.user_data["choice"] = "join"
        await update.message.reply_text(
            "🔁 Great! Please enter the name of the organization you'd like to join:",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
        return "retry_org_name"

    elif org_name.lower().startswith("create new"):
        context.user_data["choice"] = "create"
        await update.message.reply_text(
            "✨ Awesome! Please enter a new unique name for your organization:",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
        return "retry_org_name"

    elif org_name.lower().startswith("try again"):
        await update.message.reply_text(
            "🔁 Please re-enter the correct organization name:",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
        return "retry_org_name"

    # === Asyncpg connection pool (assumes `pool` is global or passed in context) ===
    async with pool.acquire() as conn:
        if choice == "create":
            try:
                # Insert new organization
                await conn.execute(
                    "INSERT INTO organizations (name) VALUES ($1) ON CONFLICT DO NOTHING",
                    org_name
                )
                await update.message.reply_text(
                    f"✅ Organization <b>{org_name}</b> created successfully!",
                    parse_mode="HTML",
                    reply_markup=ReplyKeyboardRemove()
                )
            except Exception as e:
                await update.message.reply_text(
                    f"⚠️ Could not create organization <b>{org_name}</b>. Try a different name.",
                    parse_mode="HTML"
                )
                return "retry_org_name"

            # Add user to this org and mark as executive + admin
            await conn.execute(
                """
                INSERT INTO user_orgs (user_id, org_name, executive, admin)
                VALUES ($1, $2, TRUE, TRUE)
                ON CONFLICT (user_id, org_name) DO NOTHING
                """,
                user_id, org_name
            )

        elif choice == "join":
            org_record = await conn.fetchrow(
                "SELECT id FROM organizations WHERE name=$1", org_name
            )
            if not org_record:
                await update.message.reply_text(
                    "⚠️ Organization not found. Please check the name or create a new one.",
                    parse_mode="HTML",
                    reply_markup=ReplyKeyboardMarkup(
                        [["Try Again", "Create New Organization"]],
                        resize_keyboard=True
                    )
                )
                return "retry_org_name"

            await update.message.reply_text(
                f"🎉 Welcome {first_name}! You’ve successfully joined <b>{org_name}</b>.",
                parse_mode="HTML",
                reply_markup=ReplyKeyboardRemove()
            )

            # Add user to the org
            await conn.execute(
                """
                INSERT INTO user_orgs (user_id, org_name, executive, admin)
                VALUES ($1, $2, FALSE, FALSE)
                ON CONFLICT (user_id, org_name) DO NOTHING
                """,
                user_id, org_name
            )

        # Upsert user general info into users table
        await conn.execute(
            """
            INSERT INTO users (user_id, username, first_name, surname)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id) DO UPDATE SET
                username=EXCLUDED.username,
                first_name=EXCLUDED.first_name,
                surname=EXCLUDED.surname
            """,
            user_id, username, first_name, surname
        )

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
