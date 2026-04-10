import os
import anthropic
from typing import Optional
from supabase import create_client

# --- Claude API ---
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# --- Supabase ---
supabase = create_client(
    os.getenv("SUPABASE_URL", ""),
    os.getenv("SUPABASE_KEY", "")
)

# Haiku 4.5 pricing per 1M tokens
INPUT_PRICE = 1.0
OUTPUT_PRICE = 5.0


def build_system_prompt(project: str = "transkrib_bot") -> str:
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


def load_history(telegram_id: int, limit: int = 10) -> list:
    try:
        result = supabase.table("bot_chat_history") \
            .select("role, content") \
            .eq("telegram_id", telegram_id) \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        if result.data:
            return list(reversed(result.data))
        return []
    except Exception as e:
        print(f"Load history error: {e}")
        return []


def save_message(telegram_id: int, role: str, content: str, project: str = "transkrib_bot"):
    try:
        supabase.table("bot_chat_history").insert({
            "telegram_id": telegram_id,
            "role": role,
            "content": content,
            "project": project
        }).execute()
    except Exception as e:
        print(f"Save message error: {e}")


def get_total_spent() -> float:
    try:
        result = supabase.table("bot_api_usage") \
            .select("cost_usd") \
            .execute()
        if result.data:
            return sum(float(r["cost_usd"]) for r in result.data)
    except Exception as e:
        print(f"Get total spent error: {e}")
    return 0.0


def save_usage(telegram_id: int, input_tokens: int, output_tokens: int, cost: float):
    try:
        supabase.table("bot_api_usage").insert({
            "telegram_id": telegram_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost
        }).execute()
    except Exception as e:
        print(f"Save usage error: {e}")


async def ask_claude(
    user_text: str,
    project: str = "transkrib_bot",
    history: Optional[list] = None,
    telegram_id: Optional[int] = None
) -> str:
    if telegram_id and not history:
        history = load_history(telegram_id)

    messages = history or []
    messages = messages + [{"role": "user", "content": user_text}]

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=build_system_prompt(project),
            messages=messages
        )
        answer = response.content[0].text

        inp = response.usage.input_tokens
        out = response.usage.output_tokens
        cost = (inp * INPUT_PRICE + out * OUTPUT_PRICE) / 1_000_000

        if telegram_id:
            save_message(telegram_id, "user", user_text, project)
            save_message(telegram_id, "assistant", answer, project)
            save_usage(telegram_id, inp, out, cost)

        total_spent = get_total_spent() if telegram_id else cost
        footer = f"\n\n```\n\U0001F4CA {inp}+{out} tok | ${cost:.4f} | total: ${total_spent:.4f}\n```"
        return answer + footer

    except Exception as e:
        print(f"Claude API error: {type(e).__name__}: {e}")
        return "\U0001F916 Помощник временно недоступен. Попробуй /help"
