# ============================================
# HackerNews: текущая главная страница через Algolia API
# (один запрос вместо N по официальному Firebase API)
# ============================================

API_URL = "https://hn.algolia.com/api/v1/search"


async def fetch_top(client, limit=10):
    response = await client.get(API_URL, params={
        "tags": "front_page",
        "hitsPerPage": limit,
    })
    response.raise_for_status()

    items = []
    for hit in response.json().get("hits", []):
        story_id = hit.get("objectID", "")
        items.append({
            "source": "hackernews",
            "title": hit.get("title", ""),
            "points": hit.get("points", 0),
            "url": hit.get("url") or f"https://news.ycombinator.com/item?id={story_id}",
        })
    return items
