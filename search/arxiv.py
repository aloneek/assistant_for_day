# ============================================
# arXiv API: поиск статей, ответ — Atom XML
# ============================================

import xml.etree.ElementTree as ET

API_URL = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"

# Сколько символов аннотации отдаём в синтез
SUMMARY_LIMIT = 300


# sort_by="submittedDate" даёт свежие статьи (для Muse),
# "relevance" — самые близкие по теме (для Explorer)
async def search(client, query, limit=5, sort_by="relevance"):
    response = await client.get(API_URL, params={
        "search_query": query if ":" in query else f"all:{query}",
        "max_results": limit,
        "sortBy": sort_by,
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
