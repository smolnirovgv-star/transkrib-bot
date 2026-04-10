import os
import json
import asyncio
import httpx
from dotenv import load_dotenv
load_dotenv()
from billing import can_process, increment_usage, get_status_text
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_URL = os.environ.get("TRANSKRIB_API_URL", "https://transkrib-api.onrender.com")

WAITING_CUT = 1
WAITING_FORMAT = 2
WAITING_LANG = 3

CUT_LABELS = {'cut_1': '1 мин', 'cut_3': '3 мин', 'cut_5': '5 мин', 'cut_no': 'Без сокращения'}
FMT_LABELS = {'fmt_text': 'Только транскрипция', 'fmt_cut': 'Транскрипция + нарезка', 'fmt_srt': 'SRT субтитры'}
LANG_LABELS = {'lang_auto': '🔄 Авто', 'lang_ru': '🇷🇺 Русский', 'lang_en': '🇬🇧 English'}

LANG_MESSAGES = {
    'lang_ru': '🇷🇺 Язык установлен: Русский\n\nОтправь ссылку на видео YouTube, VK или Rutube!',
    'lang_en': '🇬🇧 Language set: English\n\nSend a YouTube, VK or Rutube link!',
    'lang_hi': '🇮🇳 Hindi selected\n\nSend a YouTube, VK or Rutube link!',
    'lang_zh': '🇨🇳 已选择中文\n\n请发送YouTube、VK或Rutube链接！',
    'lang_ko': '🇰🇷 한국어 선택됨\n\nYouTube, VK 또는 Rutube 링크를 보내주세요!',
    'lang_pt': '🇧🇷 Português selecionado\n\nEnvie um link do YouTube, VK ou Rutube!',
}


