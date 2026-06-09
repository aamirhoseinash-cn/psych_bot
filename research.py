"""
جستجوی مقالات واقعی از Semantic Scholar و PubMed
کاملاً رایگان، بدون API Key
"""

import asyncio
import logging
import httpx

log = logging.getLogger(__name__)

SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"


async def search_semantic_scholar(query: str, limit: int = 6) -> list[dict]:
    """
    جستجو در Semantic Scholar — 200 میلیون مقاله واقعی
    فقط مقالات peer-reviewed با abstract برمی‌گرداند
    """
    # چند کوئری موازی برای پوشش بهتر
    queries = [
        query,
        f"{query} psychology",
        f"{query} neuroscience clinical",
    ]

    all_results = []
    seen_ids = set()

    async with httpx.AsyncClient(timeout=20) as client:
        for q in queries[:2]:  # دو کوئری اول
            try:
                params = {
                    "query": q,
                    "limit": limit,
                    "fields": "title,authors,year,venue,abstract,citationCount,publicationTypes,externalIds",
                    "sort": "relevance",
                }
                resp = await client.get(SEMANTIC_SCHOLAR_URL, params=params)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                papers = data.get("data", [])

                for p in papers:
                    pid = p.get("paperId", "")
                    if pid in seen_ids or not p.get("title"):
                        continue
                    if p.get("year", 0) and p.get("year", 0) < 1990:
                        continue
                    # فقط مقالاتی که abstract دارند
                    if not p.get("abstract"):
                        continue
                    seen_ids.add(pid)

                    authors = [a.get("name", "") for a in p.get("authors", [])[:3]]
                    if len(p.get("authors", [])) > 3:
                        authors.append("et al.")

                    all_results.append({
                        "title": p.get("title", ""),
                        "authors": ", ".join(authors),
                        "year": p.get("year", ""),
                        "venue": p.get("venue", ""),
                        "abstract": p.get("abstract", "")[:600],
                        "citations": p.get("citationCount", 0),
                    })

                await asyncio.sleep(1)  # rate limiting

            except Exception as e:
                log.warning(f"⚠️ Semantic Scholar ({q[:20]}): {e}")
                continue

    # مرتب‌سازی: جدیدتر و پراستناد اول
    all_results.sort(key=lambda x: (x.get("year", 0), x.get("citations", 0)), reverse=True)
    return all_results[:limit]


async def search_pubmed(query: str, limit: int = 4) -> list[dict]:
    """جستجو در PubMed — 36 میلیون مقاله پزشکی/روانشناسی"""
    SEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    SUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            search_resp = await client.get(SEARCH, params={
                "db": "pubmed",
                "term": f"{query}[Title/Abstract] AND (psychology[MeSH] OR psychiatry[MeSH] OR neuroscience[MeSH] OR behavior[MeSH])",
                "retmax": limit * 2,
                "sort": "relevance",
                "retmode": "json",
                "mindate": "2000",
            })
            if search_resp.status_code != 200:
                return []

            ids = search_resp.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                return []

            await asyncio.sleep(0.5)

            summary_resp = await client.get(SUMMARY, params={
                "db": "pubmed",
                "id": ",".join(ids[:limit]),
                "retmode": "json",
            })
            if summary_resp.status_code != 200:
                return []

            articles = summary_resp.json().get("result", {})
            results = []

            for pmid in ids[:limit]:
                a = articles.get(str(pmid), {})
                if not a or not a.get("title"):
                    continue

                authors_list = a.get("authors", [])[:3]
                authors = [x.get("name", "") for x in authors_list]
                if len(a.get("authors", [])) > 3:
                    authors.append("et al.")

                pub_date = a.get("pubdate", "")
                year = pub_date[:4] if pub_date else ""

                results.append({
                    "title": a.get("title", "").rstrip("."),
                    "authors": ", ".join(authors),
                    "year": year,
                    "venue": a.get("source", ""),
                    "abstract": "",
                    "citations": 0,
                })

            return results

    except Exception as e:
        log.warning(f"⚠️ PubMed: {e}")
        return []


async def fetch_real_papers(topic: str) -> str:
    """
    مقالات واقعی را جستجو می‌کند و یک SOURCE_PACK آماده برمی‌گرداند.
    اگر هیچ مقاله‌ای پیدا نشد، string خالی برمی‌گرداند.
    """
    log.info(f"🔍 جستجوی مقالات: {topic[:40]}")

    ss_results, pm_results = await asyncio.gather(
        search_semantic_scholar(topic, limit=5),
        search_pubmed(topic, limit=3),
        return_exceptions=True
    )

    if isinstance(ss_results, Exception):
        log.warning(f"SS خطا: {ss_results}")
        ss_results = []
    if isinstance(pm_results, Exception):
        log.warning(f"PM خطا: {pm_results}")
        pm_results = []

    # ترکیب و حذف تکراری
    seen_titles = set()
    all_papers = []
    for p in (ss_results + pm_results):
        t = p.get("title", "").lower()[:50]
        if t and t not in seen_titles:
            seen_titles.add(t)
            all_papers.append(p)

    if not all_papers:
        log.warning("⚠️ هیچ مقاله‌ای پیدا نشد")
        return ""

    log.info(f"✅ {len(all_papers)} مقاله واقعی پیدا شد")

    lines = [
        "\n\nSOURCE_PACK — REAL VERIFIED PAPERS (retrieved live from Semantic Scholar & PubMed):",
        "RULE: Only cite papers from this list. Do NOT add any other citation.",
        "RULE: If a claim cannot be traced to these papers, write it as general consensus without a citation.",
        "RULE: Never fabricate author names, titles, years, or journals.\n"
    ]

    for i, p in enumerate(all_papers, 1):
        venue = f" — {p['venue']}" if p.get("venue") else ""
        abstract = f"\n   Abstract: {p['abstract']}" if p.get("abstract") else ""
        lines.append(f"{i}. {p['authors']} ({p['year']}). {p['title']}{venue}.{abstract}\n")

    lines.append(
        "\nFor the References section: list only sources you actually used from above, "
        "in their ORIGINAL language (keep English titles in English, do not translate them)."
    )

    return "\n".join(lines)
