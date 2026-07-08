# ============================================
# GitHub API (без токена): репозитории пользователя с README —
# сырьё для профиля проектов. Лимит без ключа 60 запросов/час,
# синк раз в неделю укладывается с запасом
# ============================================

import asyncio
import logging

API_URL = "https://api.github.com"
HEADERS = {"Accept": "application/vnd.github.raw+json"}

README_LIMIT = 1500

logger = logging.getLogger(__name__)


async def _fetch_readme(client, full_name):
    response = await client.get(f"{API_URL}/repos/{full_name}/readme", headers=HEADERS)
    if response.status_code == 404:
        return ""
    response.raise_for_status()
    return response.text[:README_LIMIT]


async def fetch_repos(client, username, limit=10):
    response = await client.get(
        f"{API_URL}/users/{username}/repos",
        headers=HEADERS,
        params={"sort": "pushed", "per_page": limit},
    )
    response.raise_for_status()
    repos = [repo for repo in response.json() if not repo.get("fork")]

    readmes = await asyncio.gather(
        *(_fetch_readme(client, repo["full_name"]) for repo in repos),
        return_exceptions=True,
    )

    results = []
    for repo, readme in zip(repos, readmes):
        if isinstance(readme, Exception):
            logger.warning("README %s недоступен: %s", repo["full_name"], str(readme)[:80])
            readme = ""
        results.append({
            "name": repo["name"],
            "description": repo.get("description") or "",
            "language": repo.get("language") or "",
            "stars": repo.get("stargazers_count", 0),
            "pushed_at": repo.get("pushed_at", ""),
            "readme": readme,
        })
    return results
