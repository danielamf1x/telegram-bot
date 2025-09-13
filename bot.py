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
    "Manager ID",
    "Manager",
    "Номер заявки",
    "Дата услуги (ДД.MM.ГГ)",
    "Тип услуги",
    "Аэропорт",
    "Терминал",
    "Направление",
    "Номер рейса",
    "Время рейса (ЧЧ:ММ/ЧЧ:ММ)",
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

ASKING, CONFIRM = range(2)

# ========= Вспомогательные функции ==========
def get_next_available_number(prefix="ДЮ-"):
    rows = sheet.get_all_values()[1:]
    numbers = [int(re.search(r"\d+$", r[2]).group()) for r in rows if re.match(rf"{prefix}\d+$", r[2])]
    return f"{prefix}{max(numbers)+1 if numbers else 1}"

def format_input(text):
    return text.strip() if text.strip() else "-"

# ========= Handlers ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["answers"] = {}
    context.user_data["idx"] = 0
    msg = await update.message.reply_text(f"{questions[0]} (если неизвестно, ставь '-')")
    context.user_data["last_msg"] = msg
    return ASKING

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data["idx"]
    answers = context.user_data["answers"]
    text = format_input(update.message.text)

    # Удаляем вопрос после ответа
    try: await context.user_data["last_msg"].delete()
    except: pass
    try: await update.message.delete()
    except: pass

    # Проверка дубликата номера заявки
    if questions[idx] == "Номер заявки":
        rows = sheet.get_all_values()[1:]
        existing_numbers = [r[2] for r in rows if r]
        if text in existing_numbers:
            text = get_next_available_number()
            msg = await update.message.reply_text(f"⚠️ Такой номер уже есть. Используем следующий: {text}")
            context.user_data["last_msg"] = msg

    answers[questions[idx]] = text
    idx += 1

    if idx < len(questions):
        context.user_data["idx"] = idx
        msg = await update.message.reply_text(f"{questions[idx]} (если неизвестно, ставь '-')")
        context.user_data["last_msg"] = msg
        return ASKING
    else:
        return await show_summary(update, context)

