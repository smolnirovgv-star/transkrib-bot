import os
import json
import asyncio
import httpx
from dotenv import load_dotenv
load_dotenv()
from billing import can_process, increment_usage, get_status_text
from claude_assistant import ask_claude
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_URL = os.environ.get("TRANSKRIB_API_URL", "https://transkrib-api.onrender.com")

ADMIN_ID = 5052641158
FREE_CHAT_LIMIT = 10  # messages per day for free users

WAITING_CUT = 1
WAITING_FORMAT = 2
WAITING_LANG = 3

CUT_LABELS = {'cut_1': '1 Ð¼Ð¸Ð½', 'cut_3': '3 Ð¼Ð¸Ð½', 'cut_5': '5 Ð¼Ð¸Ð½', 'cut_no': 'ÐÐµÐ· ÑÐ¾ÐºÑÐ°ÑÐµÐ½Ð¸Ñ'}
FMT_LABELS = {'fmt_text': 'Ð¢Ð¾Ð»ÑÐºÐ¾ ÑÑÐ°Ð½ÑÐºÑÐ¸Ð¿ÑÐ¸Ñ', 'fmt_cut': 'Ð¢ÑÐ°Ð½ÑÐºÑÐ¸Ð¿ÑÐ¸Ñ + Ð½Ð°ÑÐµÐ·ÐºÐ°', 'fmt_srt': 'SRT ÑÑÐ±ÑÐ¸ÑÑÑ'}
LANG_LABELS = {'lang_auto': 'ð ÐÐ²ÑÐ¾', 'lang_ru': 'ð·ðº Ð ÑÑÑÐºÐ¸Ð¹', 'lang_en': 'ð¬ð§ English'}

