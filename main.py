import logging
import sqlite3
import os
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

logging.basicConfig(level=logging.INFO)

DB_FILE = "text_directory.db"

# ---------------- INIT ----------------

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_category TEXT NOT NULL,
            clean_category TEXT NOT NULL,
            display_trigger TEXT NOT NULL,
            clean_trigger TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            UNIQUE(clean_trigger)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS category_orders (
            clean_category TEXT PRIMARY KEY,
            sort_weight INTEGER NOT NULL DEFAULT 100
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # Defaults
    cursor.execute("INSERT OR IGNORE INTO bot_settings VALUES ('hub_name','iQOO Neo 10 Hub')")
    cursor.execute("INSERT OR IGNORE INTO bot_settings VALUES ('hub_desc','Tap a trigger to fetch files')")
    cursor.execute("INSERT OR IGNORE INTO bot_settings VALUES ('default_category','Miscellaneous')")

    conn.commit()
    conn.close()


# ---------------- SETTINGS ----------------

def get_setting(key):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT value FROM bot_settings WHERE key=?", (key,))
    r = cur.fetchone()
    conn.close()
    return r[0] if r else ""

def set_setting(key, value):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO bot_settings VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()


# ---------------- NORMALIZE ----------------

def normalize_trigger(text: str) -> str:
    text = text.strip().lower()
    if not text.startswith("#"):
        text = "#" + text
    text = re.sub(r"[^a-z0-9_#]", "", text)
    return text


# ---------------- KEYBOARD ----------------

def get_categories():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        SELECT clean_category
        FROM category_orders
        ORDER BY sort_weight ASC
    """)

    cats = [c[0] for c in cur.fetchall()]
    conn.close()
    return cats


def get_keyboard(trigger: str):
    cats = get_categories()
    kb = []

    for c in cats:
        kb.append([InlineKeyboardButton(f"📁 {c}", callback_data=f"mv|{trigger}|{c}")])

    kb.append([
        InlineKeyboardButton("⭕ Delete", callback_data=f"del|{trigger}"),
        InlineKeyboardButton("❌ Cancel", callback_data=f"cancel|{trigger}")
    ])

    return InlineKeyboardMarkup(kb)


# ---------------- SAVE ----------------

async def save_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message first.")
        return

    arg = " ".join(context.args).strip()
    if not arg:
        await update.message.reply_text("Use /save Category/trigger or /save trigger")
        return

    default_cat = get_setting("default_category")

    if "/" in arg:
        cat, trig = arg.split("/", 1)
    else:
        cat, trig = default_cat, arg

    trig = normalize_trigger(trig)

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        INSERT OR REPLACE INTO notes
        (display_category, clean_category, display_trigger, clean_trigger, message_id, chat_id)
        VALUES (?,?,?,?,?,?)
    """, (
        cat, cat.lower(),
        trig, trig,
        update.message.reply_to_message.message_id,
        update.message.chat_id
    ))

    cur.execute("""
        INSERT OR IGNORE INTO category_orders VALUES (?,100)
    """, (cat.lower(),))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"📥 Saved:\n`{trig}` in {cat}",
        parse_mode="Markdown"
    )


# ---------------- NOTES ----------------

async def notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        SELECT display_category, display_trigger
        FROM notes
        ORDER BY clean_category ASC, clean_trigger ASC
    """)

    rows = cur.fetchall()
    conn.close()

    hub = get_setting("hub_name")
    desc = get_setting("hub_desc")

    text = f"{hub}\n{desc}\n\n"

    current = None
    for cat, trig in rows:
        if cat != current:
            current = cat
            text += f"\n{cat.upper()}\n"
        text += f"• `{trig}`\n"

    await update.message.reply_text(text, parse_mode="Markdown")


# ---------------- TRIGGER FETCH ----------------

async def fetch_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trig = normalize_trigger(update.message.text)

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        SELECT chat_id, message_id
        FROM notes
        WHERE clean_trigger=?
    """, (trig,))

    row = cur.fetchone()
    conn.close()

    if row:
        await context.bot.forward_message(
            chat_id=update.effective_chat.id,
            from_chat_id=row[0],
            message_id=row[1]
        )


# ---------------- CALLBACKS ----------------

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = q.data.split("|")

    if data[0] == "mv":
        _, trig, cat = data
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("""
            UPDATE notes
            SET display_category=?, clean_category=?
            WHERE clean_trigger=?
        """, (cat, cat.lower(), trig))
        conn.commit()
        conn.close()

        await q.edit_message_text(f"Moved {trig} → {cat}")

    elif data[0] == "del":
        trig = data[1]

        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("DELETE FROM notes WHERE clean_trigger=?", (trig,))
        conn.commit()
        conn.close()

        await q.edit_message_text(f"Deleted {trig}")

    elif data[0] == "cancel":
        await q.edit_message_text("Cancelled")


# ---------------- SETTINGS ----------------

async def set_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_setting("hub_name", " ".join(context.args))
    await update.message.reply_text("Updated name")

async def set_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_setting("hub_desc", " ".join(context.args))
    await update.message.reply_text("Updated description")


# ---------------- MAIN ----------------

def main():
    init_db()

    app = Application.builder().token(os.getenv("BOT_TOKEN")).build()

    app.add_handler(CommandHandler("save", save_item))
    app.add_handler(CommandHandler("notes", notes))
    app.add_handler(CommandHandler("name", set_name))
    app.add_handler(CommandHandler("description", set_desc))

    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^#"), fetch_trigger))
    app.add_handler(CallbackQueryHandler(callback))

    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
