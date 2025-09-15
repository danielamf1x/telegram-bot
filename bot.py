import os
import re
import json
import gspread
from google.oauth2.service_account import Credentials
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, Message
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ConversationHandler, ContextTypes, CallbackQueryHandler
)

# ========= Настройки ==========
GOOGLE_SHEET_ID = "1t31GuGFQc-bQpwtlw4cQM6Eynln1r_vbXVo86Yn8k0E"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

google_creds_json = os.getenv("GOOGLE_JSON")
if not google_creds_json:
    raise ValueError("Не найден секрет GOOGLE_JSON")
creds_dict = json.loads(google_creds_json)

creds = Credentials.from_service_account_info(
    creds_dict,
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
client = gspread.authorize(creds)
sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1

# ========= Вопросы ==========
questions = [
    "Номер заявки",
    "Manager ID",
    "Manager",
    "Дата (ДД.MM.ГГ)",
    "Услуга",
    "Аэропорт",
    "Терминал",
    "Направление",
    "Рейс",
    "Время (чч:мм)",
    "Пассажиры (через запятую)",
    "Брутто",
    "Валюта брутто",
    "Нетто",
    "Валюта нетто",
    "Дата оплаты клиентом (ДД.MM.ГГ)",
    "Куда оплатил клиент",
    "Дата оплаты поставщику (ДД.MM.ГГ)",
    "Как оплатили поставщику",
]

ASKING, CONFIRM, EDITING = range(3)


# ========= Вспомогательные ==========
def find_next_number(current: str, existing: list[str]) -> str:
    """Предлагает следующий номер заявки"""
    match = re.match(r"([^\d]*)(\d+)$", current)
    if match:
        prefix, num = match.groups()
        next_num = int(num)
        while f"{prefix}{next_num}" in existing:
            next_num += 1
        return f"{prefix}{next_num}"
    return current


def format_sms_manager(data: dict) -> str:
    return (
        f"Заявка № {data['Номер заявки']}\n"
        f"Дата: {data['Дата (ДД.MM.ГГ)']}\n"
        f"Услуга: {data['Услуга']}\n"
        f"Аэропорт: {data['Аэропорт']}\n"
        f"Терминал: {data['Терминал']}\n"
        f"Направление: {data['Направление']}\n"
        f"Рейс: {data['Рейс']}\n"
        f"Время: {data['Время (чч:мм)']}\n"
        f"Пассажиры:\n" + "\n".join(data['Пассажиры (через запятую)'].split(",")) + "\n\n"
        f"Сумма к оплате: {data['Нетто']} {data['Валюта нетто']}"
    )


def format_sms_table(data: dict) -> str:
    return (
        f"Manager ID: {data['Manager ID']}\n"
        f"Manager: {data['Manager']}\n"
        f"Заявка № {data['Номер заявки']}\n"
        f"Дата: {data['Дата (ДД.MM.ГГ)']}\n"
        f"Услуга: {data['Услуга']}\n"
        f"Аэропорт: {data['Аэропорт']}\n"
        f"Терминал: {data['Терминал']}\n"
        f"Направление: {data['Направление']}\n"
        f"Рейс: {data['Рейс']}\n"
        f"Время: {data['Время (чч:мм)']}\n"
        f"Пассажиры:\n" + "\n".join(data['Пассажиры (через запятую)'].split(",")) + "\n"
        f"Брутто: {data['Брутто']} {data['Валюта брутто']}\n"
        f"Нетто: {data['Нетто']} {data['Валюта нетто']}\n"
        f"Даты оплаты клиентом: {data['Дата оплаты клиентом (ДД.MM.ГГ)']}\n"
        f"Куда оплатил клиент: {data['Куда оплатил клиент']}\n"
        f"Дата оплаты поставщику: {data['Дата оплаты поставщику (ДД.MM.ГГ)']}\n"
        f"Как оплатили поставщику: {data['Как оплатили поставщику']}"
    )


async def cleanup_messages(context: ContextTypes.DEFAULT_TYPE):
    """Удаляет временные вопросы/ответы"""
    for msg in context.user_data.get("to_delete", []):
        try:
            await msg.delete()
        except Exception:
            pass
    context.user_data["to_delete"] = []


# ========= Логика ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["answers"] = {}
    context.user_data["idx"] = 0
    context.user_data["to_delete"] = []

    m = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"{questions[0]} (если неизвестно, ставь '-')"
    )
    context.user_data["to_delete"].append(m)
    return ASKING


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data["idx"]
    answers = context.user_data["answers"]
    text = update.message.text.strip()

    context.user_data.setdefault("to_delete", []).append(update.message)

    # Проверка дубликата
    if questions[idx] == "Номер заявки":
        existing_numbers = [row[0] for row in sheet.get_all_values()[1:] if row]
        if text in existing_numbers:
            suggested = find_next_number(text, existing_numbers)
            text = suggested
            m = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⚠️ Такой номер уже есть! Предлагаю: {suggested}"
            )
            context.user_data["to_delete"].append(m)

    answers[questions[idx]] = text

    idx += 1
    if idx < len(questions):
        context.user_data["idx"] = idx
        m = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"{questions[idx]} (если неизвестно, ставь '-')"
        )
        context.user_data["to_delete"].append(m)
        return ASKING
    else:
        return await show_summary(update, context)


async def show_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cleanup_messages(context)
    data = context.user_data["answers"]

    sms_manager = format_sms_manager(data)
    sms_table = format_sms_table(data)
    context.user_data["sms_manager"] = sms_manager
    context.user_data["sms_table"] = sms_table

    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm")],
        [InlineKeyboardButton("✏️ Редактировать", callback_data="edit")]
    ]
    m = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"📩 СМС менеджеру:\n{sms_manager}\n\n📩 СМС в таблицу:\n{sms_table}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data["summary_msg"] = m
    return CONFIRM


async def confirm_or_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm":
        data = context.user_data["answers"]
        row = [data.get(q, "-") for q in questions]
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
        return EDITING


async def edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    idx = int(query.data.split("_")[1])
    context.user_data["edit_idx"] = idx

    m = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Введи новое значение для: {questions[idx]}"
    )
    context.user_data["to_delete"].append(m)
    return ASKING


async def handle_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data.get("edit_idx")
    if idx is None:
        return ASKING

    context.user_data["answers"][questions[idx]] = update.message.text.strip()
    context.user_data["to_delete"].append(update.message)
    context.user_data.pop("edit_idx", None)

    return await show_summary(update, context)


# === /list ===
async def list_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = sheet.get_all_values()[1:]
    if not rows:
        await update.message.reply_text("Заявок пока нет.")
        return

    keyboard = []
    for r in rows[-10:]:
        num, mgr = r[0], r[2]
        keyboard.append([InlineKeyboardButton(f"{num} / {mgr}", callback_data=f"req_{num}")])

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="📋 Последние заявки:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    num = query.data.split("_", 1)[1]
    rows = sheet.get_all_values()[1:]
    for r in rows:
        if r[0] == num:
            data = dict(zip(questions, r))
            sms_manager = format_sms_manager(data)
            sms_table = format_sms_table(data)
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
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit),
            ],
            CONFIRM: [
                CallbackQueryHandler(confirm_or_edit, pattern="^(confirm|edit)$"),
            ],
            EDITING: [
                CallbackQueryHandler(edit_field, pattern="^edit_\\d+$")
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("list", list_requests))
    app.add_handler(CallbackQueryHandler(show_request, pattern="^req_"))

    app.run_polling()


if __name__ == "__main__":
    main()
