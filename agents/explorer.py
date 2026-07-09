# ============================================
# Explorer: идея → что уже сделано (arXiv, Semantic Scholar, GitHub,
# Хабр), чем отличается, где ниша.
# Пайплайн: запросы → параллельный поиск → гейт релевантности (дешёвый
# LLM-проход отсекает работы, совпавшие только по словам) → при слабой
# выдаче вторая волна с переформулированными запросами → синтез.
# run() синхронный и работает из воркер-потока (handlers уводят весь
# handle_message в to_thread), поэтому событийный цикл бота не блокируется
# ============================================

import asyncio
import json
import logging

import httpx

from config import load_prompt
from llm.router import get_provider
from llm.structured import StructuredRequestError, request_json_array
from search import arxiv, github_search, habr, semantic_scholar

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 15.0

QUERY_COUNT = 3

SCIENCE_SOURCES = {"arxiv", "semantic_scholar"}

# Меньше релевантных после фильтра — синтез не делаем, отвечаем честно
MIN_RELEVANT_TOTAL = 2
# Меньше релевантных после первой волны — идём во вторую
SECOND_WAVE_BELOW = 4
# Научных релевантных не больше этого — режим «научной базы мало»
WEAK_SCIENCE_MAX = 1


def _validate_queries(raw):
    if not isinstance(raw, list) or len(raw) != QUERY_COUNT:
        raise ValueError(f"ожидается массив ровно из {QUERY_COUNT} строк-запросов")
    queries = []
    for item in raw:
        query = str(item).strip()
        if not query or len(query.split()) > 10:
            raise ValueError(f"запрос «{item}» пустой или длиннее 10 слов")
        queries.append(query)
    return queries


# Одна волна поиска: узкий EN — во все научные источники и GitHub,
# широкий EN — в GitHub, русский — в Хабр. Дедуп по URL через seen_urls
async def _search_wave(queries, seen_urls):
    narrow_query, broad_query, habr_query = queries
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        searches = [
            arxiv.search(client, narrow_query),
            semantic_scholar.search(client, narrow_query),
            github_search.search(client, narrow_query),
            github_search.search(client, broad_query),
            habr.search(client, habr_query),
        ]
        outcomes = await asyncio.gather(*searches, return_exceptions=True)

    results = []
    for outcome in outcomes:
        if isinstance(outcome, Exception):
            logger.warning("Источник недоступен, пропускаю: %s", str(outcome)[:120])
            continue
        for item in outcome:
            if item["url"] and item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                results.append(item)
    return results


# Гейт релевантности: каждому результату оценка 0-2 против идеи,
# в синтез проходят только 1-2. Гейт упал — пропускаем всё (как раньше)
def _gate_relevance(idea_title, idea_description, results):
    listing = [{
        "index": index,
        "source": item["source"],
        "title": item["title"],
        "summary": (item.get("summary") or "")[:200],
    } for index, item in enumerate(results)]

    def validate(raw):
        if not isinstance(raw, list):
            raise ValueError("ожидается JSON-массив оценок")
        scores = {}
        for entry in raw:
            if not isinstance(entry, dict) or "index" not in entry or "score" not in entry:
                raise ValueError("каждый элемент — объект с index и score")
            index, score = entry["index"], entry["score"]
            if not isinstance(index, int) or not 0 <= index < len(results):
                raise ValueError(f"index {index!r} вне диапазона 0..{len(results) - 1}")
            if score not in (0, 1, 2):
                raise ValueError(f"score {score!r} — допустимы только 0, 1 и 2")
            scores[index] = score
        missing = set(range(len(results))) - set(scores)
        if missing:
            raise ValueError(f"нет оценок для index: {sorted(missing)}")
        return scores

    message = (f"# Идея\n\n{idea_title}\n\n{idea_description}\n\n"
               f"# Результаты поиска\n\n{json.dumps(listing, ensure_ascii=False)}")
    try:
        scores = request_json_array("explorer", load_prompt("explorer_gate"), message, validate)
    except StructuredRequestError:
        logger.warning("Гейт релевантности не сработал — фильтрацию пропускаю")
        scores = {index: 1 for index in range(len(results))}

    for index, item in enumerate(results):
        item["relevance"] = scores[index]
    return [item for item in results if item["relevance"] >= 1]


def _second_wave_queries(idea_title, idea_description, first_queries):
    message = (
        f"Идея: {idea_title}\n\n{idea_description}\n\n"
        f"# Прошлая попытка\n\nЗапросы {json.dumps(first_queries, ensure_ascii=False)} "
        "дали мало релевантного. Дай НОВЫЕ запросы: другие термины, синонимы, "
        "смежные формулировки — не повторяй прежние."
    )
    return request_json_array("explorer", load_prompt("explorer_queries"), message, _validate_queries)


