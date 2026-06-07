import logging
import sqlite3
import os
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
    cursor.execute(
        "INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('default_category', ?)",
        (DEFAULT_CATEGORY,)
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


def set_setting(key: str, value: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def get_all_categories():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT n.display_category 
        FROM notes n
        ORDER BY (SELECT COALESCE(sort_weight, 100) FROM category_orders WHERE clean_category = n.clean_category) ASC, n.clean_category ASC
    """)
    cats = [row[0] for row in cursor.fetchall()]
    conn.close()
    return cats


def get_move_keyboard(current_trigger: str, action_type: str = "save", current_cat: str = None):
    categories = get_all_categories()
    keyboard = []
    callback_trigger = current_trigger.lstrip('#')

    for cat in categories:
        if action_type == "save" and cat.lower() == DEFAULT_CATEGORY.lower():
            continue
        keyboard.append([InlineKeyboardButton(f"📁 {cat}", callback_data=f"mv_{callback_trigger}|{cat}")])

    if action_type == "save":
        keyboard.append([InlineKeyboardButton("❎ Nope", callback_data=f"kp_{callback_trigger}")])
    else:  # move mode
        keyboard.append([
            InlineKeyboardButton("⭕ Delete", callback_data=f"del_{callback_trigger}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"kp_{callback_trigger}")
        ])

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

            await query.edit_message_text(f"✅ Moved `#{trigger}` to *{new_category}*", parse_mode="Markdown")

        elif data.startswith("del_"):
            trigger = data[4:]
            # Show delete confirmation
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT display_category FROM notes WHERE clean_trigger=?", (f"#{trigger.lower()}",))
            row = cursor.fetchone()
            conn.close()
            cat = row[0] if row else "Unknown"
            await query.edit_message_text(
                f"Do you want to delete `#{trigger}` from *{cat}*?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Yes", callback_data=f"confirm_del_{trigger}")],
                    [InlineKeyboardButton("❎ No", callback_data=f"cancel_del_{trigger}")]
                ]),
                parse_mode="Markdown"
            )

        elif data.startswith("confirm_del_"):
            trigger = data[12:]
            clean_trigger = f"#{trigger.lower()}"
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM notes WHERE clean_trigger=?", (clean_trigger,))
            conn.commit()
            conn.close()
            await query.edit_message_text(f"🗑️ `#{trigger}` has been deleted permanently.", parse_mode="Markdown")

        elif data.startswith("cancel_del_") or data.startswith("kp_"):
            await query.edit_message_text("✅ Action cancelled.", parse_mode="Markdown")

    except Exception as e:
        await query.edit_message_text("❌ Error processing action.", parse_mode="Markdown")


# ====================== COMMANDS ======================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *iQOO Neo 10 Tech Support Master Hub*\n\n"
        "📌 *Available Commands:*\n"
        "• `/start` — Show this help\n"
        "• `/notes` — Show all saved items with clickable hashtags\n"
        "• `/save <Trigger>` or `/save <Category/Trigger>` — Save replied message\n"
        "• `/rm <Trigger>` or `/rm <Category/Trigger>` — Delete item\n"
        "• `/mv <Trigger>` — Move item\n"
        "• `/default <Category>` — Change default category\n"
        "• `/name <Title>` — Change hub title\n"
        "• `/description <Text>` — Change description\n"
        "• `/order <Category/Number>` — Change category order\n\n"
        "Send any saved `#hashtag` to get the file instantly."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def set_default_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_default = " ".join(context.args).strip()
    if not new_default:
        await update.message.reply_text("❌ Format: `/default <Category Name>`", parse_mode="Markdown")
        return
    set_setting("default_category", new_default)
    await update.message.reply_text(f"✅ Default category updated to *{new_default}*", parse_mode="Markdown")


async def set_hub_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = " ".join(context.args).strip()
    if not new_name:
        await update.message.reply_text("❌ Format: `/name <New Title>`", parse_mode="Markdown")
        return
    set_setting("hub_name", new_name)
    await update.message.reply_text(f"⚙️ Hub title updated to:\n`{new_name}`", parse_mode="Markdown")


async def set_hub_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_desc = " ".join(context.args).strip()
    if not new_desc:
        await update.message.reply_text("❌ Format: `/description <Text>`", parse_mode="Markdown")
        return
    set_setting("hub_desc", new_desc)
    await update.message.reply_text(f"⚙️ Description updated.", parse_mode="Markdown")


async def save_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to a message or file to save!", parse_mode="Markdown")
        return

    raw_path = " ".join(context.args).strip()
    if not raw_path:
        await update.message.reply_text("❌ Format: `/save <Trigger>` or `/save <Category/Trigger>`", parse_mode="Markdown")
        return

    is_path = "/" in raw_path
    if is_path:
        try:
            category, trigger = raw_path.split("/", 1)
            display_category = category.strip()
            display_trigger = trigger.strip()
        except ValueError:
            await update.message.reply_text("❌ Wrong format. Use `Category/Trigger`", parse_mode="Markdown")
            return
    else:
        display_category = get_setting("default_category") or DEFAULT_CATEGORY
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
        # Show move menu
        reply_markup = get_move_keyboard(display_trigger, "save")
        await update.message.reply_text(
            f"`{display_trigger}` is saved in *{display_category}*!\n\n"
            f"Do you want to change category of `{display_trigger}`?",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"✅ Saved `{display_trigger}` in *{display_category}*!", parse_mode="Markdown")


async def master_notes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT n.display_category, n.display_trigger
        FROM notes n
        LEFT JOIN category_orders o ON n.clean_category = o.clean_category
        ORDER BY COALESCE(o.sort_weight, 100) ASC, n.clean_category ASC, n.clean_trigger ASC
    """)
    data = cursor.fetchall()
    conn.close()

    current_name = get_setting("hub_name")
    current_desc = get_setting("hub_desc")

    if not data:
        await update.message.reply_text(f"🤖 **{current_name}**\n{current_desc}\n\nNo items yet.", parse_mode="Markdown")
        return

    text = f"🤖 **{current_name}**\n{current_desc}\n\n"
    current_cat = None
    for category, trigger in data:
        if category != current_cat:
            current_cat = category
            text += f"🌟 **{category.upper()}**\n"
        text += f"{trigger}\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def move_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = " ".join(context.args).strip()
    if not raw:
        await update.message.reply_text("❌ Format: `/mv <Trigger>`", parse_mode="Markdown")
        return

    display_trigger = raw if raw.startswith("#") else f"#{raw}"
    clean_trigger = display_trigger.lower()

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT display_category FROM notes WHERE clean_trigger=?", (clean_trigger,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await update.message.reply_text(f"❌ `{display_trigger}` not found.", parse_mode="Markdown")
        return

    current_cat = row[0]
    reply_markup = get_move_keyboard(display_trigger, "move", current_cat)
    await update.message.reply_text(
        f"Change `{display_trigger}` from *{current_cat}*",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


async def remove_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_path = " ".join(context.args).strip()
    if not raw_path:
        await update.message.reply_text("❌ Format: `/rm <Trigger>` or `/rm <Category/Trigger>`", parse_mode="Markdown")
        return

    if "/" in raw_path:
        try:
            cat, trig = raw_path.split("/", 1)
            clean_trigger = f"#{trig.strip().lower()}"
        except:
            await update.message.reply_text("❌ Wrong format.", parse_mode="Markdown")
            return
    else:
        clean_trigger = f"#{raw_path.strip().lower()}"

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT display_category FROM notes WHERE clean_trigger=?", (clean_trigger,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await update.message.reply_text("❌ Item not found.", parse_mode="Markdown")
        return

    cat = row[0]
    trigger = clean_trigger[1:]
    await update.message.reply_text(
        f"Do you want to delete `#{trigger}` from *{cat}*?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes", callback_data=f"confirm_del_{trigger}")],
            [InlineKeyboardButton("❎ No", callback_data="cancel_del")]
        ]),
        parse_mode="Markdown"
    )


# ====================== HASHTAG FETCHER ======================
async def global_hashtag_fetcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if not text.startswith("#"):
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT message_id, chat_id FROM notes WHERE clean_trigger=?", (text,))
    result = cursor.fetchone()
    conn.close()

    if result:
        msg_id, chat_id = result
        await context.bot.forward_message(
            chat_id=update.message.chat_id,
            from_chat_id=chat_id,
            message_id=msg_id
        )


# ====================== MAIN ======================
def main():
    init_db()
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable is not set!")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("notes", master_notes_command))
    app.add_handler(CommandHandler("save", save_item))
    app.add_handler(CommandHandler("mv", move_item))
    app.add_handler(CommandHandler("rm", remove_item))
    app.add_handler(CommandHandler("name", set_hub_name))
    app.add_handler(CommandHandler("description", set_hub_description))
    app.add_handler(CommandHandler("default", set_default_category))

    app.add_handler(CallbackQueryHandler(process_callback_moves))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^#"), global_hashtag_fetcher))

    print("🤖 Bot started successfully!")
    app.run_polling()


if __name__ == "__main__":
    main()
