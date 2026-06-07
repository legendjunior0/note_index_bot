import os
import re
import sqlite3
import unicodedata
import logging
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
DB_FILE = "text_directory.db"

if not BOT_TOKEN or not WEBHOOK_URL:
    raise Exception("BOT_TOKEN or WEBHOOK_URL missing")

# ================= INIT =================

app = FastAPI()
application = Application.builder().token(BOT_TOKEN).build()
bot = application.bot

logging.basicConfig(level=logging.INFO)

# ================= DATABASE =================

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        display_category TEXT,
        clean_category TEXT,
        display_trigger TEXT,
        clean_trigger TEXT UNIQUE,
        message_id INTEGER,
        chat_id INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS bot_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    cur.execute("INSERT OR IGNORE INTO bot_settings VALUES ('hub_name','Notes Hub')")
    cur.execute("INSERT OR IGNORE INTO bot_settings VALUES ('hub_desc','Send #trigger to fetch notes')")
    cur.execute("INSERT OR IGNORE INTO bot_settings VALUES ('default_category','Miscellaneous')")

    conn.commit()
    conn.close()

# ================= NORMALIZER (CRITICAL FIX) =================

def norm(text: str) -> str:
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)
    text = text.strip().lower()

    if text.startswith("#"):
        text = text[1:]

    # unify spaces, underscores, hyphens
    text = re.sub(r"[\s\-]+", "_", text)

    # remove invalid chars
    text = re.sub(r"[^a-z0-9_]", "", text)

    # collapse underscores
    text = re.sub(r"_+", "_", text)

    return "#" + text


# ================= SETTINGS =================

def get_setting(key: str):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT value FROM bot_settings WHERE key=?", (key,))
    r = cur.fetchone()
    conn.close()
    return r[0] if r else ""


# ================= COMMANDS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot is running")


async def save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to a message first")

    raw = " ".join(context.args).strip()

    if "/" in raw:
        cat, trig = raw.split("/", 1)
    else:
        cat = get_setting("default_category")
        trig = raw

    clean = norm(trig)

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
    INSERT OR REPLACE INTO notes
    (display_category, clean_category, display_trigger, clean_trigger, message_id, chat_id)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        cat,
        cat.lower(),
        trig,
        clean,
        update.message.reply_to_message.message_id,
        update.message.chat_id
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(f"📥 Saved {clean}")


# ================= NOTES LIST =================

async def notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
    SELECT display_category, display_trigger
    FROM notes
    ORDER BY clean_category, clean_trigger
    """)

    rows = cur.fetchall()
    conn.close()

    text = f"🤖 {get_setting('hub_name')}\n\n"

    current = None
    for cat, trig in rows:
        if cat != current:
            current = cat
            text += f"\n📁 {cat.upper()}\n"
        text += f"• `{trig}`\n"

    await update.message.reply_text(text)


# ================= FETCH (FIXED MULTI-WORD SUPPORT) =================

async def fetch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if not text.startswith("#"):
        return

    trigger = norm(text)

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
    SELECT chat_id, message_id
    FROM notes
    WHERE clean_trigger=?
    """, (trigger,))

    row = cur.fetchone()
    conn.close()

    if row:
        from_chat, msg_id = row

        await context.bot.forward_message(
            chat_id=update.effective_chat.id,
            from_chat_id=from_chat,
            message_id=msg_id
        )


# ================= CALLBACK (BASIC) =================

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Action received")


# ================= HANDLERS =================

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("save", save))
application.add_handler(CommandHandler("notes", notes))
application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^#"), fetch))
application.add_handler(CallbackQueryHandler(callback))


# ================= WEBHOOK =================

@app.get("/health")
async def health():
    return {"status": "alive"}


@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot)

    await application.process_update(update)

    return {"ok": True}


# ================= STARTUP =================

@app.on_event("startup")
async def startup():
    init_db()

    await application.initialize()
    await application.start()

    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")


@app.on_event("shutdown")
async def shutdown():
    await application.stop()
    await application.shutdown()
