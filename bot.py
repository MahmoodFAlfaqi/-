import os
import json
import re
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── config ──────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ["BOT_TOKEN"]
CHANNEL_ID  = os.environ["CHANNEL_ID"]          # e.g. -1001234567890
INDEX_FILE  = "index.json"

# ── helpers ──────────────────────────────────────────────────────────────────
def load_index() -> dict:
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"message_id": None, "poems": []}

def save_index(data: dict):
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def parse_poem(text: str) -> dict | None:
    """
    Expected format anywhere in the message:
        #عنوان:اسم_القصيدة  #شاعر:اسم_الشاعر  #وسم:وسم1،وسم2
    Tags separator can be comma or Arabic comma.
    Returns None if any required field is missing.
    """
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
    """Builds the Arabic index message."""
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

    lines.append(f"\n_آخر تحديث: {__import__('datetime').datetime.now().strftime('%Y-%m-%d')}_")
    return "\n".join(lines)

# ── handler ───────────────────────────────────────────────────────────────────
async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post
    if not msg or not msg.text:
        return

    # Only act on messages from our channel
    if str(msg.chat.id) != str(CHANNEL_ID):
        return

    poem = parse_poem(msg.text)
    if not poem:
        return  # message has no poem metadata — ignore silently

    poem["link"] = f"https://t.me/c/{str(CHANNEL_ID).replace('-100', '')}/{msg.message_id}"

    data = load_index()
    data["poems"].append(poem)
    save_index(data)

    index_text = build_index_text(data["poems"])

    try:
        if data["message_id"]:
            # Update existing index message
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=data["message_id"],
                text=index_text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            logger.info(f"Index updated — now {len(data['poems'])} poem(s).")
        else:
            # First time: send a new message and pin it
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
            logger.info("Index message created and pinned.")
    except Exception as e:
        logger.error(f"Failed to update index: {e}")

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, on_channel_post))
    logger.info("Bot is running…")
    app.run_polling(allowed_updates=["channel_post"])

if __name__ == "__main__":
    main()
