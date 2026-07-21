import os
import re
import html
import logging
import aiohttp
import asyncio
import io
import warnings
import hashlib
import json
import random
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from datetime import datetime
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, PicklePersistence
from telegram.constants import ParseMode

# --- ⚙️ CONFIGURATION & LOGGING ---
load_dotenv()
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants from Environment
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else None

if not BOT_TOKEN or not ADMIN_ID or not GROQ_API_KEY:
    logger.error("Missing required environment variables (BOT_TOKEN, ADMIN_ID, GROQ_API_KEY)")
    exit(1)

# Bot Settings
DB_FILE = "processed_posts.txt"
CHECK_INTERVAL = 300  # 5 minutes

# Channel Configs
PRIMARY_CHANNEL_ID = -1002416411673 # Gyar Nuu
THEINKHA_CHANNEL = "@theinkha007"
KNOWLEDGE_CHANNEL = "@developknowledge007"
EXTRA_CHANNELS = ["@bhonehtetmm", "@maungpn777"]

CHANNEL_CONFIGS = {
    PRIMARY_CHANNEL_ID: {
        "name": "Gyar Nuu (သေသပ်သော သတင်းဟန်)",
        "prompt": (
            "မင်းက ကျွမ်းကျင်တဲ့ သတင်းအယ်ဒီတာတစ်ယောက်ဖြစ်တယ်။ "
            "အောက်ပါ မြန်မာသတင်းစာသားကို အဓိပ္ပာယ် လုံးဝမပျက်စေဘဲ၊ သတင်းအချက်အလက် စုံစုံလင်လင်ဖြင့် "
            "ဖတ်ရတာ ပိုမိုသေသပ်ချောမွေ့ပြီး ခိုင်မာတဲ့ သတင်းဟန်အဖြစ် ပြန်လည်ပြင်ရေးပေးပါ။ "
            "သတင်းခေါင်းစဉ်ကို အပေါ်ဆုံးကနေ စာလုံးအထူ (Bold) ဖြင့် ထားပေးပါ။"
        )
    },
    THEINKHA_CHANNEL: {
        "name": "Theinkha (ပေါ့ပါးသော လူမှုကွန်ရက်ဟန်)",
        "prompt": (
            "မင်းက စာဖတ်သူနဲ့ ရင်းနှီးတဲ့ Social Media Content Creator တစ်ယောက်ဖြစ်တယ်။ "
            "အောက်ပါ သတင်းကို လူမှုကွန်ရက်စာမျက်နှာပေါ်မှာ တင်ဖို့အတွက် ဖတ်ရတာ ပေါ့ပေါ့ပါးပါးနဲ့ "
            "စိတ်ဝင်စားဖို့ကောင်းအောင်၊ သင့်တော်တဲ့ နေရာတွေမှာ အီမိုဂျီ (Emoji) လေးတွေ ထည့်သွင်းပြီး ပြန်လည်ရေးသားပေးပါ။"
        )
    },
    KNOWLEDGE_CHANNEL: {
        "name": "Develop Knowledge (ဗဟုသုတနှင့် သုံးသပ်ချက်ဟန်)",
        "prompt": (
            "မင်းက ဗဟုသုတ မျှဝေသူတစ်ယောက် ဖြစ်တယ်။ အောက်ပါသတင်းကို ဖတ်ရှုသူတွေ အလွယ်တကူ သဘောပေါက်ပြီး "
            "ဗဟုသုတရစေဖို့အတွက် အဓိကအချက်အလက်များကို Bullet points (အစက်အပြောက်များ) ဖြင့် စနစ်တကျ ခွဲခြားပြီး "
            "ဖတ်ရလွယ်ကူအောင် ပြန်လည်ပြင်ရေးပေးပါ။"
        )
    }
}

CHANNELS_TO_SCRAPE = ["popularjournal", "kothetjournalist", "hminewai", "globalnews247", "myanmarupdate", "MyanmarNationalPost"]
RSS_URLS = [
    "https://popularmyanmar.com/feed",
    "https://www.bbc.com/burmese/index.xml",
    "https://www.rfa.org/burmese/rss2.xml",
    "https://news-eleven.com/feed",
    "https://www.nssmy.com/feed"
]

