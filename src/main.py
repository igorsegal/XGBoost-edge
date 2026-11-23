import json
import os
import re

try:
    from src.scraper import append_seen_url, collect_batch, save_cursor
    from src.prefilter import prefilter
    from src.jury import run_pending, CAND_DIR
except ImportError:
    from scraper import append_seen_url, collect_batch, save_cursor
    from prefilter import prefilter
    from jury import run_pending, CAND_DIR

REJECTED_LOG = "data/rejected.tsv"


def _article_id(url: str) -> str:
    m = re.search(r"/articles/(\d+)", url)
    return m.group(1) if m else re.sub(r"\W+", "_", url)[-60:]


def save_candidate(art: dict) -> None:
    os.makedirs(CAND_DIR, exist_ok=True)
    with open(os.path.join(CAND_DIR, _article_id(art["url"]) + ".json"), "w", encoding="utf-8") as f:
        json.dump({**art, "status": "pending"}, f, ensure_ascii=False)


def log_rejected(art: dict, reason: str) -> None:
    os.makedirs(os.path.dirname(REJECTED_LOG), exist_ok=True)
    with open(REJECTED_LOG, "a", encoding="utf-8") as f:
        f.write(f"{art['url']}\t{reason}\t{art['title']}\n")


def run() -> None:
    print("Сбор статей MQL5 (фильтр 1 без модели, суд - отдельным шагом)")
    articles, next_cursor = collect_batch()
    print(f"Собрано статей: {len(articles)}")
    kept = 0
    for art in articles:
        reason = prefilter(art)
        if reason:
            log_rejected(art, reason)
        else:
            save_candidate(art)
            kept += 1
        append_seen_url(art["url"])
    # Курсор двигается всегда: от модели он не зависит.
    save_cursor(next_cursor)
    print(f"Отсеяно фильтром 1: {len(articles) - kept}, в очередь суда: {kept}. Курсор сохранён: {next_cursor}")
    try:
        run_pending()
    except Exception as e:
        print(f"[JURY] неожиданный сбой, сбор не затронут: {e}")


if __name__ == "__main__":
    run()
