"""
tools/web_scraper.py — Modular web scraping module for NEXUS Agent

Features:
  - requests + BeautifulSoup4 based scraping
  - rate-limit protection with configurable delay
  - retry logic with exponential backoff
  - structured content extraction (title, meta, main text, links)
  - reusable across all tools that need web content
"""
import time
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup

from config import config
from utils.logger import setup_logger
from utils.helpers import clean_html

log = setup_logger("scraper")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


@dataclass
class ScrapedPage:
    url: str
    status_code: int
    title: str = ""
    description: str = ""
    keywords: str = ""
    main_text: str = ""
    links: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and self.status_code == 200

    def to_summary(self, max_text: int = 2000) -> str:
        if not self.success:
            return f"❌ Failed to scrape {self.url}: {self.error}"
        lines = [
            f"🌐 **URL:** {self.url}",
            f"📄 **Title:** {self.title}",
        ]
        if self.description:
            lines.append(f"📝 **Description:** {self.description[:300]}")
        if self.headings:
            lines.append(f"📌 **Headings:** {' | '.join(self.headings[:5])}")
        if self.main_text:
            lines.append(f"\n**Content:**\n{self.main_text[:max_text]}")
        if self.links:
            lines.append(f"\n🔗 **Links found:** {len(self.links)}")
        return "\n".join(lines)


class WebScraper:
    """
    Rate-limited, retry-capable web scraper with structured content extraction.
    """

    def __init__(
        self,
        delay: float = None,
        max_retries: int = None,
        timeout: int = 15,
    ):
        self.delay = delay if delay is not None else config.SCRAPE_DELAY_SECONDS
        self.max_retries = max_retries if max_retries is not None else config.MAX_SCRAPE_RETRIES
        self.timeout = timeout
        self._last_request_time: float = 0.0
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request_time = time.time()

    def get(self, url: str) -> requests.Response:
        """Raw GET with retries and rate limiting."""
        self._rate_limit()
        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
                resp.raise_for_status()
                log.debug(f"GET {url} → {resp.status_code} (attempt {attempt})")
                return resp
            except requests.RequestException as exc:
                last_exc = exc
                wait = 2 ** attempt
                log.warning(f"Attempt {attempt} failed for {url}: {exc}. Retrying in {wait}s…")
                time.sleep(wait)
        raise last_exc

    def scrape(self, url: str) -> ScrapedPage:
        """Full page scrape — returns structured ScrapedPage."""
        try:
            resp = self.get(url)
            return self._parse(url, resp)
        except Exception as exc:
            log.error(f"Scrape failed for {url}: {exc}")
            return ScrapedPage(url=url, status_code=0, error=str(exc))

    def _parse(self, url: str, resp: requests.Response) -> ScrapedPage:
        page = ScrapedPage(url=url, status_code=resp.status_code)
        soup = BeautifulSoup(resp.text, "lxml")

        # Remove noise
        for tag in soup(["script", "style", "nav", "footer", "aside", "iframe", "noscript"]):
            tag.decompose()

        # Title
        title_tag = soup.find("title")
        page.title = title_tag.get_text(strip=True) if title_tag else ""

        # Meta tags
        for meta in soup.find_all("meta"):
            name = (meta.get("name") or meta.get("property") or "").lower()
            content = meta.get("content", "")
            if "description" in name:
                page.description = content
            elif "keywords" in name:
                page.keywords = content

        # Headings
        page.headings = [
            h.get_text(strip=True)
            for h in soup.find_all(["h1", "h2", "h3"])
            if h.get_text(strip=True)
        ][:10]

        # Main content — prefer article/main, fall back to body
        main_elem = (
            soup.find("article")
            or soup.find("main")
            or soup.find(id="content")
            or soup.find(class_="content")
            or soup.body
        )
        if main_elem:
            raw_text = main_elem.get_text(separator=" ", strip=True)
            page.main_text = clean_html(raw_text)

        # Links
        page.links = [
            a["href"]
            for a in soup.find_all("a", href=True)
            if a["href"].startswith("http")
        ][:50]

        return page

    def search_scrape(self, query: str, engine: str = "duckduckgo") -> list[ScrapedPage]:
        """
        Scrape search results for a query using DuckDuckGo HTML endpoint.
        Returns list of scraped result pages (up to 3).
        """
        search_url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
        try:
            resp = self.get(search_url)
            soup = BeautifulSoup(resp.text, "lxml")
            result_links = []

            for a in soup.find_all("a", class_="result__url"):
                href = a.get("href", "")
                if href.startswith("http"):
                    result_links.append(href)
            for a in soup.find_all("a", attrs={"data-testid": "result-extras-url-link"}):
                href = a.get("href", "")
                if href.startswith("http"):
                    result_links.append(href)

            # Also try result title links
            if not result_links:
                for a in soup.find_all("a", class_="result__a"):
                    href = a.get("href", "")
                    if "uddg=" in href:
                        import urllib.parse
                        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                        if "uddg" in parsed:
                            result_links.append(parsed["uddg"][0])

            log.info(f"Found {len(result_links)} results for query: {query}")
            pages = []
            for link in result_links[:3]:
                pages.append(self.scrape(link))
            return pages

        except Exception as exc:
            log.error(f"Search scrape failed: {exc}")
            return []


# Singleton scraper instance
scraper = WebScraper()