def _synthesize(idea_title, idea_description, queries, results, projects, weak_science):
    provider = get_provider("explorer")
    user_message = (
        f"# Идея\n\n{idea_title}\n\n{idea_description}\n\n"
        f"# Поисковые запросы\n\n{json.dumps(queries, ensure_ascii=False)}\n\n"
        f"# Релевантные результаты поиска\n\n{json.dumps(results, ensure_ascii=False)}"
    )
    if projects:
        user_message += (
            "\n\n# Проекты пользователя (учитывай при оценке отличий и ниши: "
            f"что он уже умеет и делал)\n\n{projects}"
        )
    if weak_science:
        user_message += (
            "\n\n# Режим: научной базы мало\n\nРелевантных научных статей почти нет — "
            "тема выглядит продуктовой. Опирайся на GitHub и Хабр, действуй по правилу 5."
        )
    response = provider.chat([
        {"role": "system", "content": load_prompt("explorer_synthesis")},
        {"role": "user", "content": user_message},
    ])
    return response["content"]


# Точка входа: вызывается оркестратором с новой идеей пользователя
def run(idea_title, idea_description, db_conn):
    # Идею сохраняем сразу: даже если исследование упадёт, она не потеряется
    cursor = db_conn.execute(
        "INSERT INTO ideas (title, description, origin) VALUES (?, ?, 'user')",
        (idea_title, idea_description),
    )
    idea_id = cursor.lastrowid
    db_conn.commit()
    return explore_idea(idea_id, idea_title, idea_description, db_conn)


# Исследование уже сохранённой идеи — используется и оркестратором (run),
# и кнопкой «🔍 Исследовать» под идеями от Muse
def explore_idea(idea_id, idea_title, idea_description, db_conn):
    try:
        queries = request_json_array(
            "explorer",
            load_prompt("explorer_queries"),
            f"Идея: {idea_title}\n\n{idea_description}",
            _validate_queries,
        )
    except StructuredRequestError:
        return f"Идею «{idea_title}» сохранил (№{idea_id}), но исследование не удалось — попробуй позже."

    seen_urls = set()
    all_results = asyncio.run(_search_wave(queries, seen_urls))
    relevant = _gate_relevance(idea_title, idea_description, all_results) if all_results else []

    # Слабый первый проход — вторая волна с переформулированными запросами
    if all_results and len(relevant) < SECOND_WAVE_BELOW:
        try:
            second_queries = _second_wave_queries(idea_title, idea_description, queries)
            second_results = asyncio.run(_search_wave(second_queries, seen_urls))
            if second_results:
                relevant += _gate_relevance(idea_title, idea_description, second_results)
                all_results += second_results
            queries = queries + second_queries
        except StructuredRequestError:
            logger.warning("Вторая волна запросов не удалась, работаю с первой")

    # Сырьё (обе волны, с оценками релевантности) — в базу для истории
    db_conn.execute(
        "UPDATE ideas SET sources = ? WHERE id = ?",
        (json.dumps(all_results, ensure_ascii=False), idea_id),
    )
    db_conn.commit()

    if not all_results:
        return (
            f"Идею «{idea_title}» сохранил (№{idea_id}), но все источники поиска "
            "сейчас недоступны — попробуй исследовать позже."
        )

    # Почти всё отсеялось — честный ответ вместо синтеза с притянутым
    if len(relevant) < MIN_RELEVANT_TOTAL:
        leftover_lines = "\n".join(f"- {item['title']} ({item['source']}): {item['url']}" for item in relevant)
        note = f"\n\nЕдинственное смежное, что нашлось:\n{leftover_lines}" if relevant else ""
        return (
            f"Идею «{idea_title}» сохранил (№{idea_id}). Релевантной базы поиск не дал: "
            f"из {len(all_results)} найденных работ к идее относятся {len(relevant)} — остальные "
            "совпадают только по словам. Тема, похоже, продуктовая — научные статьи тут "
            "не главный источник. Это НЕ значит, что ниша свободна: поиск не исчерпывающий." + note
        )

    science_count = sum(1 for item in relevant if item["source"] in SCIENCE_SOURCES)
    weak_science = science_count <= WEAK_SCIENCE_MAX

    projects_row = db_conn.execute(
        "SELECT value FROM user_context WHERE key = 'projects'"
    ).fetchone()
    synthesis = _synthesize(idea_title, idea_description, queries, relevant,
                            projects_row["value"] if projects_row else None, weak_science)
    db_conn.execute(
        "UPDATE ideas SET exploration_result = ?, status = 'explored' WHERE id = ?",
        (synthesis, idea_id),
    )
    db_conn.commit()
    return synthesis
