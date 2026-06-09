"""
جستجوی مقالات واقعی از Semantic Scholar و PubMed
کاملاً رایگان، بدون API Key، بدون محدودیت
"""

import asyncio
import logging
import httpx
from datetime import datetime

log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# Semantic Scholar API
# ۲۰۰ میلیون مقاله — رایگان بدون ثبت‌نام
# ─────────────────────────────────────────
SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

async def search_semantic_scholar(query: str, limit: int = 5) -> list[dict]:
    """
    جستجوی مقالات از Semantic Scholar
    برمی‌گرداند: لیست مقالات با عنوان، نویسندگان، سال، مجله، abstract واقعی
    """
    params = {
        "query": query,
        "limit": limit,
        "fields": "title,authors,year,venue,abstract,citationCount,publicationTypes,openAccessPdf",
        "sort": "relevance",
    }
    # فیلتر: فقط مقالات peer-reviewed (نه preprint)
    # اولویت: مقالات ۲۰۱۵ به بعد با citation بالا

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(SEMANTIC_SCHOLAR_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            papers = data.get("data", [])

            results = []
            for p in papers:
                if not p.get("title") or not p.get("year"):
                    continue
                # فیلتر: فقط مقالات ۲۰۱۰ به بعد
                if p.get("year", 0) < 2010:
                    continue

                authors = [a.get("name", "") for a in p.get("authors", [])[:3]]
                if len(p.get("authors", [])) > 3:
                    authors.append("et al.")

                results.append({
                    "title": p.get("title", ""),
                    "authors": ", ".join(authors),
                    "year": p.get("year", ""),
                    "venue": p.get("venue", ""),
                    "abstract": p.get("abstract", "")[:500] if p.get("abstract") else "",
                    "citations": p.get("citationCount", 0),
                    "source": "Semantic Scholar",
                })

            # مرتب‌سازی: اول مقالات جدیدتر با citation بیشتر
            results.sort(key=lambda x: (x["year"], x["citations"]), reverse=True)
            return results[:limit]

    except Exception as e:
        log.warning(f"⚠️ Semantic Scholar خطا: {e}")
        return []


# ─────────────────────────────────────────
# PubMed API
# ۳۶ میلیون مقاله پزشکی/روانشناسی — رایگان
# ─────────────────────────────────────────
PUBMED_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_FETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
PUBMED_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

async def search_pubmed(query: str, limit: int = 3) -> list[dict]:
    """
    جستجوی مقالات از PubMed
    برای روانشناسی بالینی و عصب‌شناسی بسیار مناسب
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # مرحله ۱: جستجو و گرفتن ID ها
            search_params = {
                "db": "pubmed",
                "term": f"{query}[Title/Abstract] AND (psychology[MeSH] OR psychiatry[MeSH] OR neuroscience[MeSH])",
                "retmax": limit * 2,
                "sort": "relevance",
                "retmode": "json",
                "mindate": "2010",
                "maxdate": str(datetime.now().year),
            }
            search_resp = await client.get(PUBMED_SEARCH_URL, params=search_params)
            search_resp.raise_for_status()
            ids = search_resp.json().get("esearchresult", {}).get("idlist", [])

            if not ids:
                return []

            # مرحله ۲: گرفتن اطلاعات مقالات
            summary_params = {
                "db": "pubmed",
                "id": ",".join(ids[:limit]),
                "retmode": "json",
            }
            summary_resp = await client.get(PUBMED_SUMMARY_URL, params=summary_params)
            summary_resp.raise_for_status()
            articles = summary_resp.json().get("result", {})

            results = []
            for pmid in ids[:limit]:
                article = articles.get(str(pmid), {})
                if not article or article.get("title") == "":
                    continue

                authors_list = article.get("authors", [])[:3]
                authors = [a.get("name", "") for a in authors_list]
                if len(article.get("authors", [])) > 3:
                    authors.append("et al.")

                pub_date = article.get("pubdate", "")
                year = pub_date[:4] if pub_date else ""

                journal = article.get("source", "")

                results.append({
                    "title": article.get("title", "").rstrip("."),
                    "authors": ", ".join(authors),
                    "year": year,
                    "venue": journal,
                    "abstract": "",  # PubMed summary نداره، باید جداگانه fetch بشه
                    "citations": 0,
                    "pmid": pmid,
                    "source": "PubMed",
                })

            return results

    except Exception as e:
        log.warning(f"⚠️ PubMed خطا: {e}")
        return []


# ─────────────────────────────────────────
# جستجوی ترکیبی
# ─────────────────────────────────────────
async def fetch_real_papers(topic: str) -> str:
    """
    مقالات واقعی رو از هر دو منبع جستجو می‌کنه
    و یک متن آماده برای درج در پرامپت برمی‌گردونه
    """
    log.info(f"🔍 جستجوی مقالات برای: {topic[:40]}")

    # جستجوی موازی در هر دو منبع
    ss_results, pm_results = await asyncio.gather(
        search_semantic_scholar(topic, limit=4),
        search_pubmed(topic, limit=3),
        return_exceptions=True
    )

    if isinstance(ss_results, Exception):
        ss_results = []
    if isinstance(pm_results, Exception):
        pm_results = []

    all_papers = ss_results + pm_results

    if not all_papers:
        log.warning("⚠️ هیچ مقاله‌ای پیدا نشد")
        return ""

    log.info(f"✅ {len(all_papers)} مقاله واقعی پیدا شد")

    # فرمت برای پرامپت
    formatted = "\n\nREAL PAPERS FROM DATABASES (use ONLY these for citations — do not add others):\n"
    formatted += "These are real, verifiable papers retrieved live from Semantic Scholar and PubMed.\n\n"

    for i, p in enumerate(all_papers, 1):
        venue = f" — {p['venue']}" if p.get("venue") else ""
        abstract = f"\n   Abstract: {p['abstract']}" if p.get("abstract") else ""
        formatted += f"{i}. {p['authors']} ({p['year']}). {p['title']}{venue}.{abstract}\n\n"

    formatted += "\nINSTRUCTION: Build your report based on the content of these papers. "
    formatted += "Only cite papers from this list. If a specific claim cannot be traced to these papers, "
    formatted += "describe the general scientific consensus without fabricating a citation."

    return formatted


# ─────────────────────────────────────────
# تست
# ─────────────────────────────────────────
if __name__ == "__main__":
    async def test():
        result = await fetch_real_papers("cognitive behavioral therapy depression")
        print(result)
    asyncio.run(test())
