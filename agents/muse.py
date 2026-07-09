# ============================================
# Muse: проактивные идеи из свежих трендов × контекста пользователя.
# run() синхронный, зовётся планировщиком через asyncio.to_thread;
# источники опрашиваются параллельно через собственный asyncio.run
# ============================================

import asyncio
import json
import logging
import random

import httpx

from agents.plan_generator import load_profile
from config import MUSE_INTERVAL_DAYS, TELEGRAM_CHAT_ID, load_prompt
from llm.structured import StructuredRequestError, request_json_array
from search import arxiv, habr, hackernews
from timeutils import in_wake_window, now_local

logger = logging.getLogger(__name__)

# Больше, чем у Explorer: arXiv медленно отдаёт сортировку по дате,
# а Muse работает в фоне — спешить некуда
HTTP_TIMEOUT = 40.0

# Свежие статьи arXiv по темам пользователя (робототехника и ИИ)
ARXIV_QUERY = "cat:cs.RO OR cat:cs.AI OR cat:cs.LG"

TITLE_LIMIT = 80


def _validate_ideas(raw):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 2:
        raise ValueError("ожидается JSON-массив из 1-2 идей")
    ideas = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("идея должна быть объектом с title и description")
        title = str(item.get("title") or "").strip()
        description = str(item.get("description") or "").strip()
        if not title or not description:
            raise ValueError("у идеи пустой title или description")
        if len(title) > TITLE_LIMIT:
            raise ValueError(f"title длиннее {TITLE_LIMIT} символов: «{title}»")
        ideas.append({"title": title, "description": description})
    return ideas


# Пора ли приносить идею: настроен chat id, сейчас окно бодрствования
# и с прошлой идеи Muse прошло не меньше интервала
def is_due(db_conn):
    if not TELEGRAM_CHAT_ID:
        return False

    profile = load_profile(db_conn)
    if not in_wake_window(profile.get("wake_time", "09:00"), profile.get("sleep_time", "23:30")):
        return False

    last = db_conn.execute(
        "SELECT MAX(created_at) AS last FROM ideas WHERE origin = 'muse'"
    ).fetchone()["last"]
    if last is None:
        return True
    days_passed = db_conn.execute(
        "SELECT julianday('now') - julianday(?) AS days", (last,)
    ).fetchone()["days"]
    return days_passed >= MUSE_INTERVAL_DAYS


async def _fetch_trends():
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        outcomes = await asyncio.gather(
            habr.fetch_top(client),
            hackernews.fetch_top(client),
            arxiv.search(client, ARXIV_QUERY, limit=8, sort_by="submittedDate"),
            return_exceptions=True,
        )
    trends = []
    for outcome in outcomes:
        if isinstance(outcome, Exception):
            logger.warning("Muse: источник недоступен, пропускаю: %s", str(outcome)[:120])
        else:
            trends.extend(outcome)
    return trends


def _build_request(db_conn, trends):
    spheres = [dict(row) for row in db_conn.execute(
        "SELECT name, sphere_type, config, priority FROM spheres WHERE active = 1"
    )]
    skills = [row["name"] for row in db_conn.execute("SELECT name FROM skills")]
    existing_ideas = [row["title"] for row in db_conn.execute(
        "SELECT title FROM ideas ORDER BY id DESC LIMIT 20"
    )]

    # Случайное скрещивание: навык (или сфера) × свежий тренд
    seed_skill = random.choice(skills) if skills else random.choice(spheres)["name"]
    seed_trend = random.choice(trends)["title"]

    projects = db_conn.execute(
        "SELECT value FROM user_context WHERE key = 'projects'"
    ).fetchone()

    sections = [
        "# Сферы развития\n\n" + json.dumps(spheres, ensure_ascii=False),
        "# Навыки\n\n" + json.dumps(skills, ensure_ascii=False),
    ]
    if projects:
        sections.append("# Мои проекты на GitHub (не предлагать то же самое)\n\n" + projects["value"])
    sections += [
        "# Существующие идеи (НЕ повторять)\n\n" + json.dumps(existing_ideas, ensure_ascii=False),
        "# Свежие тренды\n\n" + json.dumps(trends, ensure_ascii=False),
        f"# Случайное скрещивание\n\n«{seed_skill}» × «{seed_trend}»",
        "Придумай 1-2 идеи. Верни только JSON-массив.",
    ]
    return "\n\n".join(sections), existing_ideas


# Дедупликация против существующих идей: совпадение нормализованных
# названий или вхождение одного в другое
def _is_duplicate(title, existing_titles):
    normalized = title.lower().strip()
    for existing in existing_titles:
        existing_normalized = existing.lower().strip()
        if normalized == existing_normalized:
            return True
        if normalized in existing_normalized or existing_normalized in normalized:
            return True
    return False


# Главная функция: генерирует идеи, сохраняет в ideas (origin='muse')
# и возвращает список {id, title, description} для отправки.
# Пустой список = сегодня нечего слать (это не ошибка)
def run(db_conn):
    trends = asyncio.run(_fetch_trends())
    if not trends:
        logger.warning("Muse: все источники трендов недоступны, пропускаю запуск")
        return []

    request, existing_titles = _build_request(db_conn, trends)
    try:
        ideas = request_json_array("muse", load_prompt("muse"), request, _validate_ideas)
    except StructuredRequestError:
        logger.warning("Muse: модели не вернули корректные идеи, пропускаю запуск")
        return []

    fresh_ideas = [idea for idea in ideas if not _is_duplicate(idea["title"], existing_titles)]
    if not fresh_ideas:
        logger.info("Muse: все сгенерированные идеи — дубли существующих, пропускаю")
        return []

    saved = []
    sources_json = json.dumps(trends, ensure_ascii=False)
    for idea in fresh_ideas:
        cursor = db_conn.execute(
            "INSERT INTO ideas (title, description, origin, sources) VALUES (?, ?, 'muse', ?)",
            (idea["title"], idea["description"], sources_json),
        )
        saved.append({"id": cursor.lastrowid, **idea})
    db_conn.commit()
    return saved
