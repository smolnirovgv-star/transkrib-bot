import os
from datetime import datetime, timezone
from supabase import create_client

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

PLANS = {
    "free":    {"videos_limit": 3,    "days": None, "price": 0},
    "starter": {"videos_limit": 30,   "days": 30,   "price": 9},
    "pro":     {"videos_limit": 9999, "days": 30,   "price": 29},
    "annual":  {"videos_limit": 9999, "days": 365,  "price": 99},
}

PLAN_PRICES = {
    "starter": {"rub": "450",  "usd": "5",  "days": 30,  "videos_limit": 30,   "name": "🚀 Starter"},
    "pro":     {"rub": "1700", "usd": "20", "days": 30,  "videos_limit": 9999, "name": "💼 Pro"},
    "annual":  {"rub": "8900", "usd": "100","days": 365, "videos_limit": 9999, "name": "👑 Annual"},
}

LEMON_LINKS = {
    "starter": "https://transkrib.lemonsqueezy.com/buy/starter",
    "pro":     "https://transkrib.lemonsqueezy.com/buy/pro",
    "annual":  "https://transkrib.lemonsqueezy.com/buy/annual",
}


def get_user(tid: int) -> dict:
    res = supabase.table("bot_users").select("*").eq("telegram_id", tid).execute()
    if res.data:
        return res.data[0]
    new = {"telegram_id": tid, "plan": "free", "videos_used": 0, "videos_limit": 3}
    supabase.table("bot_users").insert(new).execute()
    return new


def activate_plan(tid: int, plan: str) -> None:
    """Activate paid plan for user (called after successful payment)."""
    from datetime import timedelta
    plan_info = PLAN_PRICES.get(plan)
    if not plan_info:
        return
    expires_at = (datetime.now(timezone.utc) + timedelta(days=plan_info["days"])).isoformat()
    supabase.table("bot_users").upsert({
        "telegram_id": tid,
        "plan": plan,
        "videos_limit": plan_info["videos_limit"],
        "videos_used": 0,
        "plan_expires_at": expires_at,
    }).execute()


def can_process(tid: int) -> tuple:
    user = get_user(tid)
    if user.get("plan_expires_at") and user["plan"] != "free":
        expires = datetime.fromisoformat(user["plan_expires_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires:
            supabase.table("bot_users").update(
                {"plan": "free", "videos_limit": 3, "videos_used": 0}
            ).eq("telegram_id", tid).execute()
            return False, "expired"
    if user["videos_used"] >= user["videos_limit"]:
        return False, "limit"
    return True, "ok"


def increment_usage(tid: int):
    user = get_user(tid)
    supabase.table("bot_users").update(
        {"videos_used": user["videos_used"] + 1}
    ).eq("telegram_id", tid).execute()


def get_status_text(tid: int) -> str:
    user = get_user(tid)
    plan = user["plan"]
    used = user["videos_used"]
    limit = user["videos_limit"]
    exp = (user.get("plan_expires_at") or "")[:10]
    names = {"free": "🆓 Free", "starter": "🚀 Starter",
             "pro": "💼 Pro", "annual": "👑 Annual"}
    name = names.get(plan, plan)
    nl = chr(10)
    if plan == "free":
        return (f"{name}" + nl + "Видео использовано: " + str(used) + "/3"
                + nl + nl + "Для продолжения купи подписку 👇")
    elif plan == "starter":
        return (f"{name}" + nl + "Видео: " + str(used) + "/" + str(limit)
                + nl + "Действует до: " + exp)
    else:
        return (f"{name} — Безлимит ✅"
                + nl + "Действует до: " + exp)
