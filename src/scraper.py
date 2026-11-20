import json
import os
import random
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
BASE_URL = "https://mql5.com"
ARTICLES_INDEX_URL = "https://mql5.com/en/articles"
SEEN_URLS_PATH = "data/seen_urls.txt"
CURSOR_PATH = "data/cursor.json"
BATCH_LIMIT = 25
CUTOFF_YEAR = 2018
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://mql5.com/en/articles",
    "Connection": "keep-alive",
}
class RateLimitException(Exception):
    """Срабатывает при 403/429 для немедленной остановки парсера."""
def load_seen_urls() -> Set[str]:
    if not os.path.exists(SEEN_URLS_PATH):
        return set()
    with open(SEEN_URLS_PATH, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}
def append_seen_url(url: str) -> None:
    os.makedirs(os.path.dirname(SEEN_URLS_PATH), exist_ok=True)
    with open(SEEN_URLS_PATH, "a", encoding="utf-8") as f:
        f.write(url + "\n")
def load_cursor() -> Dict:
    if not os.path.exists(CURSOR_PATH):
        return {"backfill_page": 1, "cutoff_year": CUTOFF_YEAR, "backfill_completed": False}
    with open(CURSOR_PATH, "r", encoding="utf-8") as f:
        return json.load(f)
def save_cursor(cursor: Dict) -> None:
    os.makedirs(os.path.dirname(CURSOR_PATH), exist_ok=True)
    with open(CURSOR_PATH, "w", encoding="utf-8") as f:
        json.dump(cursor, f, indent=2)
def polite_sleep(step_count: int) -> None:
    delay = random.uniform(5.0, 12.0)
    if step_count > 0 and step_count % 10 == 0:
        delay += 15.0
    time.sleep(delay)
def fetch_html(session: requests.Session, url: str) -> str:
    resp = session.get(url, headers=HEADERS, timeout=25)
    if resp.status_code in (403, 429):
        raise RateLimitException(f"HTTP {resp.status_code} on {url}. Stopping immediately.")
    resp.raise_for_status()
    return resp.text
def extract_article_links(list_html: str) -> List[str]:
    soup = BeautifulSoup(list_html, "lxml")
    links: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.match(r"^/en/articles/\d+$", href):
            full_url = urljoin(BASE_URL, href)
            if full_url not in links:
                links.append(full_url)
    return links
def parse_article_page(html: str, url: str) -> Optional[Dict]:
    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else "Untitled"
    pub_year = datetime.utcnow().year
    pub_date_str = ""
    time_tag = soup.find("time")
    if time_tag:
        pub_date_str = time_tag.get("datetime") or time_tag.get_text(strip=True)
        year_match = re.search(r"(20\d{2})", pub_date_str)
        if year_match:
            pub_year = int(year_match.group(1))
    content_div = soup.find("div", class_=re.compile(r"(article|content|text)", re.I))
    raw_text = content_div.get_text("\n", strip=True) if content_div else soup.get_text("\n", strip=True)
    return {
        "url": url,
        "title": title,
        "published_date": pub_date_str,
        "published_year": pub_year,
        "text": raw_text[:45000],
    }
def collect_batch() -> List[Dict]:
    seen_urls = load_seen_urls()
    cursor = load_cursor()
    session = requests.Session()
    collected: List[Dict] = []
    request_counter = 0
    try:
        first_page_html = fetch_html(session, ARTICLES_INDEX_URL)
        request_counter += 1
        fresh_links = extract_article_links(first_page_html)
        for link in fresh_links:
            if len(collected) >= BATCH_LIMIT:
                break
            if link in seen_urls:
                continue
            polite_sleep(request_counter)
            article_html = fetch_html(session, link)
            request_counter += 1
            parsed = parse_article_page(article_html, link)
            if parsed:
                collected.append(parsed)
                seen_urls.add(link)
        while len(collected) < BATCH_LIMIT and not cursor.get("backfill_completed", False):
            page_num = cursor["backfill_page"]
            page_url = f"{ARTICLES_INDEX_URL}/page{page_num}" if page_num > 1 else ARTICLES_INDEX_URL
            if page_num > 1:
                polite_sleep(request_counter)
                page_html = fetch_html(session, page_url)
                request_counter += 1
            else:
                page_html = first_page_html
            links = extract_article_links(page_html)
            if not links:
                cursor["backfill_completed"] = True
                break
            reached_cutoff = False
            for link in links:
                if len(collected) >= BATCH_LIMIT:
                    break
                if link in seen_urls:
                    continue
                polite_sleep(request_counter)
                article_html = fetch_html(session, link)
                request_counter += 1
                parsed = parse_article_page(article_html, link)
                if not parsed:
                    continue
                if parsed["published_year"] < cursor.get("cutoff_year", CUTOFF_YEAR):
                    reached_cutoff = True
                    cursor["backfill_completed"] = True
                    break
                collected.append(parsed)
                seen_urls.add(link)
            if not reached_cutoff and len(collected) < BATCH_LIMIT:
                cursor["backfill_page"] = page_num + 1
    except RateLimitException as e:
        print(f"[CIRCUIT BREAKER] {e}")
    finally:
        save_cursor(cursor)
    return collected