async def handle_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    msg = LANG_MESSAGES.get(query.data, "Send a video link!")
    try:
        await query.edit_message_text(text=msg)
    except Exception:
        await context.bot.send_message(chat_id=query.message.chat_id, text=msg)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
        InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
        InlineKeyboardButton("🇮🇳 हिन्दी", callback_data="lang_hi"),
    ],[
        InlineKeyboardButton("🇨🇳 中文", callback_data="lang_zh"),
        InlineKeyboardButton("🇰🇷 한국어", callback_data="lang_ko"),
        InlineKeyboardButton("🇧🇷 Português", callback_data="lang_pt"),
    ],[
        InlineKeyboardButton("💳 Мой тариф", callback_data="show_plan"),
    ]]
    await update.message.reply_text(
        "👋 Привет! Я Transkrib SmartCut AI Bot.\n\n"
        "✂️ Отправь мне ссылку на видео YouTube, VK или Rutube — "
        "я транскрибирую его и сделаю умную нарезку ключевых моментов!\n\n"
        "🌍 Choose your language:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_url_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not url.startswith('http'):
        await update.message.reply_text(
            '❌ Пожалуйста отправь ссылку на видео.\nПоддерживаются: YouTube, VK, Rutube'
        )
        return ConversationHandler.END
    context.user_data['url'] = url
    keyboard = [[
        InlineKeyboardButton('1 мин', callback_data='cut_1'),
        InlineKeyboardButton('3 мин', callback_data='cut_3'),
        InlineKeyboardButton('5 мин', callback_data='cut_5'),
        InlineKeyboardButton('Без сокращения', callback_data='cut_no'),
    ]]
    await update.message.reply_text(
        '⏱ До скольки минут сократить видео?',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WAITING_CUT


async def handle_cut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['cut'] = query.data
    keyboard = [
        [InlineKeyboardButton('Только транскрипция', callback_data='fmt_text')],
        [InlineKeyboardButton('Транскрипция + нарезка', callback_data='fmt_cut')],
        [InlineKeyboardButton('SRT субтитры', callback_data='fmt_srt')],
    ]
    await query.edit_message_text(
        '📄 Что создать?',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WAITING_FORMAT


async def handle_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['fmt'] = query.data
    keyboard = [[
        InlineKeyboardButton('🔄 Авто', callback_data='lang_auto'),
        InlineKeyboardButton('🇷🇺 Русский', callback_data='lang_ru'),
        InlineKeyboardButton('🇬🇧 English', callback_data='lang_en'),
    ]]
    await query.edit_message_text(
        '🌍 Язык транскрипции?',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WAITING_LANG


async def handle_lang_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['lang'] = query.data
    cut = CUT_LABELS.get(context.user_data.get('cut', ''), '?')
    fmt = FMT_LABELS.get(context.user_data.get('fmt', ''), '?')
    lang = LANG_LABELS.get(query.data, '?')
    url = context.user_data.get('url', '')
    await query.edit_message_text(
        '✅ Настройки:\n'
        '- Длительность: ' + cut + '\n'
        '- Формат: ' + fmt + '\n'
        '- Язык: ' + lang + '\n\n'
        '⏳ Начинаю обработку...'
    )
    await process_video(query.message.chat_id, url, context)
    return ConversationHandler.END


async def process_video(chat_id, url, context):
    cut_minutes = context.user_data.get('cut', 'cut_no').replace('cut_', '').replace('no', '0')
    fmt = context.user_data.get('fmt', 'fmt_text')
    language = context.user_data.get('lang', 'lang_auto').replace('lang_', '')

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Шаг 0: разбудить Render (может занять 30 сек)
            await context.bot.send_message(chat_id=chat_id, text='🔄 Запускаю сервер обработки...')
            for attempt in range(5):
                try:
                    ping = await client.get(f"{API_URL}/api/health", timeout=15.0)
                    if ping.status_code < 500:
                        break
                except Exception:
                    pass
                await asyncio.sleep(8)

            await context.bot.send_message(
                chat_id=chat_id,
                text='⏳ Обрабатываю видео...\nЭто займёт 1-3 минуты. Пожалуйста подожди!'
            )

            # Шаг 1: создать задачу
            resp = await client.post(f"{API_URL}/api/tasks/create", json={
                "url": url,
                "cut_minutes": cut_minutes,
                "format": fmt,
                "language": language,
            })
            if resp.status_code != 200:
                await context.bot.send_message(chat_id=chat_id, text=f"❌ Ошибка создания задачи: {resp.text[:200]}")
                return
            task_id = resp.json().get("task_id")

            # Шаг 2: polling каждые 10 сек
            for attempt in range(30):
                await asyncio.sleep(10)
                try:
                    status_resp = await client.get(
                        f"{API_URL}/api/tasks/{task_id}/status",
                        timeout=30.0
                    )
                    if not status_resp.text.strip():
                        continue  # пустой ответ — Render просыпается, ждём
                    data = status_resp.json()
                except (httpx.TimeoutException, json.JSONDecodeError):
                    continue  # временная ошибка — продолжаем polling

                status = data.get("status")

                if status == "done":
                    text = data.get("transcription", data.get("text", "Готово!"))
                    await context.bot.send_message(chat_id=chat_id, text=f"✅ Готово!\n\n{text[:3500]}")
                    return
                elif status == "error":
                    error = data.get("error", "Неизвестная ошибка")
                    await context.bot.send_message(chat_id=chat_id, text=f"❌ Ошибка: {error}")
                    return
                # status == "processing" — продолжаем ждать

            await context.bot.send_message(chat_id=chat_id, text="⏱ Превышено время ожидания (5 мин). Попробуй более короткое видео.")

    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Ошибка: {str(e)[:200]}")


async def cmd_plan(update, context):
    tid = update.effective_user.id
    nl = chr(10)
    text = "💳 *Твой тариф*" + nl + nl + get_status_text(tid)
    text += nl + nl + "📦 *Тарифы:*" + nl
    text += "🚀 Starter — $9/мес (30 видео)" + nl
    text += "💼 Pro — $29/мес (безлимит)" + nl
    text += "👑 Annual — $99/год (безлимит)"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🚀 $9/мес", callback_data="buy_starter"),
        InlineKeyboardButton("💼 $29/мес", callback_data="buy_pro"),
        InlineKeyboardButton("👑 $99/год", callback_data="buy_annual"),
    ]])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def handle_buy(update, context):
    query = update.callback_query
    await query.answer()
    plan = query.data.replace("buy_", "")
    links = {
        "starter": "https://transkrib.lemonsqueezy.com/buy/starter",
        "pro":     "https://transkrib.lemonsqueezy.com/buy/pro",
        "annual":  "https://transkrib.lemonsqueezy.com/buy/annual",
    }
    prices = {"starter": "$9/мес", "pro": "$29/мес", "annual": "$99/год"}
    nl = chr(10)
    await query.edit_message_text(
        f"💳 *{plan.capitalize()}* — {prices.get(plan)}" + nl + nl
        + f"[Перейти к оплате]({links.get(plan)})" + nl + nl
        + "После оплаты напиши /plan для проверки.",
        parse_mode="Markdown"
    )


async def handle_show_plan(update, context):
    query = update.callback_query
    await query.answer()
    tid = query.from_user.id
    nl = chr(10)
    text = "💳 *Твой тариф*" + nl + nl + get_status_text(tid)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🚀 $9/мес", callback_data="buy_starter"),
        InlineKeyboardButton("💼 $29/мес", callback_data="buy_pro"),
        InlineKeyboardButton("👑 $99/год", callback_data="buy_annual"),
    ]])
    await query.edit_message_reply_markup(reply_markup=None)
    await context.bot.send_message(chat_id=tid, text=text, parse_mode="Markdown", reply_markup=kb)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Как пользоваться Transkrib Bot:*\n\n"
        "1. Скопируй ссылку на видео\n"
        "2. Вставь её в чат\n"
        "3. Выбери настройки\n"
        "4. Получи транскрипцию и нарезку!\n\n"
        "🔗 Поддерживаются: YouTube, VK, Rutube\n\n"
        "💻 Скачать приложение: https://transkrib.su",
        parse_mode="Markdown"
    )


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"https?://"), handle_url_start)],
        states={
            WAITING_CUT: [CallbackQueryHandler(handle_cut, pattern="^cut_")],
            WAITING_FORMAT: [CallbackQueryHandler(handle_format, pattern="^fmt_")],
            WAITING_LANG: [CallbackQueryHandler(handle_lang_choice, pattern="^lang_")],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(handle_language, pattern="^lang_(?:ru|en|hi|zh|ko|pt)$"))
    print("Bot started!")
    app.run_polling()


if __name__ == "__main__":
    main()
