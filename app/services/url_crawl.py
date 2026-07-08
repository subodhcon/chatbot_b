import logging
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("app.services.url_crawl")


class UrlCrawlService:
    """
    Service to crawl web pages, respect robots.txt rules, and extract page contents.
    """

    def __init__(self, user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"):
        self.user_agent = user_agent
        self._robots_parsers = {}

    def _get_robots_parser(self, base_url: str) -> RobotFileParser:
        if base_url not in self._robots_parsers:
            parser = RobotFileParser()
            robots_url = urljoin(base_url, "/robots.txt")
            try:
                # Fetch robots.txt synchronously using httpx
                resp = httpx.get(
                    robots_url,
                    timeout=5.0,
                    headers={
                        "User-Agent": self.user_agent,
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Connection": "keep-alive"
                    },
                    follow_redirects=True,
                )
                if resp.status_code == 200:
                    parser.parse(resp.text.splitlines())
                else:
                    # If robots.txt is missing, allow crawling
                    parser.parse([])
            except Exception as e:
                logger.warning(f"Could not fetch/parse robots.txt from {robots_url}: {e}")
                parser.parse([])
            self._robots_parsers[base_url] = parser
        return self._robots_parsers[base_url]

    def can_crawl(self, url: str) -> bool:
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        parser = self._get_robots_parser(base_url)
        return parser.can_fetch(self.user_agent, url)

    def clean_html(self, html_content: str) -> str:
        """
        Parses HTML, removes navigation, footers, headers, scripts, styles, and sidebars,
        and returns cleaned text content.
        """
        soup = BeautifulSoup(html_content, "html.parser")

        # Decompose non-content semantic tag blocks
        tags_to_remove = ["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"]
        for tag in list(soup.find_all(tags_to_remove)):
            if tag is not None:
                tag.decompose()

        # Decompose elements with navigation/footer indicators in ID or class
        for tag in list(soup.find_all(True)):
            if tag is None or tag.parent is None:
                continue
            # Check classes
            classes = tag.get("class", [])
            if classes is None:
                classes = []
            if isinstance(classes, str):
                classes = [classes]
            classes_str = " ".join(classes).lower()

            tag_id = tag.get("id", "")
            if tag_id is None:
                tag_id = ""
            tag_id = str(tag_id).lower()

            # Common navigation/footer/header markers
            nav_indicators = ["nav", "footer", "header", "sidebar", "menu", "aside", "widget"]
            if any(ind in classes_str or ind in tag_id for ind in nav_indicators):
                tag.decompose()

        # Extract remaining text lines cleanly
        lines = [line.strip() for line in soup.get_text(separator="\n").splitlines()]
        # Filter out empty lines
        return "\n".join(line for line in lines if line)

    def extract_links(self, html_content: str, current_url: str) -> list[str]:
        """
        Extracts all absolute links from HTML content that share the same origin/domain.
        """
        soup = BeautifulSoup(html_content, "html.parser")
        parsed_current = urlparse(current_url)
        current_domain = parsed_current.netloc

        links = []
        for anchor in list(soup.find_all("a", href=True)):
            if anchor is None or anchor.parent is None:
                continue
            href = anchor.get("href")
            if not href:
                continue
            abs_url = urljoin(current_url, href)
            parsed_abs = urlparse(abs_url)

            # Keep links on the same domain and using HTTP/HTTPS
            if parsed_abs.netloc == current_domain and parsed_abs.scheme in ["http", "https"]:
                # Strip fragments to normalize URLs
                normalized_url = abs_url.split("#")[0]
                if normalized_url not in links:
                    links.append(normalized_url)
        return links

    def normalize_url(self, url: str) -> str:
        """
        Normalizes a URL by standardizing the path and stripping fragments.
        """
        parsed = urlparse(url)
        path = parsed.path
        if not path:
            path = "/"
        # Reconstruct normalized URL
        normalized = f"{parsed.scheme}://{parsed.netloc.lower()}{path}"
        # Strip trailing slash if it's not the root path
        if len(path) > 1 and normalized.endswith("/"):
            normalized = normalized[:-1]
        return normalized

    def crawl(self, start_url: str, max_depth: int = 1) -> dict[str, str]:
        """
        Crawls starting from start_url up to max_depth.
        Returns a dictionary mapping crawled URLs to their cleaned text contents.
        """
        crawled_pages = {}
        visited = set()
        normalized_start = self.normalize_url(start_url)
        queue = [(normalized_start, 0)]  # Queue stores tuples of (url, current_depth)

        while queue:
            url, depth = queue.pop(0)

            if url in visited:
                continue
            visited.add(url)

            if not self.can_crawl(url):
                logger.info(f"Skipping url blocked by robots.txt: {url}")
                continue

            logger.info(f"Crawling URL: {url} at depth {depth}")
            try:
                resp = httpx.get(
                    url,
                    timeout=10.0,
                    headers={
                        "User-Agent": self.user_agent,
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Connection": "keep-alive"
                    },
                    follow_redirects=True,
                )
                if resp.status_code != 200:
                    logger.warning(f"Failed to fetch {url}: HTTP {resp.status_code}")
                    continue

                content_type = resp.headers.get("content-type", "")
                if "text/html" not in content_type:
                    logger.info(f"Skipping non-HTML resource: {url} ({content_type})")
                    continue

                html = resp.text
                cleaned_text = self.clean_html(html)
                crawled_pages[url] = cleaned_text

                # If we have depth left to explore, extract links and add to queue
                if depth < max_depth:
                    links = self.extract_links(html, url)
                    for link in links:
                        normalized_link = self.normalize_url(link)
                        if normalized_link not in visited:
                            queue.append((normalized_link, depth + 1))
            except Exception as e:
                logger.error(f"Error crawling {url}: {e}")

        return crawled_pages


url_crawl_service = UrlCrawlService()