LANG_MESSAGES = {
    'lang_ru': 'ð·ðº Ð¯Ð·ÑÐº ÑÑÑÐ°Ð½Ð¾Ð²Ð»ÐµÐ½: Ð ÑÑÑÐºÐ¸Ð¹\n\nÐÑÐ¿ÑÐ°Ð²Ñ ÑÑÑÐ»ÐºÑ Ð½Ð° Ð²Ð¸Ð´ÐµÐ¾ YouTube, VK Ð¸Ð»Ð¸ Rutube!',
    'lang_en': 'ð¬ð§ Language set: English\n\nSend a YouTube, VK or Rutube link!',
    'lang_hi': 'ð®ð³ Hindi selected\n\nSend a YouTube, VK or Rutube link!',
    'lang_zh': 'ð¨ð³ å·²éæ©ä¸­æ\n\nè¯·åéYouTubeãVKæRutubeé¾æ¥ï¼',
    'lang_ko': 'ð°ð· íêµ­ì´ ì íë¨\n\nYouTube, VK ëë Rutube ë§í¬ë¥¼ ë³´ë´ì£¼ì¸ì!',
    'lang_pt': 'ð§ð· PortuguÃªs selecionado\n\nEnvie um link do YouTube, VK ou Rutube!',
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
        InlineKeyboardButton("ð·ðº Ð ÑÑÑÐºÐ¸Ð¹", callback_data="lang_ru"),
        InlineKeyboardButton("ð¬ð§ English", callback_data="lang_en"),
        InlineKeyboardButton("ð®ð³ à¤¹à¤¿à¤¨à¥à¤¦à¥", callback_data="lang_hi"),
    ],[
        InlineKeyboardButton("ð¨ð³ ä¸­æ", callback_data="lang_zh"),
        InlineKeyboardButton("ð°ð· íêµ­ì´", callback_data="lang_ko"),
        InlineKeyboardButton("ð§ð· PortuguÃªs", callback_data="lang_pt"),
    ],[
        InlineKeyboardButton("ð³ ÐÐ¾Ð¹ ÑÐ°ÑÐ¸Ñ", callback_data="show_plan"),
    ]]
    await update.message.reply_text(
        "ð ÐÑÐ¸Ð²ÐµÑ! Ð¯ Transkrib SmartCut AI Bot.\n\n"
        "âï¸ ÐÑÐ¿ÑÐ°Ð²Ñ Ð¼Ð½Ðµ ÑÑÑÐ»ÐºÑ Ð½Ð° Ð²Ð¸Ð´ÐµÐ¾ YouTube, VK Ð¸Ð»Ð¸ Rutube â "
        "Ñ ÑÑÐ°Ð½ÑÐºÑÐ¸Ð±Ð¸ÑÑÑ ÐµÐ³Ð¾ Ð¸ ÑÐ´ÐµÐ»Ð°Ñ ÑÐ¼Ð½ÑÑ Ð½Ð°ÑÐµÐ·ÐºÑ ÐºÐ»ÑÑÐµÐ²ÑÑ Ð¼Ð¾Ð¼ÐµÐ½ÑÐ¾Ð²!\n\n"
        "ð Choose your language:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_url_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not url.startswith('http'):
        await update.message.reply_text(
            'â ÐÐ¾Ð¶Ð°Ð»ÑÐ¹ÑÑÐ° Ð¾ÑÐ¿ÑÐ°Ð²Ñ ÑÑÑÐ»ÐºÑ Ð½Ð° Ð²Ð¸Ð´ÐµÐ¾.\nÐÐ¾Ð´Ð´ÐµÑÐ¶Ð¸Ð²Ð°ÑÑÑÑ: YouTube, VK, Rutube'
        )
        return ConversationHandler.END
    context.user_data['url'] = url
    keyboard = [[
        InlineKeyboardButton('1 Ð¼Ð¸Ð½', callback_data='cut_1'),
        InlineKeyboardButton('3 Ð¼Ð¸Ð½', callback_data='cut_3'),
        InlineKeyboardButton('5 Ð¼Ð¸Ð½', callback_data='cut_5'),
        InlineKeyboardButton('ÐÐµÐ· ÑÐ¾ÐºÑÐ°ÑÐµÐ½Ð¸Ñ', callback_data='cut_no'),
    ]]
    await update.message.reply_text(
        'â± ÐÐ¾ ÑÐºÐ¾Ð»ÑÐºÐ¸ Ð¼Ð¸Ð½ÑÑ ÑÐ¾ÐºÑÐ°ÑÐ¸ÑÑ Ð²Ð¸Ð´ÐµÐ¾?',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WAITING_CUT


async def handle_cut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['cut'] = query.data
    keyboard = [
        [InlineKeyboardButton('Ð¢Ð¾Ð»ÑÐºÐ¾ ÑÑÐ°Ð½ÑÐºÑÐ¸Ð¿ÑÐ¸Ñ', callback_data='fmt_text')],
        [InlineKeyboardButton('Ð¢ÑÐ°Ð½ÑÐºÑÐ¸Ð¿ÑÐ¸Ñ + Ð½Ð°ÑÐµÐ·ÐºÐ°', callback_data='fmt_cut')],
        [InlineKeyboardButton('SRT ÑÑÐ±ÑÐ¸ÑÑÑ', callback_data='fmt_srt')],
    ]
    await query.edit_message_text(
        'ð Ð§ÑÐ¾ ÑÐ¾Ð·Ð´Ð°ÑÑ?',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WAITING_FORMAT


async def handle_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['fmt'] = query.data
    keyboard = [[
        InlineKeyboardButton('ð ÐÐ²ÑÐ¾', callback_data='lang_auto'),
        InlineKeyboardButton('ð·ðº Ð ÑÑÑÐºÐ¸Ð¹', callback_data='lang_ru'),
        InlineKeyboardButton('ð¬ð§ English', callback_data='lang_en'),
    ]]
    await query.edit_message_text(
        'ð Ð¯Ð·ÑÐº ÑÑÐ°Ð½ÑÐºÑÐ¸Ð¿ÑÐ¸Ð¸?',
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
        'â ÐÐ°ÑÑÑÐ¾Ð¹ÐºÐ¸:\n'
        '- ÐÐ»Ð¸ÑÐµÐ»ÑÐ½Ð¾ÑÑÑ: ' + cut + '\n'
        '- Ð¤Ð¾ÑÐ¼Ð°Ñ: ' + fmt + '\n'
        '- Ð¯Ð·ÑÐº: ' + lang + '\n\n'
        'â³ ÐÐ°ÑÐ¸Ð½Ð°Ñ Ð¾Ð±ÑÐ°Ð±Ð¾ÑÐºÑ...'
    )
    await process_video(query.message.chat_id, url, context)
    return ConversationHandler.END


async def process_video(chat_id, url, context):
    cut_minutes = context.user_data.get('cut', 'cut_no').replace('cut_', '').replace('no', '0')
    fmt = context.user_data.get('fmt', 'fmt_text')
    language = context.user_data.get('lang', 'lang_auto').replace('lang_', '')

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            # Ð¨Ð°Ð³ 0: ÑÐ°Ð·Ð±ÑÐ´Ð¸ÑÑ Render (Ð¼Ð¾Ð¶ÐµÑ Ð·Ð°Ð½ÑÑÑ 30 ÑÐµÐº)
            await context.bot.send_message(chat_id=chat_id, text='ð ÐÐ°Ð¿ÑÑÐºÐ°Ñ ÑÐµÑÐ²ÐµÑ Ð¾Ð±ÑÐ°Ð±Ð¾ÑÐºÐ¸...')
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
                text='â³ ÐÐ±ÑÐ°Ð±Ð°ÑÑÐ²Ð°Ñ Ð²Ð¸Ð´ÐµÐ¾...\nÐ­ÑÐ¾ Ð·Ð°Ð¹Ð¼ÑÑ 1-3 Ð¼Ð¸Ð½ÑÑÑ. ÐÐ¾Ð¶Ð°Ð»ÑÐ¹ÑÑÐ° Ð¿Ð¾Ð´Ð¾Ð¶Ð´Ð¸!'
            )

            # Ð¨Ð°Ð³ 1: ÑÐ¾Ð·Ð´Ð°ÑÑ Ð·Ð°Ð´Ð°ÑÑ
            resp = await client.post(f"{API_URL}/api/tasks/create", json={
                "url": url,
                "cut_minutes": cut_minutes,
                "format": fmt,
                "language": language,
            })
            if resp.status_code != 200:
                await context.bot.send_message(chat_id=chat_id, text=f"â ÐÑÐ¸Ð±ÐºÐ° ÑÐ¾Ð·Ð´Ð°Ð½Ð¸Ñ Ð·Ð°Ð´Ð°ÑÐ¸: {resp.text[:200]}")
                return
            task_id = resp.json().get("task_id")

            # Ð¨Ð°Ð³ 2: polling ÐºÐ°Ð¶Ð´ÑÐµ 10 ÑÐµÐº
            for attempt in range(30):
                await asyncio.sleep(10)
                try:
                    status_resp = await client.get(
                        f"{API_URL}/api/tasks/{task_id}/status",
                        timeout=30.0
                    )
                    if not status_resp.text.strip():
                        continue  # Ð¿ÑÑÑÐ¾Ð¹ Ð¾ÑÐ²ÐµÑ â Render Ð¿ÑÐ¾ÑÑÐ¿Ð°ÐµÑÑÑ, Ð¶Ð´ÑÐ¼
                    data = status_resp.json()
                except (httpx.TimeoutException, json.JSONDecodeError):
                    continue  # Ð²ÑÐµÐ¼ÐµÐ½Ð½Ð°Ñ Ð¾ÑÐ¸Ð±ÐºÐ° â Ð¿ÑÐ¾Ð´Ð¾Ð»Ð¶Ð°ÐµÐ¼ polling

                status = data.get("status")

                if status == "done":
                    text = data.get("transcription", data.get("text", "ÐÐ¾ÑÐ¾Ð²Ð¾!"))
                    await context.bot.send_message(chat_id=chat_id, text=f"â ÐÐ¾ÑÐ¾Ð²Ð¾!\n\n{text[:3500]}")
                    return
                elif status == "error":
                    error = data.get("error", "ÐÐµÐ¸Ð·Ð²ÐµÑÑÐ½Ð°Ñ Ð¾ÑÐ¸Ð±ÐºÐ°")
                    await context.bot.send_message(chat_id=chat_id, text=f"â ÐÑÐ¸Ð±ÐºÐ°: {error}")
                    return
                # status == "processing" â Ð¿ÑÐ¾Ð´Ð¾Ð»Ð¶Ð°ÐµÐ¼ Ð¶Ð´Ð°ÑÑ

            await context.bot.send_message(chat_id=chat_id, text="â± ÐÑÐµÐ²ÑÑÐµÐ½Ð¾ Ð²ÑÐµÐ¼Ñ Ð¾Ð¶Ð¸Ð´Ð°Ð½Ð¸Ñ (5 Ð¼Ð¸Ð½). ÐÐ¾Ð¿ÑÐ¾Ð±ÑÐ¹ Ð±Ð¾Ð»ÐµÐµ ÐºÐ¾ÑÐ¾ÑÐºÐ¾Ðµ Ð²Ð¸Ð´ÐµÐ¾.")

    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"â ÐÑÐ¸Ð±ÐºÐ°: {str(e)[:200]}")


async def cmd_plan(update, context):
    tid = update.effective_user.id
    nl = chr(10)
    text = "ð³ *Ð¢Ð²Ð¾Ð¹ ÑÐ°ÑÐ¸Ñ*" + nl + nl + get_status_text(tid)
    text += nl + nl + "ð¦ *Ð¢Ð°ÑÐ¸ÑÑ:*" + nl
    text += "ð Starter â $9/Ð¼ÐµÑ (30 Ð²Ð¸Ð´ÐµÐ¾)" + nl
    text += "ð¼ Pro â $29/Ð¼ÐµÑ (Ð±ÐµÐ·Ð»Ð¸Ð¼Ð¸Ñ)" + nl
    text += "ð Annual â $99/Ð³Ð¾Ð´ (Ð±ÐµÐ·Ð»Ð¸Ð¼Ð¸Ñ)"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("ð $9/Ð¼ÐµÑ", callback_data="buy_starter"),
        InlineKeyboardButton("ð¼ $29/Ð¼ÐµÑ", callback_data="buy_pro"),
        InlineKeyboardButton("ð $99/Ð³Ð¾Ð´", callback_data="buy_annual"),
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
    prices = {"starter": "$9/Ð¼ÐµÑ", "pro": "$29/Ð¼ÐµÑ", "annual": "$99/Ð³Ð¾Ð´"}
    nl = chr(10)
    await query.edit_message_text(
        f"ð³ *{plan.capitalize()}* â {prices.get(plan)}" + nl + nl
        + f"[ÐÐµÑÐµÐ¹ÑÐ¸ Ðº Ð¾Ð¿Ð»Ð°ÑÐµ]({links.get(plan)})" + nl + nl
        + "ÐÐ¾ÑÐ»Ðµ Ð¾Ð¿Ð»Ð°ÑÑ Ð½Ð°Ð¿Ð¸ÑÐ¸ /plan Ð´Ð»Ñ Ð¿ÑÐ¾Ð²ÐµÑÐºÐ¸.",
        parse_mode="Markdown"
    )


async def handle_show_plan(update, context):
    query = update.callback_query
    await query.answer()
    tid = query.from_user.id
    nl = chr(10)
    text = "ð³ *Ð¢Ð²Ð¾Ð¹ ÑÐ°ÑÐ¸Ñ*" + nl + nl + get_status_text(tid)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("ð $9/Ð¼ÐµÑ", callback_data="buy_starter"),
        InlineKeyboardButton("ð¼ $29/Ð¼ÐµÑ", callback_data="buy_pro"),
        InlineKeyboardButton("ð $99/Ð³Ð¾Ð´", callback_data="buy_annual"),
    ]])
    await query.edit_message_reply_markup(reply_markup=None)
    await context.bot.send_message(chat_id=tid, text=text, parse_mode="Markdown", reply_markup=kb)


