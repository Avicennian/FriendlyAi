# bot.py

import os
import json
import time
import random
import threading
import datetime
import pytz
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from flask import Flask

# --- 1. RENDER İÇİN YAPILANDIRMA VE KURULUM ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
try:
    AUTHORIZED_USER_ID = int(os.environ.get("AUTHORIZED_USER_ID"))
except (TypeError, ValueError):
    print("HATA: AUTHORIZED_USER_ID ortam değişkeni ayarlanmamış.")
    exit()

# KALICI HAFIZANIN ADRESİ: Render'daki diskin yolu.
PERSISTENT_STORAGE_PATH = "/var/data"
CHAT_HISTORY_FILE = os.path.join(PERSISTENT_STORAGE_PATH, "chat_history.json")

TIMEZONE = pytz.timezone('Europe/Istanbul')
SLEEP_START_HOUR = 2
SLEEP_END_HOUR = 9
history_lock = threading.Lock()
genai.configure(api_key=GEMINI_API_KEY)

# --- WEB SUNUCUSU (RENDER İÇİN 7/24 AKTİFLİK) ---
web_app = Flask(__name__)
@web_app.route('/')
def health_check():
    return "Sanal Arkadaş Botu Aktif ve Çalışıyor!", 200

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

# --- 2. YAPAY ZEKA KİŞİLİK TANIMI ---
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

# --- 3. YARDIMCI FONKSİYONLAR (HAFIZA VE ZAMANLAMA) ---
def get_current_time():
    return datetime.datetime.now(TIMEZONE)

def is_sleeping_time():
    current_hour = get_current_time().hour
    return SLEEP_START_HOUR <= current_hour < SLEEP_END_HOUR

def get_humanlike_delay():
    if is_sleeping_time():
        now = get_current_time()
        wake_up_time = now.replace(hour=SLEEP_END_HOUR, minute=random.randint(0, 30), second=0)
        if now > wake_up_time: wake_up_time += datetime.timedelta(days=1)
        return (wake_up_time - now).total_seconds()
    else:
        rand = random.random()
        if rand < 0.5: return random.uniform(1, 5)
        elif rand < 0.9: return random.uniform(10, 90)
        else: return random.uniform(120, 900)

# KALICI HAFIZA FONKSİYONLARI
def load_chat_history():
    if not os.path.exists(CHAT_HISTORY_FILE):
        os.makedirs(PERSISTENT_STORAGE_PATH, exist_ok=True)
        return []
    with history_lock:
        with open(CHAT_HISTORY_FILE, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except json.JSONDecodeError: return []

def save_chat_history(history):
    with history_lock:
        with open(CHAT_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=4)

def add_to_history(role, text):
    history = load_chat_history()
    history.append({"role": role, "parts": [{"text": text}], "timestamp": get_current_time().isoformat()})
    save_chat_history(history)

# --- 4. TELEGRAM BOT MANTIĞI ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != AUTHORIZED_USER_ID:
        await update.message.reply_text("sadece sahibimle konuşurum.")
        return
    # Not: /start komutu artık hafızayı silmiyor.
    # Sadece geçmiş boşsa ilk mesajı ekliyor.
    if not load_chat_history():
        add_to_history("user", "slm")
        await update.message.reply_text('slm')
    else:
        await update.message.reply_text('yine ben :)')

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != AUTHORIZED_USER_ID: return
    await update.message.reply_text("Bot çalışıyor ve aktif. (Bu test mesajıdır, gecikme uygulanmaz)")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != AUTHORIZED_USER_ID: return
    user_message = update.message.text
    add_to_history("user", user_message)
    delay = get_humanlike_delay()
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
        print(f"Hata oluştu: {e}")
        await update.message.reply_text("kafam yandı bi an.. ne diyodun")

# --- 5. PROAKTİF MESAJ MOTORU ---
def proactive_message_checker(application: Application) -> None:
    # Bu fonksiyonun mantığı, kalıcı hafızaya güvendiği için değişmedi.
    while True:
        time.sleep(random.uniform(45 * 60, 120 * 60))
        if is_sleeping_time(): continue
        history = load_chat_history()
        if not history: continue
        last_message = history[-1]
        last_message_time = datetime.datetime.fromisoformat(last_message["timestamp"])
        time_since_last_message = get_current_time() - last_message_time
        if last_message["role"] == "model" and random.random() < 0.7: continue
        proactive_threshold_hours = random.uniform(4, 11)
        if time_since_last_message > datetime.timedelta(hours=proactive_threshold_hours):
            proactive_prompt = f"""Biz seninle arkadaşız. En son konuşmamızın üzerinden {int(time_since_last_message.total_seconds() / 3600)} saat geçti. Sohbeti yeniden başlatmak için çok doğal, alakasız veya komik bir şey yaz. "uzun zamandır konuşmadık" gibi klişe şeyler söyleme. Sanki aklına birden bir şey gelmiş gibi olsun. Örnek: "aklıma ne geldi lan", "rüyamda seni gördüm", "napiyon la değişik", "canım sıkıldı". Şimdi o mesajı yaz:"""
            try:
                proactive_model = genai.GenerativeModel("gemini-1.5-flash")
                response = proactive_model.generate_content(proactive_prompt)
                new_message = response.text
                application.bot.send_message(chat_id=AUTHORIZED_USER_ID, text=new_message)
                add_to_history("model", new_message)
            except Exception as e:
                print(f"Proaktif mesaj oluşturulurken hata: {e}")

# --- 6. BOTU VE WEB SUNUCUSUNU BAŞLATMA ---
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test", test))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    threading.Thread(target=proactive_message_checker, args=(application,), daemon=True).start()
    threading.Thread(target=application.run_polling, daemon=True).start()
    
    run_web_server()

if __name__ == '__main__':
    main()
