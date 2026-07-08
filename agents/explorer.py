# ============================================
# Explorer: идея → что уже сделано (arXiv, Semantic Scholar, GitHub),
# чем отличается, где ниша.
# run() синхронный и работает из воркер-потока (handlers уводят весь
# handle_message в to_thread), поэтому событийный цикл бота не блокируется;
# три источника опрашиваются параллельно через собственный asyncio.run
# ============================================

import asyncio
import json
import logging

import httpx

from config import load_prompt
from llm.router import get_provider
from llm.structured import StructuredRequestError, request_json_array
from search import arxiv, github_search, semantic_scholar

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 15.0

QUERY_COUNT = 2


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


# Параллельный опрос: узкий запрос — во все три источника,
# широкий — только в GitHub (по широким словам код ищется лучше статей)
async def _search_all(queries):
    narrow_query, broad_query = queries
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        searches = [
            arxiv.search(client, narrow_query),
            semantic_scholar.search(client, narrow_query),
            github_search.search(client, narrow_query),
            github_search.search(client, broad_query),
        ]
        outcomes = await asyncio.gather(*searches, return_exceptions=True)

    results = []
    seen_urls = set()
    for outcome in outcomes:
        if isinstance(outcome, Exception):
            logger.warning("Источник недоступен, пропускаю: %s", str(outcome)[:120])
            continue
        for item in outcome:
            if item["url"] and item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                results.append(item)
    return results


def _synthesize(idea_title, idea_description, queries, results):
    provider = get_provider("explorer")
    user_message = (
        f"# Идея\n\n{idea_title}\n\n{idea_description}\n\n"
        f"# Поисковые запросы\n\n{json.dumps(queries, ensure_ascii=False)}\n\n"
        f"# Результаты поиска\n\n{json.dumps(results, ensure_ascii=False)}"
    )
    response = provider.chat([
        {"role": "system", "content": load_prompt("explorer_synthesis")},
        {"role": "user", "content": user_message},
    ])
    return response["content"]


# Точка входа: вызывается оркестратором
def run(idea_title, idea_description, db_conn):
    # Идею сохраняем сразу: даже если исследование упадёт, она не потеряется
    cursor = db_conn.execute(
        "INSERT INTO ideas (title, description, origin) VALUES (?, ?, 'user')",
        (idea_title, idea_description),
    )
    idea_id = cursor.lastrowid
    db_conn.commit()

    try:
        queries = request_json_array(
            "explorer",
            load_prompt("explorer_queries"),
            f"Идея: {idea_title}\n\n{idea_description}",
            _validate_queries,
        )
    except StructuredRequestError:
        return f"Идею «{idea_title}» сохранил (№{idea_id}), но исследование не удалось — попробуй позже."

    results = asyncio.run(_search_all(queries))
    db_conn.execute(
        "UPDATE ideas SET sources = ? WHERE id = ?",
        (json.dumps(results, ensure_ascii=False), idea_id),
    )
    db_conn.commit()

    if not results:
        return (
            f"Идею «{idea_title}» сохранил (№{idea_id}), но все источники поиска "
            "сейчас недоступны — попробуй исследовать позже."
        )

    synthesis = _synthesize(idea_title, idea_description, queries, results)
    db_conn.execute(
        "UPDATE ideas SET exploration_result = ?, status = 'explored' WHERE id = ?",
        (synthesis, idea_id),
    )
    db_conn.commit()
    return synthesis
