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

# Channel Configs with distinct prompts
PRIMARY_CHANNEL_ID = -1002416411673 # Gyar Nuu
THEINKHA_CHANNEL = "@theinkha007"
KNOWLEDGE_CHANNEL = "@developknowledge007"

CHANNEL_CONFIGS = {
    PRIMARY_CHANNEL_ID: {
        "name": "Gyar Nuu (သေသပ်သော သတင်းဟန်)",
        "prompt": (
            "မင်းက ကျွမ်းကျင်တဲ့ သတင်းအယ်ဒီတာတစ်ယောက်ဖြစ်တယ်။ "
            "အောက်ပါ မြန်မာသတင်းစာသားကို အဓိပ္ပာယ် လုံးဝမပျက်စေဘဲ၊ သတင်းအချက်အလက် စုံစုံလင်လင်ဖြင့် "
            "ဖတ်ရတာ ပိုမိုသေသပ်ချောမွေ့ပြီး ခိုင်မာတဲ့ သတင်းဟန်အဖြစ် ပြန်လည်ပြင်ရေးပေးပါ။ "
            "သတင်းခေါင်းစဉ်ကို အပေါ်ဆုံးကနေ စာလုံးအထူ (Bold) ဖြင့် ထားပေးပါ။ "
            "စကားလုံးအသုံးအနှုန်းများကို သတင်းဌာနကြီးများကဲ့သို့ ယဉ်ကျေးသေသပ်စွာ သုံးနှုန်းပါ။"
        )
    },
    THEINKHA_CHANNEL: {
        "name": "Theinkha (ပေါ့ပါးသော လူမှုကွန်ရက်ဟန်)",
        "prompt": (
            "မင်းက စာဖတ်သူနဲ့ ရင်းနှီးတဲ့ Social Media Content Creator တစ်ယောက်ဖြစ်တယ်။ "
            "အောက်ပါ သတင်းကို လူမှုကွန်ရက်စာမျက်နှာပေါ်မှာ တင်ဖို့အတွက် ဖတ်ရတာ ပေါ့ပေါ့ပါးပါးနဲ့ "
            "စိတ်ဝင်စားဖို့ကောင်းအောင်၊ သင့်တော်တဲ့ နေရာတွေမှာ အီမိုဂျီ (Emoji) လေးတွေ ထည့်သွင်းပြီး ပြန်လည်ရေးသားပေးပါ။ "
            "သတင်းခေါင်းစဉ်ကို စိတ်ဝင်စားစရာဖြစ်အောင် ရေးပေးပါ။"
        )
    },
    KNOWLEDGE_CHANNEL: {
        "name": "Develop Knowledge (ဗဟုသုတနှင့် သုံးသပ်ချက်ဟန်)",
        "prompt": (
            "မင်းက ဗဟုသုတ မျှဝေသူတစ်ယောက် ဖြစ်တယ်။ အောက်ပါသတင်းကို ဖတ်ရှုသူတွေ အလွယ်တကူ သဘောပေါက်ပြီး "
            "ဗဟုသုတရစေဖို့အတွက် အဓိကအချက်အလက်များကို Bullet points (အစက်အပြောက်များ) ဖြင့် စနစ်တကျ ခွဲခြားပြီး "
            "ဖတ်ရလွယ်ကူအောင် ပြန်လည်ပြင်ရေးပေးပါ။ စာလုံးအထူ (Bold) များကို အဓိကနေရာတွေမှာ သုံးပေးပါ။"
        )
    }
}

EXTRA_CHANNELS = ["@bhonehtetmm", "@maungpn777"]

CHANNELS_TO_SCRAPE = ["popularjournal", "kothetjournalist", "hminewai", "globalnews247", "myanmarupdate", "MyanmarNationalPost"]
RSS_URLS = [
    "https://popularmyanmar.com/feed",
    "https://www.bbc.com/burmese/index.xml",
    "https://www.rfa.org/burmese/rss2.xml",
    "https://news-eleven.com/feed",
    "https://www.nssmy.com/feed"
]

RSSHUB_MIRRORS = ["https://rsshub.rssforever.com", "https://rsshub.app"]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/108.0"
]

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
def make_safe_key(post_id):
    return hashlib.md5(post_id.encode("utf-8")).hexdigest()[:15]

def is_valid_image_url(url):
    if not url: return False
    return any(ext in url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"])

async def download_image(session, url):
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    try:
        async with session.get(url, headers=headers, timeout=10) as res:
            if res.status == 200 and "image" in res.headers.get("Content-Type", ""):
                content = await res.read()
                img_io = io.BytesIO(content)
                img_io.name = 'news_image.jpg'
                return img_io
    except: pass
    return None

# --- 🤖 AI ENGINE (Groq API) ---
class AIEngine:
    def __init__(self, api_key):
        self.api_key = api_key
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        self.model_name = "llama-3.3-70b-versatile"

    async def rewrite(self, text, prompt_style):
        if not self.api_key: return None
        prompt = f"{prompt_style}\n\nမူရင်းသတင်းစာသား -\n{text}"
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 2048,
            "stream": False
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, headers=headers, timeout=30) as response:
                    res_json = await response.json()
                    if response.status == 200:
                        return res_json["choices"][0]["message"]["content"]
        except: pass
        return None

