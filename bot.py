import os
import re
import logging
import datetime
import threading
import asyncio
from flask import Flask
from pymongo import MongoClient
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── config ──────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ.get("BOT_TOKEN")
CHANNEL_ID  = os.environ.get("CHANNEL_ID")
MONGO_URI   = os.environ.get("MONGO_URI")

# ── database setup ──────────────────────────────────────────────────────────
client = MongoClient(MONGO_URI)
db = client["poem_database"]
collection = db["index_data"]

# ── web server disguise ─────────────────────────────────────────────────────
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is alive and monitoring the channel!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# ── helpers ──────────────────────────────────────────────────────────────────
def load_index() -> dict:
    data = collection.find_one({"_id": "main_index"})
    if data:
        return data
    return {"_id": "main_index", "message_id": None, "poems": []}

def save_index(data: dict):
    collection.update_one({"_id": "main_index"}, {"$set": data}, upsert=True)

def parse_poem(text: str) -> dict | None:
    title_m  = re.search(r"#عنوان[:\s]+([^\s#]+)", text)
    poet_m   = re.search(r"#شاعر[:\s]+([^\s#]+)", text)
    tags_raw = re.findall(r"#وسم[:\s]+([^\s#]+)", text)

    if not (title_m and poet_m):
        return None

    title = title_m.group(1).replace("_", " ")
    poet  = poet_m.group(1).replace("_", " ")
    tags  = []
    for t in tags_raw:
        tags.extend(re.split(r"[،,]", t))
    tags = [t.replace("_", " ").strip() for t in tags if t.strip()]

    return {"title": title, "poet": poet, "tags": tags}

def build_index_text(poems: list) -> str:
    if not poems:
        return "📚 *فهرس القصائد*\n\n_لم تُضَف قصائد بعد._"

    lines = ["📚 *فهرس القصائد*\n"]
    for i, p in enumerate(poems, 1):
        tags_str = " · ".join(f"#{t}" for t in p["tags"]) if p["tags"] else ""
        link     = f"[{p['title']}]({p['link']})" if p.get("link") else p["title"]
        line     = f"{i}. {link} — _{p['poet']}_"
        if tags_str:
            line += f"\n    {tags_str}"
        lines.append(line)

    lines.append(f"\n_آخر تحديث: {datetime.datetime.now().strftime('%Y-%m-%d')}_")
    return "\n".join(lines)

# ── handler ───────────────────────────────────────────────────────────────────
async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post
    if not msg or not msg.text:
        return

    if str(msg.chat.id) != str(CHANNEL_ID):
        return

    poem = parse_poem(msg.text)
    if not poem:
        return

    poem["link"] = f"https://t.me/c/{str(CHANNEL_ID).replace('-100', '')}/{msg.message_id}"

    data = load_index()
    data["poems"].append(poem)
    save_index(data)

    index_text = build_index_text(data["poems"])

    try:
        if data["message_id"]:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=data["message_id"],
                text=index_text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
        else:
            sent = await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=index_text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            data["message_id"] = sent.message_id
            save_index(data)
            await context.bot.pin_chat_message(
                chat_id=CHANNEL_ID,
                message_id=sent.message_id,
                disable_notification=True,
            )
    except Exception as e:
        logger.error(f"Failed to update index: {e}")

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    # Start the web server in the background
    threading.Thread(target=run_web, daemon=True).start()

    # Create a new event loop for the Telegram bot
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Start the bot
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, on_channel_post))
    logger.info("Bot and Web Server are running…")
    app.run_polling(allowed_updates=["channel_post"])

if __name__ == "__main__":
    main()
