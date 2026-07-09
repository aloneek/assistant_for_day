# ============================================
# Хабр: RSS лучших статей недели (Muse) и поиск по ключевым
# словам (Explorer) — продуктовый и русскоязычный срез,
# которого нет в arXiv
# ============================================

import re
import xml.etree.ElementTree as ET

FEED_URL = "https://habr.com/ru/rss/best/weekly/?fl=ru"
SEARCH_URL = "https://habr.com/ru/rss/search/"

# Поисковый RSS Хабра отвечает только браузерным User-Agent
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

TAG_PATTERN = re.compile(r"<[^>]+>")
SUMMARY_LIMIT = 300


def _parse_items(xml_text, limit, with_summary=False):
    items = []
    for item in ET.fromstring(xml_text).iter("item"):
        entry = {
            "source": "habr",
            "title": (item.findtext("title") or "").strip(),
            "url": (item.findtext("link") or "").strip(),
        }
        if with_summary:
            description = TAG_PATTERN.sub(" ", item.findtext("description") or "")
            entry["summary"] = " ".join(description.split())[:SUMMARY_LIMIT]
        items.append(entry)
        if len(items) >= limit:
            break
    return items


async def fetch_top(client, limit=10):
    response = await client.get(FEED_URL, headers=HEADERS)
    response.raise_for_status()
    return _parse_items(response.text, limit)


async def search(client, query, limit=6):
    response = await client.get(SEARCH_URL, headers=HEADERS, params={"q": query, "target_type": "posts"})
    response.raise_for_status()
    return _parse_items(response.text, limit, with_summary=True)