RSSHUB_MIRRORS = ["https://rsshub.rssforever.com", "https://rsshub.app"]
USER_AGENTS = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"]

# --- 💾 DATABASE MANAGER ---
class Database:
    def __init__(self, filename):
        self.filename = filename
        self.processed_posts = self._load()

    def _load(self):
        if not os.path.exists(self.filename): return set()
        try:
            with open(self.filename, "r", encoding="utf-8") as f:
                return set(line.strip() for line in f if line.strip())
        except: return set()

    def is_processed(self, post_id): return post_id in self.processed_posts

    def add(self, post_id):
        if post_id not in self.processed_posts:
            self.processed_posts.add(post_id)
            try:
                with open(self.filename, "a", encoding="utf-8") as f:
                    f.write(f"{post_id}\n")
            except: pass

    def clear(self):
        self.processed_posts.clear()
        if os.path.exists(self.filename):
            try: os.remove(self.filename)
            except: pass

db = Database(DB_FILE)

# --- 🛠 UTILS ---
def make_safe_key(post_id): return hashlib.md5(post_id.encode("utf-8")).hexdigest()[:15]

async def download_image(session, url):
    try:
        async with session.get(url, headers={"User-Agent": random.choice(USER_AGENTS)}, timeout=10) as res:
            if res.status == 200:
                content = await res.read()
                img_io = io.BytesIO(content)
                img_io.name = 'news_image.jpg'
                return img_io
    except: pass
    return None

# --- 🤖 AI ENGINE ---
class AIEngine:
    def __init__(self, api_key):
        self.api_key = api_key
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        self.model_name = "llama-3.3-70b-versatile"

    async def rewrite(self, text, prompt_style):
        prompt = f"{prompt_style}\n\nမူရင်းသတင်းစာသား -\n{text}"
        payload = {"model": self.model_name, "messages": [{"role": "user", "content": prompt}], "temperature": 0.7}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, headers=headers, timeout=30) as response:
                    res_json = await response.json()
                    return res_json["choices"][0]["message"]["content"]
        except: return None

ai_engine = AIEngine(GROQ_API_KEY)

# --- 📰 SCRAPERS ---
class NewsScraper:
    def __init__(self, session): self.session = session

    async def fetch_telegram(self, channel):
        for mirror in RSSHUB_MIRRORS:
            url = f"{mirror}/telegram/channel/{channel}"
            try:
                async with self.session.get(url, timeout=20) as response:
                    if response.status != 200: continue
                    soup = BeautifulSoup(await response.text(), "xml")
                    items = []
                    for item_tag in soup.find_all("item"):
                        guid = item_tag.find("guid") or item_tag.find("link")
                        unique_id = f"tg_{channel}_{hashlib.md5(guid.text.encode()).hexdigest()[:12]}"
                        if db.is_processed(unique_id): continue
                        desc = item_tag.find("description").text
                        desc_soup = BeautifulSoup(desc, "html.parser")
                        img_tag = desc_soup.find("img")
                        image_url = img_tag.get("src") if img_tag else None
                        clean_desc = desc_soup.get_text(separator="\n").strip()
                        clean_desc = re.sub(r'^[\s\n]*(🖼️|🖼|📷|📸|📹|🎥|📽️|🎞️|🎬)[\s\n]*', '', clean_desc)
                        items.append({"id": unique_id, "source": f"Telegram (@{channel})", "summary": clean_desc, "image_url": image_url, "link": item_tag.find("link").text})
                    return items
            except: continue
        return []

    async def fetch_rss(self, url):
        try:
            async with self.session.get(url, timeout=15) as response:
                soup = BeautifulSoup(await response.read(), features="xml")
                items = []
                for item in soup.find_all("item"):
                    guid = item.find("guid") or item.find("link")
                    unique_id = f"rss_{guid.text.strip()}"
                    if db.is_processed(unique_id): continue
                    link = item.find("link").text.strip()
                    title = item.find("title").text.strip()
                    desc = item.find("description").text.strip()
                    clean_desc = BeautifulSoup(desc, "html.parser").get_text().strip()
                    summary = f"<b>{title}</b>\n\n{clean_desc}"
                    
                    # Fetch full content for RSS
                    image_url, full_summary = await self._fetch_full_rss_content(link, url, title, summary)
                    items.append({"id": unique_id, "source": self._get_rss_source_name(url), "summary": full_summary, "image_url": image_url, "link": link})
                return items
        except: return []

    def _get_rss_source_name(self, url):
        if "bbc.com" in url: return "BBC Burmese"
        if "rfa.org" in url: return "RFA Burmese"
        if "popularmyanmar" in url: return "Popular Journal"
        if "news-eleven.com" in url: return "Eleven Media"
        if "nssmy.com" in url: return "NSS Myanmar"
        return "RSS Feed"

    async def _fetch_full_rss_content(self, link, rss_url, title, default_summary):
        image_url, summary = None, default_summary
        try:
            async with self.session.get(link, timeout=6) as res:
                if res.status == 200:
                    soup = BeautifulSoup(await res.text(), "html.parser")
                    og_img = soup.find("meta", property="og:image")
                    if og_img: image_url = og_img.get("content")
                    if any(x in rss_url for x in ["bbc.com", "rfa.org", "popularmyanmar", "news-eleven.com"]):
                        paragraphs = soup.find_all("p")
                        body = [p.get_text().strip() for p in paragraphs[:5] if len(p.get_text().strip()) > 10]
                        if body: summary = f"<b>{title}</b>\n\n" + "\n\n".join(body)
        except: pass
        return image_url, summary

