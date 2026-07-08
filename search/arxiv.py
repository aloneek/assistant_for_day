# ============================================
# arXiv API: поиск статей, ответ — Atom XML
# ============================================

import xml.etree.ElementTree as ET

API_URL = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"

# Сколько символов аннотации отдаём в синтез
SUMMARY_LIMIT = 300


async def search(client, query, limit=5):
    response = await client.get(API_URL, params={
        "search_query": f"all:{query}",
        "max_results": limit,
        "sortBy": "relevance",
    })
    response.raise_for_status()

    results = []
    for entry in ET.fromstring(response.text).findall(f"{ATOM}entry"):
        title = " ".join(entry.findtext(f"{ATOM}title", "").split())
        summary = " ".join(entry.findtext(f"{ATOM}summary", "").split())[:SUMMARY_LIMIT]
        results.append({
            "source": "arxiv",
            "title": title,
            "year": entry.findtext(f"{ATOM}published", "")[:4],
            "summary": summary,
            "url": entry.findtext(f"{ATOM}id", ""),
        })
    return results
