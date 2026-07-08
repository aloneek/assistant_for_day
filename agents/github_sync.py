# ============================================
# Синхронизация GitHub → профиль проектов в user_context['projects'].
# Зовётся недельной джобой планировщика и вручную через оркестратор.
# run() синхронный (вызывается из воркер-потока), HTTP — параллельно
# ============================================

import asyncio
import json
import logging

import httpx

from config import GITHUB_USERNAME, load_prompt
from llm.router import get_provider
from search import github_profile

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 20.0


def run(db_conn):
    async def _fetch():
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            return await github_profile.fetch_repos(client, GITHUB_USERNAME)

    try:
        repos = asyncio.run(_fetch())
    except Exception as error:
        logger.warning("GitHub недоступен: %s", str(error)[:120])
        return "GitHub сейчас недоступен, профиль проектов не обновил — попробуй позже."
    if not repos:
        return f"У пользователя {GITHUB_USERNAME} не нашлось репозиториев (форки не считаются)."

    provider = get_provider("github_sync")
    response = provider.chat([
        {"role": "system", "content": load_prompt("github_profile")},
        {"role": "user", "content": json.dumps(repos, ensure_ascii=False)},
    ])
    summary = response["content"].strip()

    db_conn.execute(
        "INSERT INTO user_context (key, value, category) VALUES ('projects', ?, 'fact') "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (summary,),
    )
    db_conn.commit()
    logger.info("Профиль проектов обновлён: %d реп", len(repos))
    return f"Профиль проектов обновлён ({len(repos)} реп с GitHub):\n\n{summary}"
