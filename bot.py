import os
import asyncio
import httpx
from dotenv import load_dotenv
load_dotenv()
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_URL = os.environ.get("TRANSKRIB_API_URL", "https://transkrib-api.onrender.com")

LANG_MESSAGES = {
    "lang_ru": "🇷🇺 Язык установлен: Русский

Отправь ссылку на видео YouTube, VK или Rutube!",
    "lang_en": "🇬🇧 Language set: English

Send a YouTube, VK or Rutube link!",
    "lang_hi": "🇮🇳 भाषा सेट: हिन्दी

YouTube, VK या Rutube लिंक भेजें!",
    "lang_zh": "🇨🇳 语言已设置：中文

发送YouTube、VK或Rutube链接！",
    "lang_ko": "🇰🇷 언어 설정: 한국어

YouTube, VK 또는 Rutube 링크를 보내주세요!",
    "lang_pt": "🇧🇷 Idioma: Português

Envie um link do YouTube, VK ou Rutube!",
}

async def handle_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    msg = LANG_MESSAGES.get(query.data, "Send a video link!")
    await query.edit_message_text(text=msg)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
        InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
        InlineKeyboardButton("🇮🇳 हिन्दी", callback_data="lang_hi"),
    ],[
        InlineKeyboardButton("🇨🇳 中文", callback_data="lang_zh"),
        InlineKeyboardButton("🇰🇷 한국어", callback_data="lang_ko"),
        InlineKeyboardButton("🇧🇷 Português", callback_data="lang_pt"),
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 Привет! Я Transkrib SmartCut AI Bot.\n\n"
        "✂️ Отправь мне ссылку на видео YouTube, VK или Rutube — "
        "я транскрибирую его и сделаю умную нарезку ключевых моментов!\n\n"
        "🌍 Choose your language:",
        reply_markup=reply_markup
    )

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    
    if not url.startswith('http'):
        await update.message.reply_text(
            "❌ Пожалуйста отправь ссылку на видео.\n"
            "Поддерживаются: YouTube, VK, Rutube"
        )
        return
    
    msg = await update.message.reply_text(
        "⏳ Обрабатываю видео...\n"
        "Это займёт 1-3 минуты. Пожалуйста подожди!"
    )
    
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{API_URL}/api/tasks/url",
                json={"url": url, "user_id": str(update.effective_user.id)}
            )
            data = resp.json()
            task_id = data.get("task_id")
            
            if not task_id:
                await msg.edit_text("❌ Ошибка создания задачи. Попробуй позже.")
                return
            
            for i in range(60):
                await asyncio.sleep(5)
                status = await client.get(f"{API_URL}/api/tasks/{task_id}")
                sd = status.json()
                
                if sd.get("status") == "completed":
                    result = sd.get("result", {})
                    transcript = (result.get("transcript") or "")[:2000]
                    summary = result.get("summary") or result.get("analysis") or ""
                    
                    await msg.edit_text(
                        f"✅ Готово!\n\n"
                        f"📋 *Резюме:*\n{summary[:500]}\n\n"
                        f"📝 *Транскрипция:*\n{transcript}...\n\n"
                        f"🎬 Обработано Transkrib SmartCut AI",
                        parse_mode="Markdown"
                    )
                    return
                    
                elif sd.get("status") == "failed":
                    await msg.edit_text("❌ Ошибка обработки. Попробуй другую ссылку.")
                    return
                    
                if i % 6 == 0 and i > 0:
                    mins = (i * 5) // 60
                    await msg.edit_text(f"⏳ Обрабатываю... прошло {mins} мин.")
            
            await msg.edit_text("⏱ Превышено время ожидания. Попробуй позже.")
            
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {str(e)[:200]}")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Как пользоваться Transkrib Bot:*\n\n"
        "1. Скопируй ссылку на видео\n"
        "2. Вставь её в чат\n"
        "3. Жди 1-3 минуты\n"
        "4. Получи транскрипцию и нарезку!\n\n"
        "🔗 Поддерживаются: YouTube, VK, Rutube\n\n"
        "💻 Скачать приложение: https://transkrib.su",
        parse_mode="Markdown"
    )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(handle_language, pattern="^lang_"))
    print("Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()