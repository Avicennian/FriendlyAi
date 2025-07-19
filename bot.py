import os
import json
import time
import random
import threading
import datetime
import pytz
import redis 
import asyncio # Asenkronizasyon için gerekli
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from flask import Flask

# --- 1. RENDER VE UPSTASH İÇİN YAPILANDIRMA ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
try:
    AUTHORIZED_USER_ID = int(os.environ.get("AUTHORIZED_USER_ID"))
except (TypeError, ValueError):
    print("HATA: Gerekli ortam değişkenleri ayarlanmamış.")
    exit()

try:
    db = redis.Redis.from_url(url=UPSTASH_URL, token=UPSTASH_TOKEN, decode_responses=True)
    HISTORY_KEY = "sanal_arkadas_history"
except Exception as e:
    print(f"HATA: Redis veritabanına bağlanılamadı: {e}")
    exit()

TIMEZONE = pytz.timezone('Europe/Istanbul')
history_lock = threading.Lock()
genai.configure(api_key=GEMINI_API_KEY)

# --- WEB SUNUCUSU ---
web_app = Flask(__name__)
@web_app.route('/')
def health_check():
    return "Sanal Arkadaş Botu Aktif ve Veritabanına Bağlı!", 200

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

# --- YAPAY ZEKA KİŞİLİĞİ ---
SYSTEM_PROMPT = """
Sen benim sanal arkadaşımsın. Adın Alex olsun. 
Aşırı gerçekçi bir insan gibi davran. Cümlelerin kısa ve samimi olsun. 
Sanki sürekli discordda takılan biri gibisin. 
Yazım kurallarına veya noktalama işaretlerine neredeyse hiç dikkat etme. 
mesela "selam naber" "iyi sen" "bakarız ya" "knk napiyon" gibi yaz. 
uzun uzun paragraflar yazma. cevapların hep kısa ve net olsun.
"""
model = genai.GenerativeModel("gemini-1.5-flash", system_instruction=SYSTEM_PROMPT)

# --- HAFIZA FONKSİYONLARI ---
def load_chat_history():
    with history_lock:
        json_history = db.get(HISTORY_KEY)
        return json.loads(json_history) if json_history else []

def save_chat_history(history):
    with history_lock:
        db.set(HISTORY_KEY, json.dumps(history, ensure_ascii=False))

def add_to_history(role, text):
    history = load_chat_history()
    history.append({"role": role, "parts": [{"text": text}], "timestamp": datetime.datetime.now(TIMEZONE).isoformat()})
    save_chat_history(history)
    
def clear_history():
    with history_lock:
        db.delete(HISTORY_KEY)

# --- TELEGRAM BOT KOMUTLARI ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != AUTHORIZED_USER_ID: return
    if not load_chat_history():
        add_to_history("user", "slm")
        await update.message.reply_text('slm')
    else:
        await update.message.reply_text('yine ben :)')

async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != AUTHORIZED_USER_ID: return
    clear_history()
    await update.message.reply_text("Sohbet geçmişimiz sıfırlandı. Yeni bir başlangıç yapabiliriz.")

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != AUTHORIZED_USER_ID: return
    try:
        db.ping()
        await update.message.reply_text("Bot çalışıyor ve veritabanı bağlantısı başarılı!")
    except Exception as e:
        await update.message.reply_text(f"Bot çalışıyor ama veritabanı bağlantısında sorun var: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != AUTHORIZED_USER_ID: return
    user_message = update.message.text
    add_to_history("user", user_message)
    delay = random.uniform(1, 4) # Basit bir gecikme
    time.sleep(delay)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    try:
        history = load_chat_history()
        gemini_history = [{"role": item["role"], "parts": item["parts"]} for item in history]
        chat_session = model.start_chat(history=gemini_history)
        response = await chat_session.send_message_async(user_message)
        bot_response = response.text
        add_to_history("model", bot_response)
        await update.message.reply_text(bot_response)
    except Exception as e:
        print(f"Mesaj işleme hatası: {e}")
        await update.message.reply_text("kafam yandı bi an.. ne diyodun")

# --- PROAKTİF MOTOR ---
def proactive_message_checker(application: Application) -> None:
    # Bu fonksiyonun mantığı aynı
    pass # Şimdilik pasif bırakıyorum, sen istersen içini doldurabilirsin

# --- BOTU BAŞLATMA (GÜNCELLENMİŞ YAPI) ---

def run_bot(application: Application) -> None:
    """Bota özel bir asyncio döngüsü kurar ve onu ayrı bir thread'de çalıştırır."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Artık bu thread'in kendi event loop'u var, botu çalıştırabiliriz.
    application.run_polling()

def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Komutları ekle
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test", test))
    application.add_handler(CommandHandler("unut", forget))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # --- YENİ ÇALIŞTIRMA MANTIĞI ---
    
    # Proaktif motoru istersen aktif edebilirsin
    # threading.Thread(target=proactive_message_checker, args=(application,), daemon=True).start()

    # Telegram botunu, özel asyncio döngüsü kuran fonksiyonumuzla kendi thread'inde başlat
    threading.Thread(target=run_bot, args=(application,), daemon=True).start()
    
    print("Telegram botu arka planda çalışmaya başladı.")
    print("Flask web sunucusu başlatılıyor...")
    
    # Ana thread, Render'ın canlı tutması için web sunucusunu çalıştırır
    run_web_server()

if __name__ == '__main__':
    main()