ai_engine = AIEngine(GROQ_API_KEY)

# --- 📰 SCRAPERS ---
class NewsScraper:
    def __init__(self, session):
        self.session = session

    async def fetch_telegram(self, channel):
        logger.info(f"Fetching Telegram channel: @{channel}")
        for mirror in RSSHUB_MIRRORS:
            url = f"{mirror}/telegram/channel/{channel}"
            try:
                headers = {"User-Agent": random.choice(USER_AGENTS)}
                async with self.session.get(url, headers=headers, timeout=20) as response:
                    if response.status != 200: continue
                    html_content = await response.text()
                
                soup = BeautifulSoup(html_content, "xml")
                items = []
                for item_tag in soup.find_all("item"):
                    guid = item_tag.find("guid") or item_tag.find("link")
                    if not guid: continue
                    
                    unique_id = f"tg_{channel}_{hashlib.md5(guid.text.encode()).hexdigest()[:12]}"
                    if db.is_processed(unique_id): continue

                    desc = item_tag.find("description").text if item_tag.find("description") else ""
                    desc_soup = BeautifulSoup(desc, "html.parser")
                    
                    image_url = None
                    img_tag = desc_soup.find("img")
                    if img_tag: image_url = img_tag.get("src")
                    if not image_url:
                        media = item_tag.find("media:content") or item_tag.find("enclosure")
                        if media: image_url = media.get("url")

                    clean_desc = desc_soup.get_text(separator="\n").strip()
                    clean_desc = re.sub(r'^[\s\n]*(🖼️|🖼|📷|📸|📹|🎥|📽️|🎞️|🎬)[\s\n]*', '', clean_desc)
                    
                    items.append({
                        "id": unique_id,
                        "source": f"Telegram (@{channel})",
                        "summary": clean_desc,
                        "image_url": image_url if is_valid_image_url(image_url) else None,
                        "link": item_tag.find("link").text if item_tag.find("link") else ""
                    })
                if items: return items
            except: continue
        return []

    async def fetch_rss(self, url):
        items = []
        source_name = self._get_rss_source_name(url)
        try:
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            async with self.session.get(url, headers=headers, timeout=15) as response:
                if response.status != 200: return []
                content = await response.read()
            
            soup = BeautifulSoup(content, features="xml")
            for item in soup.find_all("item"):
                guid = item.find("guid") or item.find("link")
                if not guid: continue
                
                link = item.find("link").text.strip() if item.find("link") else ""
                unique_id = f"rss_{guid.text.strip()}"
                if db.is_processed(unique_id): continue
                
                title = item.find("title").text.strip() if item.find("title") else ""
                desc = item.find("description").text.strip() if item.find("description") else ""
                clean_desc = BeautifulSoup(desc, "html.parser").get_text().strip()
                summary = f"<b>{title}</b>\n\n{clean_desc}"
                
                image_url, full_summary = await self._fetch_full_rss_content(link, url, title, summary)
                
                items.append({
                    "id": unique_id,
                    "source": source_name,
                    "summary": full_summary,
                    "image_url": image_url if is_valid_image_url(image_url) else None,
                    "link": link
                })
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
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            async with self.session.get(link, headers=headers, timeout=6) as res:
                if res.status == 200:
                    html_content = await res.text()
                    soup = BeautifulSoup(html_content, "html.parser")
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
    summary = item["summary"]
    clean_text = BeautifulSoup(summary, "html.parser").get_text(separator='\n').strip()
    if len(clean_text) < 10:
        db.add(item['id'])
        return

    safe_summary = summary if summary.startswith("<b>") else html.escape(clean_text)
    caption = f"<b>Source:</b> {item['source']}\n\n{safe_summary}"
    safe_id = make_safe_key(item['id'])

    original_photo_id = None
    if item.get("image_url"):
        img = await download_image(session, item["image_url"])
        if img:
            sent_message = await context.bot.send_photo(chat_id=ADMIN_ID, photo=img, caption="Processing...")
            original_photo_id = sent_message.photo[-1].file_id
            await sent_message.delete()

    context.bot_data[f"raw_{safe_id}"] = {"text": clean_text, "link": item["link"], "original_photo_id": original_photo_id}

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 AI Rewrite & Publish All", callback_data=f"ai_{safe_id}")],
        [InlineKeyboardButton("✍️ Edit", callback_data=f"edit_{safe_id}"), InlineKeyboardButton("✅ Direct Publish", callback_data=f"pubdirect_{safe_id}")],
        [InlineKeyboardButton("🔴 Discard", callback_data=f"disc_{safe_id}"), InlineKeyboardButton("🔗 Original", url=item["link"])]
    ])

    try:
        if original_photo_id:
            if len(caption) <= 1024:
                await context.bot.send_photo(chat_id=ADMIN_ID, photo=original_photo_id, caption=caption, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            else:
                await context.bot.send_photo(chat_id=ADMIN_ID, photo=original_photo_id)
                await context.bot.send_message(chat_id=ADMIN_ID, text=caption, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        else:
            await context.bot.send_message(chat_id=ADMIN_ID, text=caption, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        db.add(item['id'])
    except: pass

async def check_news_job(context: ContextTypes.DEFAULT_TYPE):
    async with aiohttp.ClientSession() as session:
        scraper = NewsScraper(session)
        tg_results = await asyncio.gather(*(scraper.fetch_telegram(c) for c in CHANNELS_TO_SCRAPE))
        for items in tg_results:
            for item in items: await send_to_admin(context, item, session)
        rss_results = await asyncio.gather(*(scraper.fetch_rss(u) for u in RSS_URLS))
        for items in rss_results:
            for item in items: await send_to_admin(context, item, session)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try: action, safe_id = query.data.split('_', 1)
    except: return
    
    raw = context.bot_data.get(f"raw_{safe_id}")
    if not raw and action != "disc": return

    if action == "disc":
        await query.message.delete()
        context.bot_data.pop(f"raw_{safe_id}", None)
    
    elif action == "edit":
        await query.message.reply_text("✏️ **Please send your edited text now.**")
        context.user_data["editing_post_id"] = safe_id

    elif action == "ai":
        status = await query.message.reply_text("⏳ <b>AI Rewrite လုပ်ပြီး Publish လုပ်နေပါသည်...</b>", parse_mode=ParseMode.HTML)
        text = raw["text"]
        photo_id = raw.get("original_photo_id")
        
        # Publish to main style channels
        for cid, config in CHANNEL_CONFIGS.items():
            v_text = await ai_engine.rewrite(text, config["prompt"])
            if v_text:
                try:
                    if photo_id:
                        if len(v_text) <= 1024: await context.bot.send_photo(chat_id=cid, photo=photo_id, caption=v_text, parse_mode=ParseMode.HTML)
                        else:
                            await context.bot.send_photo(chat_id=cid, photo=photo_id)
                            await context.bot.send_message(chat_id=cid, text=v_text, parse_mode=ParseMode.HTML)
                    else: await context.bot.send_message(chat_id=cid, text=v_text, parse_mode=ParseMode.HTML)
                except: pass
        
        # Publish to extra channels using the first available rewrite
        v_text_extra = await ai_engine.rewrite(text, CHANNEL_CONFIGS[PRIMARY_CHANNEL_ID]["prompt"])
        if v_text_extra:
            for cid in EXTRA_CHANNELS:
                try:
                    if photo_id:
                        if len(v_text_extra) <= 1024: await context.bot.send_photo(chat_id=cid, photo=photo_id, caption=v_text_extra, parse_mode=ParseMode.HTML)
                        else:
                            await context.bot.send_photo(chat_id=cid, photo=photo_id)
                            await context.bot.send_message(chat_id=cid, text=v_text_extra, parse_mode=ParseMode.HTML)
                    else: await context.bot.send_message(chat_id=cid, text=v_text_extra, parse_mode=ParseMode.HTML)
                except: pass
        
        await status.edit_text("✅ **All channels published successfully!**")

    elif action == "pubdirect":
        photo_id = raw.get("original_photo_id")
        text = raw["text"]
        all_targets = list(CHANNEL_CONFIGS.keys()) + EXTRA_CHANNELS
        for cid in all_targets:
            try:
                if photo_id:
                    if len(text) <= 1024: await context.bot.send_photo(chat_id=cid, photo=photo_id, caption=text, parse_mode=ParseMode.HTML)
                    else:
                        await context.bot.send_photo(chat_id=cid, photo=photo_id)
                        await context.bot.send_message(chat_id=cid, text=text, parse_mode=ParseMode.HTML)
                else: await context.bot.send_message(chat_id=cid, text=text, parse_mode=ParseMode.HTML)
            except: pass
        await query.message.reply_text("🚀 Published directly to all channels!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    safe_id = context.user_data.get("editing_post_id")
    if not safe_id: return
    text = update.message.text
    if f"raw_{safe_id}" in context.bot_data:
        context.bot_data[f"raw_{safe_id}"]["text"] = text
    context.user_data.pop("editing_post_id")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🤖 AI Rewrite & Publish All", callback_data=f"ai_{safe_id}"), InlineKeyboardButton("✅ Publish Directly", callback_data=f"pubdirect_{safe_id}")]])
    await update.message.reply_text("✅ Edited text received.", reply_markup=kb)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello! I am your News Bot.")

async def clean_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    db.clear()
    await update.message.reply_text("✅ Database cleared.")

async def manual_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await update.message.reply_text("⏳ Checking news...")
    await check_news_job(context)
    await update.message.reply_text("✅ Check completed.")

def main():
    persistence = PicklePersistence(filepath="bot_persistence.pickle")
    app = Application.builder().token(BOT_TOKEN).persistence(persistence).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clean", clean_db))
    app.add_handler(CommandHandler("check", manual_check))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.job_queue.run_repeating(check_news_job, interval=CHECK_INTERVAL, first=10)
    app.run_polling()

if __name__ == '__main__':
    main()
