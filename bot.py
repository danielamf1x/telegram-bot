import os
import json
import logging
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ConversationHandler, ContextTypes, CallbackQueryHandler
)
from flask import Flask
from threading import Thread
import asyncio

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

ASKING, REVIEW = range(2)
user_data_store = {}

# ===== Валидация =====
def validate(key, text):
    if text.strip() == "-":
        return True
    if "Дата" in key:
        return bool(re.match(r"^(\d{2}\.\d{2}\.\d{2}|\-)$", text))
    if "Брутто" in key or "Нетто" in key:
        return bool(re.match(r"\d+([.,]\d{1,2})?$", text))
    if "валюта" in key.lower():
        return bool(re.match(r"[A-Z]{3}$", text))
    return True

# ===== Проверка дубликата номера заявки =====
def check_duplicate_request(request_number: str):
    try:
        values = sheet.col_values(3)  # 3-й столбец = "Номер заявки"
        if request_number in values:
            prefix, num = request_number.split("-")
            suggested = f"{prefix}-{int(num) + 1}"
            return suggested
    except Exception as e:
        logging.error(f"Ошибка при проверке дубликата: {e}")
    return None

# ===== Handlers =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_data_store[chat_id] = {"index": 0, "data": {}, "messages": []}

    msg = await update.message.reply_text(f"Привет! Давай заполним заявку.\n{questions[0]} (если неизвестно, ставь '-'):")
    user_data_store[chat_id]["messages"].append(msg)

    return ASKING

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text.strip()
    state = user_data_store.get(chat_id)

    if state is None:
        await update.message.reply_text("Нажми /start чтобы начать.")
        return ASKING

    idx = state["index"]

    if idx >= len(questions):
        return REVIEW

    key = questions[idx]

    # Проверка формата
    if not validate(key, text):
        msg = await update.message.reply_text(f"Некорректный формат для '{key}'. Попробуй ещё раз:")
        state["messages"].append(msg)
        return ASKING

    # Проверка дубликата для "Номер заявки"
    if key == "Номер заявки":
        suggestion = check_duplicate_request(text)
        if suggestion:
            msg = await update.message.reply_text(f"❌ Такой номер уже есть! Предлагаю использовать: {suggestion}")
            state["messages"].append(msg)
            return ASKING

    state["data"][key] = text
    state["index"] += 1

    # Если остались вопросы
    if state["index"] < len(questions):
        msg = await update.message.reply_text(f"{questions[state['index']]} (если неизвестно, ставь '-'):")
        state["messages"].append(msg)

        # Удаляем старые вопросы через 10 секунд
        for m in state["messages"]:
            asyncio.create_task(delete_message(update, context, m))
        state["messages"].clear()

        return ASKING

    # ===== Все ответы получены =====
    data = state["data"]

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

    await update.message.reply_text(f"📋 Проверь заявку:\n{client_template}",
                                    reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm")],
                                        [InlineKeyboardButton("✏️ Изменить", callback_data="edit")]
                                    ]))

    return REVIEW

async def review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    state = user_data_store.get(chat_id)
    await query.answer()

    if query.data == "confirm":
        row = [state["data"].get(q, "") for q in questions]
        sheet.append_row(row)
        await query.edit_message_text("✅ Заявка сохранена в Google Sheets!")
        del user_data_store[chat_id]
        return ConversationHandler.END

    elif query.data == "edit":
        await query.edit_message_text("✏️ Выбери, что редактировать:",
                                      reply_markup=InlineKeyboardMarkup([
                                          [InlineKeyboardButton(q, callback_data=f"edit_{i}")]
                                          for i, q in enumerate(questions)
                                      ]))
        return REVIEW

    elif query.data.startswith("edit_"):
        idx = int(query.data.split("_")[1])
        state["index"] = idx
        await query.edit_message_text(f"Измени поле: {questions[idx]} (если неизвестно, ставь '-'):")
        return ASKING

# ===== Просмотр списка заявок =====
async def list_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        values = sheet.get_all_values()
        if not values or len(values) < 2:
            await update.message.reply_text("Пока нет заявок.")
            return

        last_10 = values[-10:]
        text = "📑 Последние заявки:\n\n"
        for row in last_10:
            try:
                text += f"№ {row[2]} | {row[3]} | {row[4]} | {row[10]}\n"
            except IndexError:
                continue

        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Ошибка при получении заявок: {e}")

# ===== Удаление сообщений =====
async def delete_message(update: Update, context: ContextTypes.DEFAULT_TYPE, msg):
    try:
        await asyncio.sleep(10)
        await context.bot.delete_message(chat_id=update.message.chat_id, message_id=msg.message_id)
    except:
        pass

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
        states={
            ASKING: [MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)],
            REVIEW: [CallbackQueryHandler(review)]
        },
        fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("list", list_requests))

    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
