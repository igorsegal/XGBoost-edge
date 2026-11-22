import json
import os
import random
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE_URL = "https://mql5.com"
ARTICLES_INDEX_URL = "https://mql5.com/en/articles"
SEEN_URLS_PATH = "data/seen_urls.txt"
CURSOR_PATH = "data/cursor.json"

BATCH_LIMIT = 15
CUTOFF_YEAR = 2018


def load_seen_urls() -> Set[str]:
    if not os.path.exists(SEEN_URLS_PATH):
        return set()
    with open(SEEN_URLS_PATH, "r", encoding="utf-8-sig") as f:
        return {line.strip() for line in f if line.strip()}


def append_seen_url(url: str) -> None:
    os.makedirs(os.path.dirname(SEEN_URLS_PATH), exist_ok=True)
    with open(SEEN_URLS_PATH, "a", encoding="utf-8") as f:
        f.write(url + "\n")


def load_cursor() -> Dict:
    if not os.path.exists(CURSOR_PATH):
        return {"backfill_page": 1, "cutoff_year": CUTOFF_YEAR, "backfill_completed": False}
    with open(CURSOR_PATH, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_cursor(cursor: Dict) -> None:
    os.makedirs(os.path.dirname(CURSOR_PATH), exist_ok=True)
    with open(CURSOR_PATH, "w", encoding="utf-8") as f:
        json.dump(cursor, f, indent=2)


def polite_sleep(step_count: int) -> None:
    delay = random.uniform(6.0, 14.0)
    if step_count > 0 and step_count % 8 == 0:
        delay += 15.0
    time.sleep(delay)


def fetch_html_browser(page, url: str) -> Optional[str]:
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=35000)
        if not resp:
            return None
        if resp.status in (403, 429, 503):
            page.wait_for_timeout(7000)
            html = page.content()
            if "Just a moment" in html or resp.status in (403, 429, 503):
                return "BLOCKED"
        page.wait_for_timeout(1500)
        return page.content()
    except Exception:
        return None


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
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

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

    if len(raw_text) < 500:
        return None

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
    collected: List[Dict] = []
    request_counter = 0
    consecutive_blocks = 0

    with sync_playwright() as p:
        executable = "/usr/bin/google-chrome" if os.path.exists("/usr/bin/google-chrome") else None
        browser = p.chromium.launch(
            executable_path=executable,
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()

        try:
            first_page_html = fetch_html_browser(page, ARTICLES_INDEX_URL)
            if not first_page_html or first_page_html == "BLOCKED":
                print("[STOP] Index page unavailable or blocked.")
                return collected
            request_counter += 1
            fresh_links = extract_article_links(first_page_html)

            for link in fresh_links:
                if len(collected) >= BATCH_LIMIT or consecutive_blocks >= 3:
                    break
                if link in seen_urls:
                    continue
                polite_sleep(request_counter)
                article_html = fetch_html_browser(page, link)
                request_counter += 1
                if article_html == "BLOCKED":
                    consecutive_blocks += 1
                    time.sleep(15)
                    continue
                if not article_html:
                    continue
                consecutive_blocks = 0
                parsed = parse_article_page(article_html, link)
                if parsed:
                    collected.append(parsed)
                    seen_urls.add(link)

            while (
                len(collected) < BATCH_LIMIT
                and not cursor.get("backfill_completed", False)
                and consecutive_blocks < 3
            ):
                page_num = cursor["backfill_page"]
                page_url = f"{ARTICLES_INDEX_URL}/page{page_num}" if page_num > 1 else ARTICLES_INDEX_URL

                if page_num > 1:
                    polite_sleep(request_counter)
                    page_html = fetch_html_browser(page, page_url)
                    request_counter += 1
                    if page_html == "BLOCKED":
                        consecutive_blocks += 1
                        break
                    if not page_html:
                        break
                else:
                    page_html = first_page_html

                links = extract_article_links(page_html)
                if not links:
                    cursor["backfill_completed"] = True
                    break

                reached_cutoff = False
                for link in links:
                    if len(collected) >= BATCH_LIMIT or consecutive_blocks >= 3:
                        break
                    if link in seen_urls:
                        continue
                    polite_sleep(request_counter)
                    article_html = fetch_html_browser(page, link)
                    request_counter += 1
                    if article_html == "BLOCKED":
                        consecutive_blocks += 1
                        time.sleep(15)
                        continue
                    if not article_html:
                        continue
                    consecutive_blocks = 0
                    parsed = parse_article_page(article_html, link)
                    if not parsed:
                        continue
                    if parsed["published_year"] < cursor.get("cutoff_year", CUTOFF_YEAR):
                        reached_cutoff = True
                        cursor["backfill_completed"] = True
                        break
                    collected.append(parsed)
                    seen_urls.add(link)

                if not reached_cutoff and len(collected) < BATCH_LIMIT and consecutive_blocks < 3:
                    cursor["backfill_page"] = page_num + 1
        finally:
            browser.close()
            save_cursor(cursor)

    return collected
