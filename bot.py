import os
import io
import json
import asyncio
import httpx
from dotenv import load_dotenv
load_dotenv()
from billing import can_process, increment_usage, get_status_text, PLAN_PRICES, LEMON_LINKS
from claude_assistant import ask_claude
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_daily_usage_store = []  # list of {date, input_tokens, output_tokens, cost_usd}
API_URL = os.environ.get("TRANSKRIB_API_URL", "https://transkrib-api.onrender.com")

ADMIN_ID = 5052641158
FREE_CHAT_LIMIT = 10  # messages per day for free users

WAITING_CUT = 1
WAITING_FORMAT = 2
WAITING_LANG = 3

CUT_LABELS = {'cut_5': '5 мин', 'cut_10': '10 мин', 'cut_15': '15 мин', 'cut_20': '20 мин', 'cut_30': '30 мин', 'cut_no': 'Без сокращения'}
FMT_LABELS = {'fmt_text': 'Только транскрипция', 'fmt_cut': 'Транскрипция + нарезка', 'fmt_srt': 'SRT субтитры', 'fmt_md': 'Markdown (.md)'}
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
        "🌐 transkrib.su · ✉️ info@transkrib.su\n\n"
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
        InlineKeyboardButton('5 мин', callback_data='cut_5'),
        InlineKeyboardButton('10 мин', callback_data='cut_10'),
        InlineKeyboardButton('15 мин', callback_data='cut_15'),
    ],[
        InlineKeyboardButton('20 мин', callback_data='cut_20'),
        InlineKeyboardButton('30 мин', callback_data='cut_30'),
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
        [InlineKeyboardButton('📝 Markdown (.md)', callback_data='fmt_md')],
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


def split_message(text: str, max_len: int = 4000) -> list:
    if len(text) <= max_len:
        return [text]
    parts = []
    while text:
        if len(text) <= max_len:
            parts.append(text)
            break
        split_at = text.rfind('\n', 0, max_len)
        if split_at == -1:
            split_at = max_len
        parts.append(text[:split_at])
        text = text[split_at:].lstrip('\n')
    return parts


async def _send_admin_log(context, text):
    """Send debug log to admin."""
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"🔧 LOG: {text[:500]}")
    except Exception:
        pass


PROGRESS_STAGES = {
    'waking':       '⬜⬜⬜⬜⬜  Запускаю сервер...',
    'pending':      '🟩⬜⬜⬜⬜  Сервер готов. Создаю задачу...',
    'downloading':  '🟩🟨⬜⬜⬜  Скачиваю аудио...',
    'transcribing': '🟩🟩🟨⬜⬜  Транскрибирую (Whisper AI)...',
    'formatting':   '🟩🟩🟩🟨⬜  Форматирую текст (Claude AI)...',
    'done':         '🟩🟩🟩🟩🟩  ✅ Готово!',
    'error':        '🟥🟥🟥🟥🟥  ❌ Ошибка',
}


async def _update_progress(context, chat_id, msg_id, stage_key):
    """Edit progress message to show current stage."""
    text = PROGRESS_STAGES.get(stage_key, stage_key)
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id, text=text
        )
    except Exception:
        pass  # ignore "message not modified" errors


