import os
import asyncio
import logging
from urllib.parse import urlparse
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SearchResult(BaseModel):
    title: str
    url: str
    publisher: str
    date: str
    excerpt: str


async def search_web(
    queries: list[str],
    source: str = "tavily"
) -> list[SearchResult]:
    if source == "tavily":
        return await _search_tavily(queries)
    raise ValueError(f"Unknown search source: {source}")


async def _search_tavily(queries: list[str]) -> list[SearchResult]:
    from tavily import TavilyClient
    client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    loop = asyncio.get_event_loop()

    async def search_one(query: str) -> list[SearchResult]:
        response = await loop.run_in_executor(None, lambda: client.search(
            query=query,
            search_depth="basic",
            max_results=5,
            include_answer=False
        ))
        results = []
        for r in response.get("results", []):
            results.append(SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                publisher=_extract_domain(r.get("url", "")),
                date=r.get("published_date", "") or "",
                excerpt=(r.get("content", "") or "")[:600]
            ))
        return results

    raw = await asyncio.gather(*[search_one(q) for q in queries], return_exceptions=True)

    seen_urls: set[str] = set()
    deduped: list[SearchResult] = []
    for i, batch in enumerate(raw):
        if isinstance(batch, Exception):
            logger.warning("Tavily query %d/%d failed: %s", i + 1, len(queries), batch)
            continue
        for r in batch:
            if r.url not in seen_urls:
                seen_urls.add(r.url)
                deduped.append(r)

    if not deduped:
        raise RuntimeError("All Tavily search queries failed. Check TAVILY_API_KEY.")

    return deduped


def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return url
