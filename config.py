# ============================================
# Конфигурация: переменные окружения и константы
# ============================================

import os
from pathlib import Path

from dotenv import load_dotenv

# Корень проекта — папка, где лежит этот файл
BASE_DIR = Path(__file__).parent

# Подхватываем .env из корня проекта
load_dotenv(BASE_DIR / ".env")

# Токены и ключи внешних сервисов
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# Ключ Semantic Scholar не обязателен: без него меньше лимиты и чаще 429
S2_API_KEY = os.getenv("S2_API_KEY", "")

# YouTube Data API v3 (та же консоль Google Cloud, что и Gemini) —
# метаданные видео для задач; пусто = задачи-видео без длительности
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

# Модель для нативного анализа видео (video-input по YouTube URL).
# У неё отдельная неистраченная квота 20 RPD — видео-запросы редкие
VIDEO_MODEL = "gemini-3.5-flash"

# Куда Muse шлёт проактивные идеи (личный chat id пользователя).
# Пусто — проактивные сообщения выключены
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Раз в сколько дней Muse приносит идеи (1-3)
MUSE_INTERVAL_DAYS = int(os.getenv("MUSE_INTERVAL_DAYS", "2"))

# Таймзона пользователя: все «сегодня» и «сейчас» считаются в ней
# через timeutils.now_local(), а не через системное время
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")

# Путь к базе SQLite
DB_PATH = BASE_DIR / "db" / "assistant.db"

# Папка с системными промптами агентов
PROMPTS_DIR = BASE_DIR / "prompts"

# Какими моделями работает каждый агент.
# Ключ — имя агента, значение — цепочка логических имён моделей:
# первая — основная, дальше — резерв при 429/503.
# llm/router.py разворачивает имена в конкретных провайдеров.
# gemini-flash-lite (gemini-3.1-flash-lite): 15 RPM / 500 RPD,
# gemini-flash (gemini-2.5-flash): 5 RPM / 20 RPD — резерв,
# groq-llama (llama-3.3-70b-versatile): внешний резерв, если лёг весь Gemini.
AGENT_MODELS = {
    "orchestrator": ["gemini-flash-lite", "gemini-flash", "groq-llama"],
    "planner": ["gemini-flash-lite", "gemini-flash", "groq-llama"],
    # Генератор плана дня (LLM-вызов внутри generate_day_plan): отдельный
    # ключ, чтобы менять модель независимо от Planner. Эскалация по цепочке
    # здесь не только при 429/503, но и при ошибках JSON/валидации плана
    "plan_generator": ["gemini-flash-lite", "gemini-flash", "groq-llama"],
    "explorer": ["gemini-flash-lite", "gemini-flash", "groq-llama"],
    "muse": ["gemini-flash-lite", "gemini-flash", "groq-llama"],
    # текстовая деградация analyze_videos, когда видео-лимит исчерпан
    "video_meta": ["gemini-flash-lite", "gemini-flash", "groq-llama"],
}


# Читает системный промпт агента из prompts/<name>.md
def load_prompt(name):
    prompt_path = PROMPTS_DIR / f"{name}.md"
    return prompt_path.read_text(encoding="utf-8")
