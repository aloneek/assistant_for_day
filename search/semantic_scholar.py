# ============================================
# Semantic Scholar Graph API: статьи с цитируемостью.
# Без ключа лимиты общие на всех — 429 здесь норма, не ошибка
# ============================================

import logging

from config import S2_API_KEY

logger = logging.getLogger(__name__)

API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

ABSTRACT_LIMIT = 300


async def search(client, query, limit=5):
    headers = {"x-api-key": S2_API_KEY} if S2_API_KEY else {}
    response = await client.get(API_URL, headers=headers, params={
        "query": query,
        "limit": limit,
        "fields": "title,abstract,year,citationCount,url",
    })
    if response.status_code == 429:
        logger.info("Semantic Scholar: rate limit (ожидаемо без ключа), источник пропущен")
        return []
    response.raise_for_status()

    results = []
    for paper in response.json().get("data", []):
        abstract = (paper.get("abstract") or "")[:ABSTRACT_LIMIT]
        results.append({
            "source": "semantic_scholar",
            "title": paper.get("title", ""),
            "year": paper.get("year"),
            "citations": paper.get("citationCount", 0),
            "summary": abstract,
            "url": paper.get("url", ""),
        })
    return results
