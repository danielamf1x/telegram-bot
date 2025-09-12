import os
import logging
import re
import json
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes
from flask import Flask
from threading import Thread

# ===== Logging =====
logging.basicConfig(level=logging.INFO)

# ===== Telegram Token и Google JSON из GitHub Secrets =====
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_JSON = os.environ.get("GOOGLE_JSON")
GOOGLE_SHEET_ID = "1t31GuGFQc-bQpwtlw4cQM6Eynln1r_vbXVo86Yn8k0E"

if not TELEGRAM_TOKEN:
    raise ValueError("Не найден секрет TELEGRAM_TOKEN")
if not GOOGLE_JSON:
    raise ValueError("Не найден секрет GOOGLE_JSON")

# ===== Google Sheets =====
credentials_dict = json.loads(GOOGLE_JSON)
scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
client = gspread.authorize(creds)
sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1

# ===== Вопросы =====
questions = [
    "Manager ID",
    "Manager",
    "Номер заявки",
    "Дата услуги (ДД.MM.ГГ)",
    "Тип услуги",
    "Аэропорт",
    "Терминал",
    "Направление",
    "Номер рейса",
    "Время рейса",
    "Пассажиры (через запятую)",
    "Нетто",
    "Валюта нетто (RUB, USD, EUR)",
    "Дата оплаты поставщику (ДД.MM.ГГ)",
    "Брутто",
    "Валюта брутто",
    "Дата оплаты клиентом (ДД.MM.ГГ)",
    "Способ оплаты клиентом",
    "Способ оплаты поставщику"
]

ASKING = 0
user_data_store = {}

# ===== Валидация =====
def validate(key, text):
    if "Дата" in key:
        return bool(re.match(r"\d{2}\.\d{2}\.\d{2}$", text))
    if "Брутто" in key or "Нетто" in key:
        return bool(re.match(r"\d+([.,]\d{1,2})?$", text))
    if "валюта" in key.lower():
        return bool(re.match(r"[A-Z]{3}$", text))
    return True

# ===== Handlers =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_data_store[chat_id] = {"index": 0, "data": {}}
    await update.message.reply_text(f"Привет! Давай заполним заявку.\n{questions[0]}:")
    return ASKING

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text.strip()
    state = user_data_store.get(chat_id)

    if state is None:
        await update.message.reply_text("Нажми /start чтобы начать.")
        return ASKING

    idx = state["index"]

    # Проверка на выход за пределы вопросов
    if idx >= len(questions):
        await update.message.reply_text("Опрос уже завершен. Нажми /start чтобы начать заново.")
        return ConversationHandler.END

    key = questions[idx]

    if not validate(key, text):
        await update.message.reply_text(f"Некорректный формат для '{key}'. Попробуй ещё раз:")
        return ASKING

    state["data"][key] = text
    state["index"] += 1

    if state["index"] >= len(questions):
        data = state["data"]

        # ===== Шаблон для менеджера =====
        client_template = f"""Заявка № {data['Номер заявки']}
Дата: {data['Дата услуги (ДД.MM.ГГ)']}
Услуга: {data['Тип услуги']}
Аэропорт: {data['Аэропорт']}
Терминал: {data['Терминал']}
Направление: {data['Направление']}
Рейс: {data['Номер рейса']}
Время: {data['Время рейса']}
Пассажиры:
{data['Пассажиры (через запятую)']}

Сумма к оплате: {data['Брутто']} {data['Валюта брутто']}"""

        # ===== Сохраняем в Google Sheets =====
        row = [
            data["Manager ID"], data["Manager"], data["Номер заявки"], data["Дата услуги (ДД.MM.ГГ)"], data["Тип услуги"],
            data["Аэропорт"], data["Терминал"], data["Направление"], data["Номер рейса"], data["Время рейса"],
            data["Пассажиры (через запятую)"], data["Нетто"], data["Валюта нетто"], data["Дата оплаты поставщику (ДД.MM.ГГ)"],
            data["Брутто"], data["Валюта брутто"], data["Дата оплаты клиентом (ДД.MM.ГГ)"], data["Способ оплаты клиентом"],
            data["Способ оплаты поставщику"]
        ]
        sheet.append_row(row)

        await update.message.reply_text(f"Шаблон для менеджера:\n{client_template}")
        await update.message.reply_text("Данные сохранены в Google Sheet ✅")

        del user_data_store[chat_id]
        return ConversationHandler.END

    # Следующий вопрос
    next_key = questions[state["index"]]
    await update.message.reply_text(f"{next_key}:")
    return ASKING

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if chat_id in user_data_store:
        del user_data_store[chat_id]
    await update.message.reply_text("Опрос отменен.")
    return ConversationHandler.END

# ===== Flask для Railway (24/7) =====
flask_app = Flask('')

@flask_app.route('/')
def home():
    return "Bot is running"

def run_flask():
    flask_app.run(host='0.0.0.0', port=8080)

Thread(target=run_flask).start()

# ===== Основная функция =====
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={ASKING: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    app.add_handler(conv_handler)
    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
