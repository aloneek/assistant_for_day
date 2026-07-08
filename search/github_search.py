# ============================================
# GitHub Search API: готовые реализации по звёздам.
# Без токена: 10 поисковых запросов в минуту — хватает
# ============================================

API_URL = "https://api.github.com/search/repositories"


async def search(client, query, limit=6):
    response = await client.get(API_URL, headers={
        "Accept": "application/vnd.github+json",
    }, params={
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": limit,
    })
    response.raise_for_status()

    results = []
    for repo in response.json().get("items", []):
        results.append({
            "source": "github",
            "title": repo.get("full_name", ""),
            "stars": repo.get("stargazers_count", 0),
            "summary": repo.get("description") or "",
            "url": repo.get("html_url", ""),
        })
    return results