async def handle_recut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает кнопки изменения длины нарезки."""
    query = update.callback_query
    await query.answer()
    if query.data == "recut_ok":
        await query.edit_message_reply_markup(reply_markup=None)
        return
    minutes = query.data.replace("recut_", "")
    await query.edit_message_reply_markup(reply_markup=None)
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=(
            f"🔄 Хорошо! Для нарезки на <b>{minutes} мин</b> отправьте ссылку заново "
            f"и выберите <b>{minutes} мин</b> в меню."
        ),
        parse_mode="HTML"
    )


async def handle_stop(update, context):
    """Handle Stop button — cancel the running task."""
    query = update.callback_query
    await query.answer()
    task_id = query.data.replace('stop_', '', 1)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(f"{API_URL}/api/tasks/{task_id}/cancel")
    except Exception:
        pass
    try:
        await query.edit_message_text(text="⛔ Обработка остановлена")
    except Exception:
        pass


async def handle_retry(update, context):
    """Handle retry button — reset conversation and prompt for new URL."""
    query = update.callback_query
    await query.answer()
    # Clear any saved URL
    context.user_data.clear()
    await query.edit_message_reply_markup(reply_markup=None)
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="🔄 Чат перезапущен!\n\nОтправь ссылку на YouTube видео заново."
    )


async def process_video(chat_id, url, context):
    cut_minutes = context.user_data.get('cut', 'cut_no').replace('cut_', '').replace('no', '0')
    fmt = context.user_data.get('fmt', 'fmt_text')
    language = context.user_data.get('lang', 'lang_auto').replace('lang_', '')

    try:
        # Send initial progress message (will be edited in-place)
        progress_msg = await context.bot.send_message(
            chat_id=chat_id, text=PROGRESS_STAGES['waking']
        )
        msg_id = progress_msg.message_id

        async with httpx.AsyncClient(timeout=300.0) as client:
            # Шаг 0: разбудить Render
            for attempt in range(5):
                try:
                    ping = await client.get(f"{API_URL}/api/health", timeout=15.0)
                    if ping.status_code < 500:
                        break
                except Exception:
                    pass
                await asyncio.sleep(8)

            await _update_progress(context, chat_id, msg_id, 'pending')

            # Шаг 1: создать задачу
            resp = await client.post(f"{API_URL}/api/tasks/create", json={
                "url": url,
                "cut_minutes": cut_minutes,
                "format": fmt,
                "language": language,
            })
            if resp.status_code != 200:
                await _update_progress(context, chat_id, msg_id, 'error')
                await context.bot.send_message(chat_id=chat_id, text=f"❌ Ошибка создания задачи: {resp.text[:200]}")
                return
            task_id = resp.json().get("task_id")

            stop_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⛔ Стоп", callback_data=f"stop_{task_id}")]])
            stop_msg = await context.bot.send_message(
                chat_id=chat_id,
                text="⏳ Обрабатываю... нажми Стоп чтобы отменить",
                reply_markup=stop_kb,
            )

            last_stage = None

            # Шаг 2: polling каждые 10 сек
            for attempt in range(60):
                await asyncio.sleep(10)
                try:
                    status_resp = await client.get(
                        f"{API_URL}/api/tasks/{task_id}/status",
                        timeout=30.0
                    )
                    if not status_resp.text.strip():
                        continue
                    data = status_resp.json()
                except (httpx.TimeoutException, json.JSONDecodeError):
                    continue

                status = data.get("status")
                stage = data.get("stage", status)

                # Update progress bar if stage changed
                if stage != last_stage and stage in PROGRESS_STAGES:
                    await _update_progress(context, chat_id, msg_id, stage)
                    last_stage = stage

                if status == "no_speech":
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                    except Exception:
                        pass
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=stop_msg.message_id)
                    except Exception:
                        pass
                    ns_text = data.get("transcription", "❌ Речь не обнаружена в видео.")
                    await context.bot.send_message(chat_id=chat_id, text=ns_text, parse_mode="HTML")
                    return
                if status == "done":
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                    except Exception:
                        pass
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=stop_msg.message_id)
                    except Exception:
                        pass
                    text = data.get("transcription", data.get("text", "Готово!"))
                    usage = data.get("claude_usage", {})
                    admin_suffix = ""
                    if usage and chat_id == ADMIN_ID:
                        inp = usage.get("input_tokens", 0)
                        out = usage.get("output_tokens", 0)
                        cost = usage.get("cost_usd", 0)
                        admin_suffix = f"\n\n<i>🔧 in:{inp} out:{out} ${cost:.4f}</i>"
                        _daily_usage_store.append({
                            "date": __import__("datetime").datetime.utcnow().strftime("%Y-%m-%d"),
                            "input_tokens": inp,
                            "output_tokens": out,
                            "cost_usd": cost,
                        })
                    if fmt == "fmt_md":
                        md_bytes = (text + admin_suffix.replace("<i>", "").replace("</i>", "")).encode("utf-8")
                        md_file = io.BytesIO(md_bytes)
                        md_file.name = "transcript.md"
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=md_file,
                            caption="✅ Транскрипция готова в формате Markdown!",
                            filename="transcript.md",
                        )
                    elif fmt == "fmt_srt":
                        srt_bytes = text.encode("utf-8")
                        srt_file = io.BytesIO(srt_bytes)
                        srt_file.name = "subtitles.srt"
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=srt_file,
                            caption="✅ SRT субтитры готовы! Импортируй в видеоредактор.",
                            filename="subtitles.srt",
                        )
                    else:
                        result_text = "✅ <b>Готово!</b>\n\n" + text + admin_suffix
                        try:
                            for part in split_message(result_text):
                                await context.bot.send_message(
                                    chat_id=chat_id, text=part, parse_mode="HTML"
                                )
                        except Exception:
                            for part in split_message("✅ Готово!\n\n" + text):
                                await context.bot.send_message(
                                    chat_id=chat_id, text=part
                                )
                    # Chunk warnings
                    chunk_warning = data.get("chunk_warning")
                    if chunk_warning:
                        warn_type = chunk_warning.get("type")
                        warn_msg = chunk_warning.get("message", "")
                        kept = chunk_warning.get("kept_minutes", 0)
                        suggestion = chunk_warning.get("suggestion_minutes", 0)
                        if warn_type == "loss":
                            warn_kb = InlineKeyboardMarkup([[
                                InlineKeyboardButton(f"📈 Увеличить до {suggestion} мин", callback_data=f"recut_{suggestion}"),
                                InlineKeyboardButton("✅ Оставить так", callback_data="recut_ok"),
                            ]])
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=(
                                    f"⚠️ <b>Важные моменты могут быть потеряны!</b>\n\n"
                                    f"{warn_msg}\n\n"
                                    f"📊 Вошло в нарезку: <b>{kept:.0f} мин</b>\n"
                                    f"💡 Рекомендую увеличить до: <b>{suggestion} мин</b>"
                                ),
                                parse_mode="HTML", reply_markup=warn_kb,
                            )
                        elif warn_type == "surplus":
                            warn_kb = InlineKeyboardMarkup([[
                                InlineKeyboardButton(f"📉 Сократить до {suggestion} мин", callback_data=f"recut_{suggestion}"),
                                InlineKeyboardButton("✅ Оставить так", callback_data="recut_ok"),
                            ]])
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=(
                                    f"✅ <b>Все ключевые моменты уложились!</b>\n\n"
                                    f"{warn_msg}\n\n"
                                    f"📊 Реальный объём: <b>{kept:.0f} мин</b>\n"
                                    f"💡 Можно сократить до: <b>{suggestion} мин</b>"
                                ),
                                parse_mode="HTML", reply_markup=warn_kb,
                            )
                    return
                elif status == "cancelled":
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                    except Exception:
                        pass
                    return
                elif status == "error":
                    await _update_progress(context, chat_id, msg_id, 'error')
                    error = data.get("error", "Неизвестная ошибка")
                    # Detect YouTube-specific errors
                    yt_keywords = ["youtube", "sign in", "bot", "cookie", "yt-dlp", "403"]
                    is_yt_error = any(kw in error.lower() for kw in yt_keywords)
                    if is_yt_error:
                        kb = InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔄 Перезапустить чат", callback_data="retry_fresh")
                        ]])
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=(
                                f"❌ Ошибка: {error[:300]}\n\n"
                                "⚠️ Не удалось скачать видео. Возможные причины:\n• Видео удалено или закрыто\n• Временная блокировка\n\nПопробуй позже или отправь другую ссылку."
                            ),
                            reply_markup=kb
                        )
                    else:
                        await context.bot.send_message(
                            chat_id=chat_id, text=f"❌ Ошибка: {error}"
                        )
                    return

            await _update_progress(context, chat_id, msg_id, 'error')
            await context.bot.send_message(chat_id=chat_id, text="⏱ Превышено время ожидания (10 мин). Попробуй более короткое видео.")

    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Ошибка: {str(e)[:200]}")


async def cmd_plan(update, context):
    tid = update.effective_user.id
    nl = chr(10)
    text = "💳 *Твой тариф*" + nl + nl + get_status_text(tid)
    text += nl + nl + "📦 *Тарифы:*" + nl
    text += "⭐ Базовый — 450₽ / $5 — безлимит, 10 дней" + nl
    text += "🚀 Стандарт — 1700₽ / $20 — безлимит, 30 дней" + nl
    text += "👑 Про — 8900₽ / $100 — безлимит, 1 год"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⭐ Базовый", callback_data="buy_starter"),
        InlineKeyboardButton("🚀 Стандарт", callback_data="buy_pro"),
        InlineKeyboardButton("👑 Про", callback_data="buy_annual"),
    ]])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def handle_buy(update, context):
    query = update.callback_query
    await query.answer()
    plan = query.data.replace("buy_", "")
    p = PLAN_PRICES.get(plan)
    if not p:
        return
    nl = chr(10)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"🇷🇺 {p['rub']}₽ — Оплатить (ЮКасса)", callback_data=f"currency_rub_{plan}"),
        InlineKeyboardButton(f"🇺🇸 ${p['usd']} — Pay (LemonSqueezy)", callback_data=f"currency_usd_{plan}"),
    ]])
    await query.edit_message_text(
        f"💳 *{p['name']}*" + nl + nl
        + f"🇷🇺 {p['rub']}₽ / 🇺🇸 ${p['usd']}" + nl + nl
        + "Выбери валюту оплаты:",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def handle_currency(update, context):
    query = update.callback_query
    await query.answer()
    _, currency, plan = query.data.split("_", 2)
    p = PLAN_PRICES.get(plan)
    if not p:
        return
    nl = chr(10)

    if currency == "usd":
        link = LEMON_LINKS.get(plan, "")
        await query.edit_message_text(
            f"💳 *{p['name']}* — ${p['usd']}/мес" + nl + nl
            + f"[Pay with LemonSqueezy]({link})" + nl + nl
            + "После оплаты напиши /plan для проверки.",
            parse_mode="Markdown",
        )
        return

    # ₽ — create YooKassa payment via API
    tid = query.from_user.id
    await query.edit_message_text("⏳ Создаю ссылку на оплату...")
    import httpx as _httpx
    try:
        # Wake up Render (free tier sleeps)
        async with _httpx.AsyncClient(timeout=60.0) as client:
            for _attempt in range(5):
                try:
                    _ping = await client.get(f"{API_URL}/api/health", timeout=15.0)
                    if _ping.status_code < 500:
                        break
                except Exception:
                    pass
                await asyncio.sleep(8)
            resp = await client.post(
                f"{API_URL}/api/bot/payments/yookassa/create",
                json={"telegram_id": tid, "plan": plan},
                timeout=60.0,
            )
        data = resp.json()
        if "error" in data:
            await context.bot.send_message(chat_id=tid, text=f"❌ Ошибка: {data['error']}")
            return
        payment_url = data["payment_url"]
        await context.bot.send_message(
            chat_id=tid,
            text=(
                f"💳 *{p['name']}* — {p['rub']}₽" + nl + nl
                + f"[🔗 Перейти к оплате]({payment_url})" + nl + nl
                + "После оплаты тариф активируется автоматически."
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        await context.bot.send_message(chat_id=tid, text=f"❌ Ошибка платежа: {str(e)[:200]}")


async def handle_show_plan(update, context):
    query = update.callback_query
    await query.answer()
    tid = query.from_user.id
    nl = chr(10)
    text = "💳 *Твой тариф*" + nl + nl + get_status_text(tid)
    text += nl + nl + "📦 *Тарифы:*" + nl
    text += "⭐ Базовый — 450₽ / $5 — безлимит, 10 дней" + nl
    text += "🚀 Стандарт — 1700₽ / $20 — безлимит, 30 дней" + nl
    text += "👑 Про — 8900₽ / $100 — безлимит, 1 год"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⭐ Базовый", callback_data="buy_starter"),
        InlineKeyboardButton("🚀 Стандарт", callback_data="buy_pro"),
        InlineKeyboardButton("👑 Про", callback_data="buy_annual"),
    ]])
    await query.edit_message_reply_markup(reply_markup=None)
    await context.bot.send_message(chat_id=tid, text=text, parse_mode="Markdown", reply_markup=kb)


async def cmd_help(update, context):
    text = (
        "🤖 *Transkrib SmartCut AI* — что умеет бот:\n\n"
        "🔗 *Отправь ссылку* на видео:\n"
        "YouTube, VK или Rutube\n\n"
        "⚙️ *Настройки обработки:*\n"
        "- ⏱ Длительность — 1, 3, 5, 10, 15 мин или без сокращения\n"
        "- 📄 Формат — только текст, текст+нарезка, SRT субтитры\n"
        "- 🌍 Язык — Авто, Русский, English\n\n"
        "🌍 *Поддерживаемые языки:*\n"
        "🇷🇺 Русский · 🇬🇧 English · 🇮🇳 हिन्दी\n"
        "🇨🇳 中文 · 🇰🇷 한국어 · 🇧🇷 Português\n\n"
        "💳 *Тарифы:*\n"
        "- 🆓 Пробный — бесплатно, 7 дней\n"
        "- ⭐ Базовый — 450₽ / $5, 10 дней\n"
        "- 🚀 Стандарт — 1700₽ / $20, 30 дней\n"
        "- 👑 Про — 8900₽ / $100, 365 дней\n\n"
        "📌 *Команды:*\n"
        "/start — главная страница\n"
        "/plan — мой тариф и подписка\n"
        "/help — эта справка\n"
        "/cancel — отменить обработку\n\n"
        "📧 *Контакты:*\n"
        "✉️ info@transkrib.su\n"
        "🛟 support@transkrib.su\n"
        "🌐 transkrib.su"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_cancel(update, context):
    await update.message.reply_text("❌ Обработка отменена. Отправь новую ссылку.")
    return ConversationHandler.END


async def cmd_stats(update, context):
    """Admin stats: usage, costs, users"""
    if update.effective_user.id != ADMIN_ID:
        return
    from claude_assistant import supabase
    try:
        usage = supabase.table("bot_api_usage").select("*").execute()
        rows = usage.data or []
        total_cost = sum(float(r["cost_usd"]) for r in rows)
        total_input = sum(r["input_tokens"] for r in rows)
        total_output = sum(r["output_tokens"] for r in rows)
        unique_users = len(set(r["telegram_id"] for r in rows))
        msg_count = len(rows)

        # Today stats
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_rows = [r for r in rows if r["created_at"][:10] == today]
        today_cost = sum(float(r["cost_usd"]) for r in today_rows)
        today_msgs = len(today_rows)

        text = (
            f"\U0001F4CA *Статистика API*\n\n"
            f"*Сегодня:*\n"
            f"  Запросов: {today_msgs}\n"
            f"  Расход: ${today_cost:.4f}\n\n"
            f"*Всего:*\n"
            f"  Запросов: {msg_count}\n"
            f"  Input: {total_input:,} tok\n"
            f"  Output: {total_output:,} tok\n"
            f"  Расход: ${total_cost:.4f}\n"
            f"  Пользователей: {unique_users}\n\n"
            f"*Баланс Anthropic:* проверь на platform.claude.com"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def handle_chat(update, context):
    user_text = update.message.text
    uid = update.effective_user.id

    # Rate limit: free users get FREE_CHAT_LIMIT/day, paid users unlimited
    if uid != ADMIN_ID:
        try:
            from claude_assistant import supabase
            from datetime import datetime, timezone
            # Check user plan
            user_row = supabase.table("bot_users").select("plan").eq("telegram_id", uid).execute()
            user_plan = user_row.data[0]["plan"] if user_row.data else "free"
            if user_plan == "free":
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                usage = supabase.table("bot_api_usage") \
                    .select("id") \
                    .eq("telegram_id", uid) \
                    .gte("created_at", today + "T00:00:00Z") \
                    .execute()
                if usage.data and len(usage.data) >= FREE_CHAT_LIMIT:
                    await update.message.reply_text(
                        f"\u26a0\ufe0f Лимит {FREE_CHAT_LIMIT} сообщений/день (Free).\n"
                        f"Обновите тариф для безлимита: /plan"
                    )
                    return
        except Exception as e:
            print(f"Rate limit check error: {e}")

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    answer = await ask_claude(user_text, project="transkrib_bot", telegram_id=uid)
    await update.message.reply_text(answer)


async def _daily_cost_summary(context):
    """Send daily Claude cost summary to admin at 20:00 MSK."""
    from datetime import datetime, timezone, timedelta
    msk_now = datetime.now(timezone.utc) + timedelta(hours=3)
    today = msk_now.strftime("%Y-%m-%d")
    total_inp = total_out = total_cost = 0.0
    for rec in list(_daily_usage_store):
        if rec.get("date") == today:
            total_inp += rec.get("input_tokens", 0)
            total_out += rec.get("output_tokens", 0)
            total_cost += rec.get("cost_usd", 0.0)
    warning = "\n⚠️ Высокие расходы!" if total_cost > 5 else ""
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"📊 Сводка за {today}:\n"
            f"Input: {int(total_inp):,} tok\n"
            f"Output: {int(total_out):,} tok\n"
            f"Стоимость: ${total_cost:.4f}{warning}"
        ),
    )


async def post_init(app):
    cookies_updated_at = os.environ.get("COOKIES_UPDATED_AT", "").strip()
    if cookies_updated_at:
        try:
            from datetime import datetime, timezone, timedelta
            updated = datetime.strptime(cookies_updated_at, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            days_old = (datetime.now(timezone.utc) - updated).days
            if days_old > 80:
                await app.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"⚠️ Cookies YouTube скоро протухнут! Обнови их в Render Secret Files. (возраст: {days_old} дней)"
                )
        except Exception:
            pass
    await app.bot.set_my_commands([
        BotCommand("start",  "🚀 Главная — выбор языка"),
        BotCommand("plan",   "💳 Мой тариф и подписка"),
        BotCommand("help",   "❓ Помощь и инструкция"),
        BotCommand("cancel", "❌ Отменить обработку"),
    ])


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    conv_handler = ConversationHandler(
        per_message=False,
        entry_points=[MessageHandler(filters.Regex(r"https?://"), handle_url_start)],
        states={
            WAITING_CUT: [CallbackQueryHandler(handle_cut, pattern="^cut_")],
            WAITING_FORMAT: [CallbackQueryHandler(handle_format, pattern="^fmt_")],
            WAITING_LANG: [CallbackQueryHandler(handle_lang_choice, pattern="^lang_")],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CallbackQueryHandler(handle_buy, pattern="^buy_"))
    app.add_handler(CallbackQueryHandler(handle_currency, pattern="^currency_"))
    app.add_handler(CallbackQueryHandler(handle_recut, pattern="^recut_"))
    app.add_handler(CallbackQueryHandler(handle_stop, pattern="^stop_"))
    app.add_handler(CallbackQueryHandler(handle_retry, pattern="^retry_fresh$"))
    app.add_handler(CallbackQueryHandler(handle_show_plan, pattern="^show_plan$"))
    app.add_handler(CallbackQueryHandler(handle_language, pattern="^lang_(?:ru|en|hi|zh|ko|pt)$"))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.Regex(r'https?://'),
        handle_chat
    ))
    job_queue = app.job_queue
    if job_queue:
        from datetime import time as _time
        job_queue.run_daily(_daily_cost_summary, time=_time(17, 0, 0))  # 17:00 UTC = 20:00 MSK
    print("Bot started!")
    app.run_polling()


if __name__ == "__main__":
    main()
