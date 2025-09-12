import os
import json
import logging
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes
from flask import Flask
from threading import Thread

# ===== Logging =====
logging.basicConfig(level=logging.INFO)

# ===== Telegram Token =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("Не найден секрет TELEGRAM_TOKEN")

# ===== Google Sheets =====
GOOGLE_SHEET_ID = "1t31GuGFQc-bQpwtlw4cQM6Eynln1r_vbXVo86Yn8k0E"
GOOGLE_JSON = os.getenv("GOOGLE_JSON")
if not GOOGLE_JSON:
    raise ValueError("Не найден секрет GOOGLE_JSON")

# Преобразуем JSON строку в объект Python
SERVICE_ACCOUNT_INFO = json.loads(GOOGLE_JSON)
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_dict(SERVICE_ACCOUNT_INFO, scope)
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

    # Если пользователь ответил на все вопросы
    if idx >= len(questions):
        await update.message.reply_text("Все вопросы уже заданы. Используй /start для новой заявки.")
        return ConversationHandler.END

    key = questions[idx]

    if not validate(key, text):
        await update.message.reply_text(f"Некорректный формат для '{key}'. Попробуй ещё раз:")
        return ASKING

    state["data"][key] = text
    state["index"] += 1

    # Если остались вопросы — задаём следующий
    if state["index"] < len(questions):
        await update.message.reply_text(f"{questions[state['index']]}:")
        return ASKING

    # ===== Все ответы получены =====
    data = state["data"]

    # ===== Шаблон для менеджера =====
    client_template = f"""Заявка № {data.get('Номер заявки', '')}
Дата: {data.get('Дата услуги (ДД.MM.ГГ)', '')}
Услуга: {data.get('Тип услуги', '')}
Аэропорт: {data.get('Аэропорт', '')}
Терминал: {data.get('Терминал', '')}
Направление: {data.get('Направление', '')}
Рейс: {data.get('Номер рейса', '')}
Время: {data.get('Время рейса', '')}
Пассажиры:
{data.get('Пассажиры (через запятую)', '')}

Сумма к оплате: {data.get('Брутто', '')} {data.get('Валюта брутто', '')}"""

    # ===== Шаблон для Google Sheets =====
    sheet_template = "\n".join([data.get(q, "") for q in questions])

    await update.message.reply_text(f"Шаблон для менеджера:\n{client_template}")
    await update.message.reply_text(f"Шаблон для таблицы:\n{sheet_template}")

    # ===== Сохраняем в Google Sheets =====
    row = [data.get(q, "") for q in questions]
    sheet.append_row(row)

    del user_data_store[chat_id]
    return ConversationHandler.END

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
