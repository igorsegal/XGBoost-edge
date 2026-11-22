import json
import os
from ai_judge import evaluate_article
from scraper import append_seen_url, collect_batch

PASSED_EDGES_PATH = "data/passed_edges.jsonl"


def save_passed_edge(record: dict) -> None:
    os.makedirs(os.path.dirname(PASSED_EDGES_PATH), exist_ok=True)
    with open(PASSED_EDGES_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run() -> None:
    print("Starting MQL5 polite collection + MAI Grill Protocol...")
    articles = collect_batch()
    print(f"Collected {len(articles)} articles for judicial review.")

    for art in articles:
        verdict_data = evaluate_article(art)
        if verdict_data is None:
            print(f" - [SKIP_API] {art['url']} (will retry next run)")
            continue

        verdict = verdict_data.get("verdict", "REJECT").upper()
        if verdict == "PASS":
            print(f" - [PASS] {art['title']} ({art['url']})")
            save_passed_edge(verdict_data)
        else:
            reason = verdict_data.get("reject_reason", "No edge")
            print(f" - [REJECT] {art['title']} -> {reason}")

        append_seen_url(art["url"])


if __name__ == "__main__":
    run()
