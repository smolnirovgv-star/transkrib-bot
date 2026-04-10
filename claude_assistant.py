import os
import anthropic
from typing import Optional

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def build_system_prompt(project: str = "transkrib_bot") -> str:
    """Системный промпт под конкретный проект — легко расширять"""

    base = (
        "Ты — дружелюбный AI-помощник. "
        "Отвечай коротко (до 150 слов), на языке пользователя. "
        "Будь конкретным и полезным.\n\n"
    )

    projects = {
        "transkrib_bot": (
            "Ты помощник Transkrib SmartCut AI — бота для транскрипции видео.\n\n"
            "Что умеет бот:\n"
            "- Транскрибирует YouTube, VK, Rutube видео в текст\n"
            "- Сокращает до 1/3/5 минут ключевых моментов\n"
            "- Форматы: текст, нарезка видео, SRT субтитры\n"
            "- Автоопределение языка\n\n"
            "Тарифы:\n"
            "- Free: 3 видео бесплатно\n"
            "- Starter: $9/мес — 30 видео\n"
            "- Pro: $29/мес — безлимит\n"
            "- Annual: $99/год — безлимит\n\n"
            "Команды: /start /plan /help /cancel\n"
            "Для оплаты → /plan. Для обработки → отправь ссылку."
        ),
        "transkrib_desktop": (
            "Ты помощник десктоп-приложения Transkrib SmartCut AI.\n"
            "Помогаешь пользователю разобраться с транскрипцией видео на компьютере."
        ),
        "domstroy": (
            "Ты помощник компании ДОМ СТРОЙ — строительство домов и установка окон в Екатеринбурге.\n"
            "Помогаешь клиентам с вопросами о строительстве, ценах и услугах."
        ),
    }

    return base + projects.get(project, "Ты универсальный AI-помощник.")


async def ask_claude(
    user_text: str,
    project: str = "transkrib_bot",
    history: Optional[list] = None
) -> str:
    """
    Универсальная функция — вызывай из любого проекта.
    history = [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
    """
    messages = history or []
    messages = messages + [{"role": "user", "content": user_text}]

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=build_system_prompt(project),
            messages=messages
        )
        return response.content[0].text
    except Exception as e:
        print(f"Claude API error: {type(e).__name__}: {e}")
        return "🤖 Помощник временно недоступен. Попробуй /help"
