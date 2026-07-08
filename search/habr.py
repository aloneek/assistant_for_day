# ============================================
# Хабр: RSS лучших статей недели
# ============================================

import xml.etree.ElementTree as ET

FEED_URL = "https://habr.com/ru/rss/best/weekly/?fl=ru"


async def fetch_top(client, limit=10):
    response = await client.get(FEED_URL)
    response.raise_for_status()

    items = []
    for item in ET.fromstring(response.text).iter("item"):
        items.append({
            "source": "habr",
            "title": (item.findtext("title") or "").strip(),
            "url": (item.findtext("link") or "").strip(),
        })
        if len(items) >= limit:
            break
    return items
