import os
import sqlite3
from dotenv import load_dotenv
from functools import lru_cache
from telegram import Update
from telegram.ext import ContextTypes

from settings import DEV_USER_IDS, get_db_connection, pool

load_dotenv()

# === USER ROLES ===
@lru_cache(maxsize=256)
def get_user_roles_cache(user_id: int) -> dict:
    """Sync cache wrapper for roles per user_id (combined across orgs)."""
    # Placeholder, real DB fetch is async
    return {"admin": False, "executive": False, "user": False, "none": True}


async def get_user_roles(user_id: int) -> dict:
    """
    Fetch a user's roles across organizations.
    Returns a dict with boolean flags: admin, executive, user, none.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT admin, executive
            FROM user_orgs
            WHERE user_id = $1
            """,
            user_id,
        )

    roles = {"admin": False, "executive": False, "user": False, "none": True}

    if rows:
        roles["admin"] = any(row["admin"] for row in rows)
        roles["executive"] = any(row["executive"] for row in rows)
        roles["user"] = not (roles["admin"] or roles["executive"])
        roles["none"] = False

    return roles


def clear_user_roles_cache(user_id: int = None):
    """Clear cached roles for one user or all users."""
    get_user_roles_cache.cache_clear()


async def promote_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Promote a user to admin or executive for a specific org."""
    actor_id = update.effective_user.id
    roles = await get_user_roles(actor_id)
    if not (roles["admin"] or roles["executive"] or actor_id in DEV_USER_IDS):
        await update.message.reply_text("🚫 You are not allowed to run this command.")
        return

    try:
        target_id = int(context.args[0])
        role = context.args[1].lower()
        org_id = int(context.args[2])  # specify org for promotion
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /promote <user_id> <admin|executive> <org_id>")
        return

    async with pool.acquire() as conn:
        if role == "admin":
            await conn.execute(
                "UPDATE user_orgs SET admin = TRUE WHERE user_id = $1 AND org_id = $2",
                target_id, org_id
            )
        elif role == "executive":
            await conn.execute(
                "UPDATE user_orgs SET executive = TRUE WHERE user_id = $1 AND org_id = $2",
                target_id, org_id
            )
        else:
            await update.message.reply_text("Role must be 'admin' or 'executive'.")
            return

        row = await conn.fetchrow(
            "SELECT u.first_name, u.surname FROM users u WHERE u.user_id = $1", target_id
        )

    clear_user_roles_cache(target_id)

    full_name = f"{row['first_name']} {row['surname']}" if row else f"User {target_id}"
    await update.message.reply_text(f"✅ {full_name} promoted to {role} in org {org_id}.")


async def demote_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Demote a user from admin or executive for a specific org."""
    actor_id = update.effective_user.id
    roles = await get_user_roles(actor_id)
    if not (roles["admin"] or roles["executive"] or actor_id in DEV_USER_IDS):
        await update.message.reply_text("🚫 You are not allowed to run this command.")
        return

    try:
        target_id = int(context.args[0])
        role = context.args[1].lower()
        org_id = int(context.args[2])  # specify org
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /demote <user_id> <admin|executive> <org_id>")
        return

    async with pool.acquire() as conn:
        if role == "admin":
            await conn.execute(
                "UPDATE user_orgs SET admin = FALSE WHERE user_id = $1 AND org_id = $2",
                target_id, org_id
            )
        elif role == "executive":
            await conn.execute(
                "UPDATE user_orgs SET executive = FALSE WHERE user_id = $1 AND org_id = $2",
                target_id, org_id
            )
        else:
            await update.message.reply_text("Role must be 'admin' or 'executive'.")
            return

        row = await conn.fetchrow(
            "SELECT u.first_name, u.surname FROM users u WHERE u.user_id = $1", target_id
        )

    clear_user_roles_cache(target_id)

    full_name = f"{row['first_name']} {row['surname']}" if row else f"User {target_id}"
    await update.message.reply_text(f"✅ {full_name} demoted from {role} in org {org_id}.")


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

    async with pool.acquire() as conn:
        # Delete from user_orgs first (cascade optional, but explicit is safer)
        await conn.execute(
            "DELETE FROM user_orgs WHERE user_id = $1", target_id
        )

        # Delete updates
        await conn.execute(
            "DELETE FROM updates WHERE user_id = $1", target_id
        )

        # Delete visits (optional)
        await conn.execute(
            "DELETE FROM visits WHERE user_id = $1", target_id
        )

        # Delete user record
        result = await conn.execute(
            "DELETE FROM users WHERE user_id = $1", target_id
        )

    # Clear cached roles
    clear_user_roles_cache(target_id)

    if result.endswith("0"):
        await update.message.reply_text(f"ℹ️ No user with ID {target_id} was found in the database.")
    else:
        await update.message.reply_text(
            f"✅ User {target_id} has been reset. They’ll go through onboarding again at /start."
        )

def main():
    pass