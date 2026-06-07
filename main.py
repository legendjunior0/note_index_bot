import os
import re
import sqlite3
import logging
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# ================= LOGGING =================
logging.basicConfig(level=logging.INFO)

# ================= FASTAPI =================
app = FastAPI()

# ================= CONFIG =================
DB_FILE = "notes.db"

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://your-app.onrender.com

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing")

# ================= GLOBAL BOT =================
application: Application | None = None


# ================= NORMALIZER =================
def norm(text: str) -> str:
    """
    Makes triggers:
    - case insensitive
    - removes spaces
    - removes underscores
    - keeps alphanumeric only
    """
    return "#" + re.sub(r"[^a-z0-9]", "", text.lower())


# ================= DB =================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT,
        clean_category TEXT,
        trigger TEXT,
        clean_trigger TEXT UNIQUE,
        chat_id INTEGER,
        message_id INTEGER
    )
    """)

    conn.commit()
    conn.close()


def db_save(category, trigger, chat_id, message_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
    INSERT OR REPLACE INTO notes
    (category, clean_category, trigger, clean_trigger, chat_id, message_id)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        category,
        category.lower(),
        trigger,
        norm(trigger),
        chat_id,
        message_id
    ))

    conn.commit()
    conn.close()


def db_get(trigger):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT chat_id, message_id FROM notes WHERE clean_trigger=?", (norm(trigger),))
    row = cur.fetchone()
    conn.close()
    return row


# ================= COMMANDS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is running 🚀")


async def save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to save it.")
        return

    args = " ".join(context.args)

    if "/" in args:
        category, trigger = args.split("/", 1)
    else:
        category = "Misc"
        trigger = args

    trigger = trigger.strip()
    category = category.strip()

    db_save(
        category,
        trigger,
        update.message.chat_id,
        update.message.reply_to_message.message_id
    )

    await update.message.reply_text(f"Saved: {trigger}")


async def notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("SELECT category, trigger FROM notes ORDER BY category")
    rows = cur.fetchall()
    conn.close()

    text = "📌 NOTES\n\n"
    current = None

    for cat, trig in rows:
        if cat != current:
            current = cat
            text += f"\n📁 {cat.upper()}\n"
        text += f"• `{trig}`\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def fetch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    row = db_get(text)

    if row:
        chat_id, msg_id = row
        await context.bot.forward_message(
            chat_id=update.effective_chat.id,
            from_chat_id=chat_id,
            message_id=msg_id
        )


async def cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Action done")


# ================= WEBHOOK =================

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.update_queue.put(update)
    return {"ok": True}


@app.get("/health")
async def health():
    return {"status": "alive"}


# ================= STARTUP =================

@app.on_event("startup")
async def startup():
    global application

    init_db()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("save", save))
    application.add_handler(CommandHandler("notes", notes))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^#"), fetch))
    application.add_handler(CallbackQueryHandler(cb))

    await application.initialize()
    await application.start()

    await application.bot.set_webhook(f"{WEBHOOK_URL}/webhook")

    logging.info("Bot started successfully")


@app.on_event("shutdown")
async def shutdown():
    await application.stop()
    await application.shutdown()
