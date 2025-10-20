import os
import sqlite3
from dotenv import load_dotenv
from functools import lru_cache
from telegram import Update
from telegram.ext import ContextTypes


load_dotenv()
DB_PATH = "work_updates.db"
DEV_USER_IDS = [int(x) for x in os.getenv("DEV_USER_IDS", "").split(",") if x]

# === USER ROLES ===
@lru_cache(maxsize=256)  # cache results for up to 256 different user_ids
def get_user_roles(user_id: int) -> dict:
    """
    Fetch a user's roles from the database (cached).
    Returns a dict with boolean flags for all roles: admin, exec, user, none.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT admin, executive FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    roles = {"admin": False, "executive": False, "user": False, "none": False}

    if row:
        roles["admin"] = bool(row[0])
        roles["executive"] = bool(row[1])
        roles["user"] = not (roles["admin"] or roles["executive"])
    else:
        roles["none"] = True
    return roles

def clear_user_roles_cache(user_id: int = None):
    """
    Clear the cached roles for a single user or all users.
    Use this after updating a user's roles in the DB.
    """
    if user_id is None:
        get_user_roles.cache_clear()
    else:
        get_user_roles.cache_clear()  # lru_cache doesn’t allow fine-grained clear
        # Alternative: reload just this user after role change if needed


async def promote_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Promote a user to admin or exec (developer-only)."""
    user_id = update.effective_user.id
    print(user_id)
    print(DEV_USER_IDS)
    if not (get_user_roles(user_id)["admin"] or 
    get_user_roles(user_id)["executive"] or
    user_id in DEV_USER_IDS):  # only dev/admin can run
        await update.message.reply_text("🚫 You are not allowed to run this command.")
        return

    try:
        target_id = int(context.args[0])
        role = context.args[1].lower()
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /promote <user_id> <admin|executive>")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if role == "admin":
        cursor.execute("UPDATE users SET admin=1 WHERE user_id=?", (target_id,))
    elif role == "executive":
        cursor.execute("UPDATE users SET executive=1 WHERE user_id=?", (target_id,))
    else:
        await update.message.reply_text("Role must be 'admin' or 'executive'.")
        conn.close()
        return

    # Get updated user info
    cursor.execute("SELECT first_name, surname FROM users WHERE user_id=?", (target_id,))
    row = cursor.fetchone()
    conn.commit()
    conn.close()

    # Clear cache
    clear_user_roles_cache(user_id=target_id)

    if row:
        full_name = f"{row[0]} {row[1]}".strip()
    else:
        full_name = f"User {target_id}"

    await update.message.reply_text(f"✅ {full_name} promoted to {role}.")


async def demote_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Demote a user (remove admin/executive flags)."""
    user_id = update.effective_user.id
    if not (get_user_roles(user_id)["admin"] or 
    get_user_roles(user_id)["executive"] or
    user_id in DEV_USER_IDS):  # only dev/admin can run
        await update.message.reply_text("🚫 You are not allowed to run this command.")
        return

    try:
        target_id = int(context.args[0])
        role = context.args[1].lower()
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /demote <user_id> <admin|executive>")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if role == "admin":
        cursor.execute("UPDATE users SET admin=0 WHERE user_id=?", (target_id,))
    elif role == "executive":
        cursor.execute("UPDATE users SET executive=0 WHERE user_id=?", (target_id,))
    else:
        await update.message.reply_text("Role must be 'admin' or 'executive'.")
        conn.close()
        return

    # Get updated user info
    cursor.execute("SELECT first_name, surname FROM users WHERE user_id=?", (target_id,))
    row = cursor.fetchone()
    conn.commit()
    conn.close()

    # Clear cache
    clear_user_roles_cache(user_id=target_id)

    if row:
        full_name = f"{row[0]} {row[1]}".strip()
    else:
        full_name = f"User {target_id}"

    await update.message.reply_text(f"✅ {full_name} demoted from {role}.")

# === Developer-only reset command ===
async def reset_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    # ✅ Ensure only developer(s) can use this
    if user_id not in DEV_USER_IDS:
        await update.message.reply_text("🚫 You are not authorized to reset onboarding.")
        return

    # Expect /resetonboarding <target_user_id>
    if not context.args:
        await update.message.reply_text("⚠️ Usage: /resetonboarding <user_id>")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ Invalid user_id format. Must be a number.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Delete user record
    cursor.execute("DELETE FROM users WHERE user_id=?", (target_id,))
    deleted = cursor.rowcount

    # Optional: also clear their updates
    cursor.execute("DELETE FROM updates WHERE user_id=?", (target_id,))
    conn.commit()
    conn.close()

    if deleted:
        await update.message.reply_text(
            f"✅ User {target_id} has been reset. They’ll go through onboarding again at /start."
        )
    else:
        await update.message.reply_text(f"ℹ️ No user with ID {target_id} was found in the database.")

def main():
    pass