# --- 📩 BOT HANDLERS ---
async def send_to_admin(context, item, session):
    safe_id = make_safe_key(item['id'])
    context.bot_data[f"raw_{safe_id}"] = {"text": item["summary"], "link": item["link"], "image_url": item["image_url"]}
    
    caption = f"<b>Source:</b> {item['source']}\n\n{item['summary'][:800]}..."
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 AI Rewrite (Preview)", callback_data=f"ai_{safe_id}")],
        [InlineKeyboardButton("✍️ Edit Raw", callback_data=f"edit_raw_{safe_id}"), InlineKeyboardButton("✅ Direct Publish All", callback_data=f"pubdirect_{safe_id}")],
        [InlineKeyboardButton("🔴 Discard", callback_data=f"disc_{safe_id}")]
    ])

    if item.get("image_url"):
        img = await download_image(session, item["image_url"])
        if img:
            sent = await context.bot.send_photo(chat_id=ADMIN_ID, photo=img, caption=caption, reply_markup=kb, parse_mode=ParseMode.HTML)
            context.bot_data[f"raw_{safe_id}"]["photo_id"] = sent.photo[-1].file_id
            db.add(item['id'])
            return

    await context.bot.send_message(chat_id=ADMIN_ID, text=caption, reply_markup=kb, parse_mode=ParseMode.HTML)
    db.add(item['id'])