async def show_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data["answers"]

    sms_manager = (
        f"Заявка № {data['Номер заявки']}\n"
        f"Дата: {data['Дата услуги (ДД.MM.ГГ)']}\n"
        f"Услуга: {data['Тип услуги']}\n"
        f"Аэропорт: {data['Аэропорт']}\n"
        f"Терминал: {data['Терминал']}\n"
        f"Направление: {data['Направление']}\n"
        f"Рейс: {data['Номер рейса']}\n"
        f"Время: {data['Время рейса (ЧЧ:ММ/ЧЧ:ММ)']}\n"
        f"Пассажиры:\n{data['Пассажиры (через запятую)'].replace(',', '\n')}\n\n"
        f"Сумма к оплате: {data['Брутто']} {data['Валюта брутто']}"
    )

    sms_table = (
        f"Manager ID: {data['Manager ID']}\n"
        f"Manager: {data['Manager']}\n"
        f"Заявка № {data['Номер заявки']}\n"
        f"Дата: {data['Дата услуги (ДД.MM.ГГ)']}\n"
        f"Услуга: {data['Тип услуги']}\n"
        f"Аэропорт: {data['Аэропорт']}\n"
        f"Терминал: {data['Терминал']}\n"
        f"Направление: {data['Направление']}\n"
        f"Рейс: {data['Номер рейса']}\n"
        f"Время: {data['Время рейса (ЧЧ:ММ/ЧЧ:ММ)']}\n"
        f"Пассажиры:\n{data['Пассажиры (через запятую)'].replace(',', '\n')}\n\n"
        f"Брутто: {data['Брутто']} {data['Валюта брутто']}\n"
        f"Нетто: {data['Нетто']} {data['Валюта нетто (RUB, USD, EUR)']}\n\n"
        f"Дата оплаты клиентом: {data['Дата оплаты клиентом (ДД.MM.ГГ)']}\n"
        f"Куда оплатил клиент: {data['Способ оплаты клиентом']}\n"
        f"Дата оплаты поставщику: {data['Дата оплаты поставщику (ДД.MM.ГГ)']}\n"
        f"Как оплатили поставщику: {data['Способ оплаты поставщику']}"
    )

    context.user_data["sms_manager"] = sms_manager
    context.user_data["sms_table"] = sms_table

    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm")],
        [InlineKeyboardButton("✏️ Редактировать", callback_data="edit")]
    ]
    msg = await update.message.reply_text(
        f"📩 СМС менеджеру:\n{sms_manager}\n\n📩 СМС в таблицу:\n{sms_table}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data["last_msg"] = msg
    return CONFIRM

async def confirm_or_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "confirm":
        row = [context.user_data["answers"].get(q, "-") for q in questions]
        sheet.append_row(row)
        await query.edit_message_text("✅ Заявка сохранена и отправлена в таблицу.")
        return ConversationHandler.END
    elif query.data == "edit":
        keyboard = [[InlineKeyboardButton(q, callback_data=f"edit_{i}")] for i, q in enumerate(questions)]
        await query.edit_message_text("Что хочешь отредактировать?", reply_markup=InlineKeyboardMarkup(keyboard))
        return CONFIRM

async def edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    context.user_data["edit_idx"] = idx
    msg = await query.edit_message_text(f"Введи новое значение для: {questions[idx]} (если неизвестно, ставь '-')")
    context.user_data["last_msg"] = msg
    return ASKING

async def handle_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data.get("edit_idx")
    if idx is not None:
        text = format_input(update.message.text)
        context.user_data["answers"][questions[idx]] = text
    return await show_summary(update, context)

# ===== Просмотр предыдущих заявок =====
async def list_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = sheet.get_all_values()[1:]
    if not rows:
        await update.message.reply_text("Заявок пока нет.")
        return
    keyboard = [[InlineKeyboardButton(f"{r[2]} / {r[1]}", callback_data=f"req_{r[2]}")] for r in rows[-10:]]
    await update.message.reply_text("📋 Последние заявки:", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    num = query.data.split("_")[1]
    rows = sheet.get_all_values()[1:]
    for r in rows:
        if r[2] == num:
            sms_manager = (
                f"Заявка № {r[2]}\nДата: {r[3]}\nУслуга: {r[4]}\nАэропорт: {r[5]}\n"
                f"Терминал: {r[6]}\nНаправление: {r[7]}\nРейс: {r[8]}\nВремя: {r[9]}\n"
                f"Пассажиры:\n{r[10].replace(',', '\n')}\n\nСумма к оплате: {r[15]} {r[16]}"
            )
            sms_table = (
                f"Manager ID: {r[0]}\nManager: {r[1]}\nЗаявка № {r[2]}\nДата: {r[3]}\n"
                f"Услуга: {r[4]}\nАэропорт: {r[5]}\nТерминал: {r[6]}\nНаправление: {r[7]}\n"
                f"Рейс: {r[8]}\nВремя: {r[9]}\nПассажиры:\n{r[10].replace(',', '\n')}\n\n"
                f"Брутто: {r[15]} {r[16]}\nНетто: {r[11]} {r[12]}\n"
                f"Дата оплаты клиентом: {r[17]}\nКуда оплатил клиент: {r[18]}\n"
                f"Дата оплаты поставщику: {r[13]}\nКак оплатили поставщику: {r[19]}"
            )
            await query.edit_message_text(f"📩 СМС менеджеру:\n{sms_manager}\n\n📩 СМС в таблицу:\n{sms_table}")
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
        per_message=True
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("list", list_requests))
    app.add_handler(CallbackQueryHandler(show_request, pattern="^req_"))
    app.run_polling()

if __name__ == "__main__":
    main()
