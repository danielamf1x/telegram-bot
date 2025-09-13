import os
import re
import json
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ConversationHandler, ContextTypes, CallbackQueryHandler
)

# ========= Настройки ==========
GOOGLE_SHEET_ID = "1t31GuGFQc-bQpwtlw4cQM6Eynln1r_vbXVo86Yn8k0E"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Загружаем JSON ключ из Secrets
google_creds_json = os.getenv("GOOGLE_JSON")
if not google_creds_json:
    raise ValueError("Не найден секрет GOOGLE_JSON")
creds_dict = json.loads(google_creds_json)

# Авторизация Google Sheets
creds = Credentials.from_service_account_info(
    creds_dict,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
client = gspread.authorize(creds)
sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1

# ========= Вопросы ==========
questions = [
    "Номер заявки",
    "Manager",
    "Клиент",
    "Услуга",
    "Пассажиры (через запятую)",
    "Нетто",
    "Валюта нетто",
    "Дата оплаты поставщику (ДД.MM.ГГ)",
    "Комиссия",
    "Валюта комиссии",
    "Маржа",
    "Валюта маржи",
    "Итого",
    "Валюта итого",
    "Дата услуги (ДД.MM.ГГ)",
    "Дата оплаты клиента (ДД.MM.ГГ)"
]

ASKING, CONFIRM = range(2)

# ========= Функции ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["answers"] = {}
    context.user_data["idx"] = 0
    await update.message.reply_text(
        f"Привет! Давай заполним заявку.\n\n{questions[0]} (если неизвестно, ставь '-')"
    )
    return ASKING

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data.get("idx", 0)
    answers = context.user_data.get("answers", {})
    text = update.message.text.strip()

    # Проверка дубликата номера заявки
    if questions[idx] == "Номер заявки":
        existing_numbers = [row[0] for row in sheet.get_all_values()[1:] if row]
        if text in existing_numbers:
            match = re.match(r"([^\d]*)(\d+)$", text)
            if match:
                prefix, num = match.groups()
                suggested = f"{prefix}{int(num) + 1}"
                await update.message.reply_text(
                    f"⚠️ Такой номер уже есть в таблице!\nПредлагаю использовать следующий: {suggested}"
                )
                text = suggested

    answers[questions[idx]] = text
    idx += 1

    if idx < len(questions):
        context.user_data["idx"] = idx
        await update.message.reply_text(
            f"{questions[idx]} (если неизвестно, ставь '-')"
        )
        return ASKING
    else:
        return await show_summary(update, context)

async def show_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data["answers"]

    sms_manager = (
        f"Заявка {data['Номер заявки']} для клиента {data['Клиент']} "
        f"услуга {data['Услуга']} дата {data['Дата услуги (ДД.MM.ГГ)']}."
    )

    sms_table = (
        f"Заявка {data['Номер заявки']}, менеджер {data['Manager']}, "
        f"пассажиры: {data['Пассажиры (через запятую)']}, "
        f"нетто {data['Нетто']} {data['Валюта нетто']}, "
        f"комиссия {data['Комиссия']} {data['Валюта комиссии']}, "
        f"маржа {data['Маржа']} {data['Валюта маржи']}, "
        f"итого {data['Итого']} {data['Валюта итого']}, "
        f"дата услуги {data['Дата услуги (ДД.MM.ГГ)']}, "
        f"оплата клиента {data['Дата оплаты клиента (ДД.MM.ГГ)']}, "
        f"оплата поставщику {data['Дата оплаты поставщику (ДД.MM.ГГ)']}."
    )

    context.user_data["sms_manager"] = sms_manager
    context.user_data["sms_table"] = sms_table

    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm")],
        [InlineKeyboardButton("✏️ Редактировать", callback_data="edit")]
    ]
    await update.message.reply_text(
        f"📩 СМС менеджеру:\n{sms_manager}\n\n📩 СМС в таблицу:\n{sms_table}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CONFIRM

async def confirm_or_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm":
        data = context.user_data["answers"]
        row = [data[q] for q in questions]
        sheet.append_row(row)
        await query.edit_message_text("✅ Заявка сохранена и отправлена в таблицу.")
        return ConversationHandler.END

    elif query.data == "edit":
        keyboard = [
            [InlineKeyboardButton(q, callback_data=f"edit_{i}")]
            for i, q in enumerate(questions)
        ]
        await query.edit_message_text(
            "Что хочешь отредактировать?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CONFIRM

async def edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    context.user_data["edit_idx"] = idx
    await query.edit_message_text(f"Введи новое значение для: {questions[idx]}")
    return ASKING

async def handle_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data.get("edit_idx")
    if idx is not None:
        context.user_data["answers"][questions[idx]] = update.message.text.strip()
    return await show_summary(update, context)

# ===== Просмотр предыдущих заявок =====
async def list_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = sheet.get_all_values()[1:]
    if not rows:
        await update.message.reply_text("Заявок пока нет.")
        return

    keyboard = []
    for r in rows[-10:]:
        num, mgr, *_ , date = r[0], r[1], *r[2:], r[14]
        keyboard.append([InlineKeyboardButton(f"{num} / {mgr} / {date}", callback_data=f"req_{num}")])

    await update.message.reply_text(
        "📋 Последние заявки:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    num = query.data.split("_", 1)[1]
    rows = sheet.get_all_values()[1:]
    for r in rows:
        if r[0] == num:
            sms_manager = (
                f"Заявка {r[0]} для клиента {r[2]} услуга {r[3]} дата {r[14]}."
            )
            sms_table = (
                f"Заявка {r[0]}, менеджер {r[1]}, пассажиры: {r[4]}, "
                f"нетто {r[5]} {r[6]}, комиссия {r[8]} {r[9]}, "
                f"маржа {r[10]} {r[11]}, итого {r[12]} {r[13]}, "
                f"дата услуги {r[14]}, оплата клиента {r[15]}, "
                f"оплата поставщику {r[7]}."
            )
            await query.edit_message_text(
                f"📩 СМС менеджеру:\n{sms_manager}\n\n📩 СМС в таблицу:\n{sms_table}"
            )
            return

# ========= Основное ==========
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASKING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit)
            ],
            CONFIRM: [
                CallbackQueryHandler(confirm_or_edit, pattern="^(confirm|edit)$"),
                CallbackQueryHandler(edit_field, pattern="^edit_\\d+$")
            ]
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=True  # 👈 добавлено для устранения предупреждения
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("list", list_requests))
    app.add_handler(CallbackQueryHandler(show_request, pattern="^req_"))

    app.run_polling()

if __name__ == "__main__":
    main()
