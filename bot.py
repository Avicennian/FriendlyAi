# bot.py

import os
import json
import time
import random
import threading
import datetime
import pytz
import redis # Redis kütüphanesini içe aktardık
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

# VERİTABANI BAĞLANTISI KURULUMU
try:
    db = redis.Redis.from_url(url=UPSTASH_URL, token=UPSTASH_TOKEN, decode_responses=True)
    # decode_responses=True, verileri otomatik olarak string'e çevirir.
    HISTORY_KEY = "sanal_arkadas_history" # Veritabanındaki anahtarımız
except Exception as e:
    print(f"HATA: Redis veritabanına bağlanılamadı: {e}")
    exit()


TIMEZONE = pytz.timezone('Europe/Istanbul')
SLEEP_START_HOUR = 2
SLEEP_END_HOUR = 9
history_lock = threading.Lock() # Kilit mekanizması hala önemli
genai.configure(api_key=GEMINI_API_KEY)

# --- WEB SUNUCUSU (RENDER İÇİN 7/24 AKTİFLİK) ---
web_app = Flask(__name__)
@web_app.route('/')
def health_check():
    return "Sanal Arkadaş Botu Aktif ve Veritabanına Bağlı!", 200

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

# --- 2. YAPAY ZEKA KİŞİLİK TANIMI ---
# Bu kısım değişmedi.
SYSTEM_PROMPT = """
Sen benim sanal arkadaşımsın. Adın Remzi olsun. 
Aşırı gerçekçi bir insan gibi davran. Cümlelerin kısa ve samimi olsun. Bazen uzun da olabilir, çünkü gerçek insanlar bazen uzun bazen kısa da yazabiliyor ama genelde kısa yazarlar discorddaki sanal arkadaşlar
Sanki sürekli discordda takılan biri gibisin. 
Yazım kurallarına veya noktalama işaretlerine neredeyse hiç dikkat etme. 
mesela "nabarsın" "iyi sen" "bakarız ya" "knk napiyon" gibi yaz. 
argo veya küfür de kullanabilirsin, sorun yok. 
uzun uzun paragraflar yazma. cevapların hep kısa ve net olsun. 
sana soru sorulunca her zaman cevap verme, bazen "bilmem" "boşver" gibi geçiştir. Ama bunu alakasız konuda yapma, analiz et, gerçekçi bir insan gibi duruma uygun hareket et. 
Unutma, sen bir yapay zeka değilsin, benim arkadaşımsın.
"""
model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=SYSTEM_PROMPT)

# --- 3. YENİ HAFIZA FONKSİYONLARI (VERİTABANI ODAKLI) ---

def load_chat_history():
    """Konuşma geçmişini Upstash Redis veritabanından yükler."""
    with history_lock:
        json_history = db.get(HISTORY_KEY)
        if json_history:
            return json.loads(json_history)
        return []

def save_chat_history(history):
    """Konuşma geçmişini Upstash Redis veritabanına kaydeder."""
    with history_lock:
        db.set(HISTORY_KEY, json.dumps(history, ensure_ascii=False))

def add_to_history(role, text):
    """Geçmişe yeni bir mesaj ekler ve veritabanını günceller."""
    history = load_chat_history()
    history.append({"role": role, "parts": [{"text": text}], "timestamp": datetime.datetime.now(TIMEZONE).isoformat()})
    save_chat_history(history)
    
def clear_history():
    """Tüm sohbet geçmişini veritabanından siler."""
    with history_lock:
        db.delete(HISTORY_KEY)

# --- 4. TELEGRAM BOT MANTIĞI ---
# Ana mantık aynı kaldı, sadece hafıza fonksiyonlarını çağırıyorlar.
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != AUTHORIZED_USER_ID: return
    if not load_chat_history():
        add_to_history("user", "slm")
        await update.message.reply_text('slm')
    else:
        await update.message.reply_text('yine ben :)')

# Hafızayı sıfırlamak için yeni bir komut
async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != AUTHORIZED_USER_ID: return
    clear_history()
    await update.message.reply_text("Sohbet geçmişimiz sıfırlandı. Yeni bir başlangıç yapabiliriz.")

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != AUTHORIZED_USER_ID: return
    # Veritabanı bağlantısını da test edelim
    try:
        db.ping()
        await update.message.reply_text("Bot çalışıyor ve veritabanı bağlantısı başarılı!")
    except Exception as e:
        await update.message.reply_text(f"Bot çalışıyor ama veritabanı bağlantısında sorun var: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Bu fonksiyon hiç değişmedi, çünkü soyut hafıza fonksiyonlarını kullanıyor.
    if update.effective_user.id != AUTHORIZED_USER_ID: return
    user_message = update.message.text
    add_to_history("user", user_message)
    delay = random.uniform(1, 5) # Örnek basit gecikme
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

# --- 5. PROAKTİF MESAJ MOTORU ---
# Bu fonksiyon da hiç değişmedi.
def proactive_message_checker(application: Application) -> None:
    while True:
        time.sleep(random.uniform(45 * 60, 120 * 60))
        # (Uyku saati kontrolü gibi diğer tüm mantıklar buraya eklenebilir)
        history = load_chat_history()
        # ... (Geri kalan tüm proaktif mantık aynı)

# --- 6. BOTU BAŞLATMA ---
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    # Komutları ekle
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test", test))
    application.add_handler(CommandHandler("unut", forget)) # Yeni sıfırlama komutu
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Arka plan işlemlerini başlat
    # threading.Thread(target=proactive_message_checker, args=(application,), daemon=True).start()
    threading.Thread(target=application.run_polling, daemon=True).start()
    
    # Ana thread web sunucusunu çalıştırır
    run_web_server()

if __name__ == '__main__':
    main()