async def check_news_job(context: ContextTypes.DEFAULT_TYPE):
    async with aiohttp.ClientSession() as session:
        scraper = NewsScraper(session)
        for c in CHANNELS_TO_SCRAPE:
            for item in await scraper.fetch_telegram(c): await send_to_admin(context, item, session)
        for u in RSS_URLS:
            for item in await scraper.fetch_rss(u): await send_to_admin(context, item, session)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try: action, safe_id = query.data.split('_', 1)
    except: return
    
    if action == "disc":
        await query.message.delete()
        context.bot_data.pop(f"raw_{safe_id}", None)
        context.bot_data.pop(f"v_{safe_id}", None)
    
    elif action == "edit_raw":
        context.user_data["editing_raw"] = safe_id
        await query.message.reply_text("✏️ Send new **Raw Text** for this post.")

    elif action == "ai":
        status = await query.message.reply_text("⏳ AI Writing previews...")
        raw = context.bot_data.get(f"raw_{safe_id}")
        versions = {}
        for cid, config in CHANNEL_CONFIGS.items():
            v_text = await ai_engine.rewrite(raw["text"], config["prompt"])
            if v_text: versions[str(cid)] = v_text
        context.bot_data[f"v_{safe_id}"] = versions
        await status.delete()
        await show_previews(query.message, safe_id, context)

    elif action.startswith("edit_v:"):
        _, target_id = action.split(':', 1)
        context.user_data["editing_v"] = {"safe_id": safe_id, "target_id": target_id}
        name = CHANNEL_CONFIGS[int(target_id) if target_id.startswith("-") else target_id]["name"]
        await query.message.reply_text(f"✏️ Send new text for <b>{name}</b>", parse_mode=ParseMode.HTML)

    elif action == "puball":
        v = context.bot_data.get(f"v_{safe_id}")
        raw = context.bot_data.get(f"raw_{safe_id}")
        if not v: return
        for cid_str, text in v.items():
            cid = int(cid_str) if cid_str.startswith("-") else cid_str
            try:
                if raw.get("photo_id"): await context.bot.send_photo(chat_id=cid, photo=raw["photo_id"], caption=text[:1024], parse_mode=ParseMode.HTML)
                else: await context.bot.send_message(chat_id=cid, text=text, parse_mode=ParseMode.HTML)
            except: pass
        for cid in EXTRA_CHANNELS:
            try:
                first_v = list(v.values())[0]
                if raw.get("photo_id"): await context.bot.send_photo(chat_id=cid, photo=raw["photo_id"], caption=first_v[:1024], parse_mode=ParseMode.HTML)
                else: await context.bot.send_message(chat_id=cid, text=first_v, parse_mode=ParseMode.HTML)
            except: pass
        await query.message.reply_text("🚀 Published All!")

    elif action == "pubdirect":
        raw = context.bot_data.get(f"raw_{safe_id}")
        if not raw: return
        all_targets = list(CHANNEL_CONFIGS.keys()) + EXTRA_CHANNELS
        for cid in all_targets:
            try:
                if raw.get("photo_id"): await context.bot.send_photo(chat_id=cid, photo=raw["photo_id"], caption=raw["text"][:1024], parse_mode=ParseMode.HTML)
                else: await context.bot.send_message(chat_id=cid, text=raw["text"], parse_mode=ParseMode.HTML)
            except: pass
        await query.message.reply_text("🚀 Published Direct!")

async def show_previews(message, safe_id, context):
    v = context.bot_data.get(f"v_{safe_id}")
    preview_text = "<b>✨ AI Rewritten Previews</b>\n\n"
    kb_btns = []
    for cid_str, text in v.items():
        name = CHANNEL_CONFIGS[int(cid_str) if cid_str.startswith("-") else cid_str]["name"]
        preview_text += f"📌 <b>{name}:</b>\n{text[:200]}...\n\n"
        kb_btns.append([InlineKeyboardButton(f"✏️ Edit {name}", callback_data=f"edit_v:{cid_str}_{safe_id}")])
    kb_btns.append([InlineKeyboardButton("🚀 Publish All Now", callback_data=f"puball_{safe_id}"), InlineKeyboardButton("🔴 Discard", callback_data=f"disc_{safe_id}")])
    await message.reply_text(preview_text, reply_markup=InlineKeyboardMarkup(kb_btns), parse_mode=ParseMode.HTML)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle Raw Edit
    if "editing_raw" in context.user_data:
        safe_id = context.user_data.pop("editing_raw")
        context.bot_data[f"raw_{safe_id}"]["text"] = update.message.text
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🤖 AI Rewrite (Preview)", callback_data=f"ai_{safe_id}"), InlineKeyboardButton("✅ Direct Publish", callback_data=f"pubdirect_{safe_id}")]])
        await update.message.reply_text("✅ Raw text updated! Now choose action:", reply_markup=kb)
        return

    # Handle Version Edit
    edit_v = context.user_data.get("editing_v")
    if edit_v:
        safe_id, target_id = edit_v["safe_id"], edit_v["target_id"]
        context.bot_data[f"v_{safe_id}"][target_id] = update.message.text
        context.user_data.pop("editing_v")
        await update.message.reply_text("✅ Version updated! Reviewing again...")
        await show_previews(update.message, safe_id, context)

def main():
    persistence = PicklePersistence(filepath="bot_persistence.pickle")
    app = Application.builder().token(BOT_TOKEN).persistence(persistence).build()
    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Bot Started")))
    app.add_handler(CommandHandler("clean", lambda u, c: db.clear() or u.message.reply_text("Database Cleared")))
    app.add_handler(CommandHandler("check", lambda u, c: check_news_job(c)))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.job_queue.run_repeating(check_news_job, interval=CHECK_INTERVAL, first=10)
    app.run_polling()

if __name__ == '__main__': main()