async def cmd_help(update, context):
    text = (
        "ð¤ *Transkrib SmartCut AI* â ÑÑÐ¾ ÑÐ¼ÐµÐµÑ Ð±Ð¾Ñ:\n\n"
        "ð *ÐÑÐ¿ÑÐ°Ð²Ñ ÑÑÑÐ»ÐºÑ* Ð½Ð° Ð²Ð¸Ð´ÐµÐ¾:\n"
        "YouTube, VK Ð¸Ð»Ð¸ Rutube\n\n"
        "âï¸ *ÐÐ°ÑÑÑÐ¾Ð¹ÐºÐ¸ Ð¾Ð±ÑÐ°Ð±Ð¾ÑÐºÐ¸:*\n"
        "â¢ â± ÐÐ»Ð¸ÑÐµÐ»ÑÐ½Ð¾ÑÑÑ â 1, 3, 5 Ð¼Ð¸Ð½ Ð¸Ð»Ð¸ Ð±ÐµÐ· ÑÐ¾ÐºÑÐ°ÑÐµÐ½Ð¸Ñ\n"
        "â¢ ð Ð¤Ð¾ÑÐ¼Ð°Ñ â ÑÐ¾Ð»ÑÐºÐ¾ ÑÐµÐºÑÑ, ÑÐµÐºÑÑ+Ð½Ð°ÑÐµÐ·ÐºÐ°, SRT ÑÑÐ±ÑÐ¸ÑÑÑ\n"
        "â¢ ð Ð¯Ð·ÑÐº â ÐÐ²ÑÐ¾, Ð ÑÑÑÐºÐ¸Ð¹, English\n\n"
        "ð³ *Ð¢Ð°ÑÐ¸ÑÑ:*\n"
        "â¢ ð Free â 3 Ð²Ð¸Ð´ÐµÐ¾ Ð±ÐµÑÐ¿Ð»Ð°ÑÐ½Ð¾\n"
        "â¢ ð Starter â $9/Ð¼ÐµÑ (30 Ð²Ð¸Ð´ÐµÐ¾)\n"
        "â¢ ð¼ Pro â $29/Ð¼ÐµÑ (Ð±ÐµÐ·Ð»Ð¸Ð¼Ð¸Ñ)\n"
        "â¢ ð Annual â $99/Ð³Ð¾Ð´ (Ð±ÐµÐ·Ð»Ð¸Ð¼Ð¸Ñ)\n\n"
        "ð *ÐÐ¾Ð¼Ð°Ð½Ð´Ñ:*\n"
        "/start â Ð³Ð»Ð°Ð²Ð½Ð°Ñ ÑÑÑÐ°Ð½Ð¸ÑÐ°\n"
        "/plan â Ð¼Ð¾Ð¹ ÑÐ°ÑÐ¸Ñ\n"
        "/help â ÑÑÐ° ÑÐ¿ÑÐ°Ð²ÐºÐ°\n"
        "/cancel â Ð¾ÑÐ¼ÐµÐ½Ð¸ÑÑ Ð¾Ð±ÑÐ°Ð±Ð¾ÑÐºÑ"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_cancel(update, context):
    await update.message.reply_text("â ÐÐ±ÑÐ°Ð±Ð¾ÑÐºÐ° Ð¾ÑÐ¼ÐµÐ½ÐµÐ½Ð°. ÐÑÐ¿ÑÐ°Ð²Ñ Ð½Ð¾Ð²ÑÑ ÑÑÑÐ»ÐºÑ.")
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
            f"\U0001F4CA *Ð¡ÑÐ°ÑÐ¸ÑÑÐ¸ÐºÐ° API*\n\n"
            f"*Ð¡ÐµÐ³Ð¾Ð´Ð½Ñ:*\n"
            f"  ÐÐ°Ð¿ÑÐ¾ÑÐ¾Ð²: {today_msgs}\n"
            f"  Ð Ð°ÑÑÐ¾Ð´: ${today_cost:.4f}\n\n"
            f"*ÐÑÐµÐ³Ð¾:*\n"
            f"  ÐÐ°Ð¿ÑÐ¾ÑÐ¾Ð²: {msg_count}\n"
            f"  Input: {total_input:,} tok\n"
            f"  Output: {total_output:,} tok\n"
            f"  Ð Ð°ÑÑÐ¾Ð´: ${total_cost:.4f}\n"
            f"  ÐÐ¾Ð»ÑÐ·Ð¾Ð²Ð°ÑÐµÐ»ÐµÐ¹: {unique_users}\n\n"
            f"*ÐÐ°Ð»Ð°Ð½Ñ Anthropic:* Ð¿ÑÐ¾Ð²ÐµÑÑ Ð½Ð° platform.claude.com"
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
                        f"\u26a0\ufe0f ÐÐ¸Ð¼Ð¸Ñ {FREE_CHAT_LIMIT} ÑÐ¾Ð¾Ð±ÑÐµÐ½Ð¸Ð¹/Ð´ÐµÐ½Ñ (Free).\n"
                        f"ÐÐ±Ð½Ð¾Ð²Ð¸ÑÐµ ÑÐ°ÑÐ¸Ñ Ð´Ð»Ñ Ð±ÐµÐ·Ð»Ð¸Ð¼Ð¸ÑÐ°: /plan"
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


async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start",  "ð ÐÐ»Ð°Ð²Ð½Ð°Ñ â Ð²ÑÐ±Ð¾Ñ ÑÐ·ÑÐºÐ°"),
        BotCommand("plan",   "ð³ ÐÐ¾Ð¹ ÑÐ°ÑÐ¸Ñ Ð¸ Ð¿Ð¾Ð´Ð¿Ð¸ÑÐºÐ°"),
        BotCommand("help",   "â ÐÐ¾Ð¼Ð¾ÑÑ Ð¸ Ð¸Ð½ÑÑÑÑÐºÑÐ¸Ñ"),
        BotCommand("cancel", "â ÐÑÐ¼ÐµÐ½Ð¸ÑÑ Ð¾Ð±ÑÐ°Ð±Ð¾ÑÐºÑ"),
    ])


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    conv_handler = ConversationHandler(
        per_message=True,
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
    app.add_handler(CallbackQueryHandler(handle_show_plan, pattern="^show_plan$"))
    app.add_handler(CallbackQueryHandler(handle_language, pattern="^lang_(?:ru|en|hi|zh|ko|pt)$"))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.Regex(r'https?://'),
        handle_chat
    ))
    print("Bot started!")
    app.run_polling()


if __name__ == "__main__":
    main()
