import logging
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

DB_FILE = "text_directory.db"
DEFAULT_CATEGORY = "Miscellaneous"


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
            UNIQUE(clean_category, clean_trigger)
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

    # Default values
    cursor.execute(
        "INSERT OR IGNORE INTO category_orders (clean_category, sort_weight) VALUES (?, ?)",
        (DEFAULT_CATEGORY.lower(), 99)
    )
    cursor.execute(
        "INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('hub_name', 'iQOO Neo 10 Tech Support Master Hub')"
    )
    cursor.execute(
        "INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('hub_desc', 'Tap any hashtag trigger below to instantly fetch the file:')"
    )
    
    conn.commit()
    conn.close()


def get_setting(key: str) -> str:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_settings WHERE key=?", (key,))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else ""


def get_move_keyboard(current_trigger: str, action_type: str = "save"):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT n.display_category, COALESCE(o.sort_weight, 100) as weight
        FROM notes n
        LEFT JOIN category_orders o ON n.clean_category = o.clean_category
        ORDER BY weight ASC, n.clean_category ASC
    """)
    categories = [row[0] for row in cursor.fetchall()]
    conn.close()

    keyboard = []
    callback_trigger = current_trigger.lstrip('#')

    for cat in categories:
        if action_type == "save" and cat.lower() == DEFAULT_CATEGORY.lower():
            continue
        keyboard.append([InlineKeyboardButton(f"📁 {cat}", callback_data=f"mv_{callback_trigger}|{cat}")])

    cancel_label = "❌ No (Keep in Misc)" if action_type == "save" else "❌ Cancel Move"
    keyboard.append([InlineKeyboardButton(cancel_label, callback_data=f"kp_{callback_trigger}")])

    return InlineKeyboardMarkup(keyboard)


async def auto_delete_menu(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try:
        await context.bot.delete_message(chat_id=job.chat_id, message_id=job.data)
    except Exception:
        pass


async def process_callback_moves(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    try:
        if data.startswith("mv_"):
            # Format: mv_trigger|NewCategory
            parts = data[3:].split("|", 1)
            trigger = parts[0]
            new_category = parts[1] if len(parts) > 1 else ""

            clean_trigger = f"#{trigger.lower()}"

            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE notes SET display_category=?, clean_category=? WHERE clean_trigger=?",
                (new_category, new_category.lower(), clean_trigger)
            )
            conn.commit()
            conn.close()

            await query.edit_message_text(
                f"✅ Moved `#{trigger}` to *{new_category}* successfully!",
                parse_mode="Markdown"
            )

        elif data.startswith("kp_"):
            await query.edit_message_text("✅ Kept in current category.", parse_mode="Markdown")
    except Exception as e:
        await query.edit_message_text(f"❌ Error: {str(e)}", parse_mode="Markdown")


# ====================== ADMIN COMMANDS ======================

async def set_hub_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = " ".join(context.args).strip()
    if not new_name:
        await update.message.reply_text("❌ Format: `/name New Hub Title`", parse_mode="Markdown")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES ('hub_name', ?)", (new_name,))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"⚙️ *Hub Title Updated!*\n`{new_name}`", parse_mode="Markdown")


async def set_hub_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_desc = " ".join(context.args).strip()
    if not new_desc:
        await update.message.reply_text("❌ Format: `/description New description text`", parse_mode="Markdown")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES ('hub_desc', ?)", (new_desc,))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"⚙️ *Hub Description Updated!*\n`{new_desc}`", parse_mode="Markdown")


async def save_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to the message/file you want to save!", parse_mode="Markdown")
        return

    raw_path = " ".join(context.args).strip()
    if not raw_path:
        await update.message.reply_text("❌ Format: `/save Category/Trigger` or `/save Trigger`", parse_mode="Markdown")
        return

    is_path = "/" in raw_path
    if is_path:
        try:
            category, trigger = raw_path.split("/", 1)
            display_category = category.strip()
            display_trigger = trigger.strip()
        except ValueError:
            await update.message.reply_text("❌ Use: `Category/Trigger`", parse_mode="Markdown")
            return
    else:
        display_category = DEFAULT_CATEGORY
        display_trigger = raw_path.strip()

    if not display_trigger.startswith("#"):
        display_trigger = f"#{display_trigger}"

    clean_category = display_category.lower()
    clean_trigger = display_trigger.lower()

    replied_msg_id = update.message.reply_to_message.message_id
    chat_id = update.message.chat_id

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO notes (display_category, clean_category, display_trigger, clean_trigger, message_id, chat_id)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(clean_category, clean_trigger) DO UPDATE SET 
            message_id=excluded.message_id,
            display_category=excluded.display_category
    """, (display_category, clean_category, display_trigger, clean_trigger, replied_msg_id, chat_id))

    cursor.execute(
        "INSERT OR IGNORE INTO category_orders (clean_category, sort_weight) VALUES (?, 100)",
        (clean_category,)
    )
    conn.commit()
    conn.close()

    if not is_path:
        reply_markup = get_move_keyboard(display_trigger, "save")
        menu_msg = await update.message.reply_text(
            f"📥 `{display_trigger}` saved in *{DEFAULT_CATEGORY}*!\n\n❓ Move to another category?",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        context.job_queue.run_once(auto_delete_menu, when=1800, chat_id=chat_id, data=menu_msg.message_id)
    else:
        await update.message.reply_text(f"✅ Saved `{display_trigger}` in *{display_category}*!", parse_mode="Markdown")


async def order_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_args = " ".join(context.args).strip()
    try:
        category, position = raw_args.split("/", 1)
        clean_category = category.strip().lower()
        weight = int(position.strip())
    except (ValueError, TypeError):
        await update.message.reply_text("❌ Format: `/order CategoryName/Number`", parse_mode="Markdown")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO category_orders (clean_category, sort_weight)
        VALUES (?, ?) ON CONFLICT(clean_category) DO UPDATE SET sort_weight=excluded.sort_weight
    """, (clean_category, weight))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"⚙️ *{category.strip()}* order set to `{weight}`", parse_mode="Markdown")


async def move_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_args = " ".join(context.args).strip()
    if not raw_args:
        await update.message.reply_text("❌ Use: `/mv TriggerName`", parse_mode="Markdown")
        return

    display_trigger = raw_args if raw_args.startswith("#") else f"#{raw_args}"
    clean_trigger = display_trigger.lower()

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT display_category FROM notes WHERE clean_trigger=?", (clean_trigger,))
    exists = cursor.fetchone()
    conn.close()

    if not exists:
        await update.message.reply_text(f"❌ `{display_trigger}` not found.", parse_mode="Markdown")
        return

    reply_markup = get_move_keyboard(display_trigger, "move")
    await update.message.reply_text(
        f"🔄 Moving `{display_trigger}`\nChoose new category:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def remove_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_path = " ".join(context.args).strip()
    if not raw_path:
        await update.message.reply_text("❌ Format: `/rm Trigger` or `/rm Category/Trigger`", parse_mode="Markdown")
        return

    if "/" in raw_path:
        try:
            category, trigger = raw_path.split("/", 1)
            clean_category = category.strip().lower()
            clean_trigger = f"#{trigger.strip().lower()}"
        except ValueError:
            await update.message.reply_text("❌ Wrong format.", parse_mode="Markdown")
            return
    else:
        clean_category = DEFAULT_CATEGORY.lower()
        clean_trigger = f"#{raw_path.strip().lower()}"

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM notes WHERE clean_category=? AND clean_trigger=?", (clean_category, clean_trigger))
    deleted = cursor.rowcount

    if deleted and clean_category != DEFAULT_CATEGORY.lower():
        cursor.execute("SELECT COUNT(id) FROM notes WHERE clean_category=?", (clean_category,))
        if cursor.fetchone()[0] == 0:
            cursor.execute("DELETE FROM category_orders WHERE clean_category=?", (clean_category,))

    conn.commit()
    conn.close()

    if deleted:
        await update.message.reply_text("🗑️ Removed successfully.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Item not found.", parse_mode="Markdown")


async def master_notes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT n.display_category, n.display_trigger, COALESCE(o.sort_weight, 100)
        FROM notes n
        LEFT JOIN category_orders o ON n.clean_category = o.clean_category
        ORDER BY COALESCE(o.sort_weight, 100) ASC, n.clean_category ASC, n.clean_trigger ASC
    """)
    data = cursor.fetchall()
    conn.close()

    current_name = get_setting("hub_name")
    current_desc = get_setting("hub_desc")

    if not data:
        await update.message.reply_text(
            f"🤖 {current_name}\n_{current_desc}_\n\nDatabase is empty. Use /save first.",
            parse_mode="Markdown"
        )
        return

    text = f"🤖 {current_name}\n{current_desc}\n"
    current_cat = None
    for category, trigger, _ in data:
        if category != current_cat:
            current_cat = category
            text += f"\n🌟 {current_cat.upper()}\n"
        text += f"• {trigger}\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def global_hashtag_fetcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text or not text.startswith("#"):
        return

    target_trigger = text.strip().lower()

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT message_id, chat_id FROM notes WHERE clean_trigger=?", (target_trigger,))
    result = cursor.fetchone()
    conn.close()

    if result:
        msg_id, chat_id = result
        await context.bot.forward_message(
            chat_id=update.message.chat_id,
            from_chat_id=chat_id,
            message_id=msg_id
        )


def main():
    init_db()
    BOT_TOKEN = "8658991271:AAHz6ZQWxsyFrFbWnr5l_9s2u62jRByvFgk"   # ← CHANGE THIS

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("name", set_hub_name))
    app.add_handler(CommandHandler("description", set_hub_description))
    app.add_handler(CommandHandler("save", save_item))
    app.add_handler(CommandHandler("order", order_category))
    app.add_handler(CommandHandler("mv", move_item))
    app.add_handler(CommandHandler("rm", remove_item))
    app.add_handler(CommandHandler("notes", master_notes_command))

    app.add_handler(CallbackQueryHandler(process_callback_moves))
    app.add_handler(MessageHandler(filters.TEXT & filters.Entity("hashtag"), global_hashtag_fetcher))

    print("🤖 Bot started successfully!")
    app.run_polling()


if __name__ == "__main__":
    main()



