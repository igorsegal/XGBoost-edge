from scraper import append_seen_url, collect_batch
def run() -> None:
    print("Starting MQL5 polite collection batch...")
    articles = collect_batch()
    print(f"Collected {len(articles)} new articles.")
    for art in articles:
        print(f" - [{art['published_year']}] {art['title']} ({art['url']})")
        append_seen_url(art["url"])
if __name__ == "__main__":
    run()
