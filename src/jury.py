"""Фильтр 2: суд из трёх ролей. Необязателен: без ключа или при сбое
кандидаты просто остаются в очереди. Сканер от него не зависит."""
import glob
import json
import os
import time
from typing import Dict, Optional

CAND_DIR = "data/candidates"
PASSED_PATH = "data/passed_edges.jsonl"
SPEC_DIR = "data/specs"
JURY_LIMIT = int(os.getenv("JURY_LIMIT", "0"))  # 0 = по умолчанию для провайдера
PAUSE_SEC = float(os.getenv("JURY_PAUSE", "6"))

ROLES = {
    "advocate": "Ты адвокат. Найди в статье всё, что говорит за наличие устойчивого преимущества (edge) на спот-форексе: замкнутая математика, правила на закрытых барах, тест вне выборки. Ответ: JSON {\"for\": [\"...\"], \"strength\": 0-10}.",
    "prosecutor": "Ты прокурор. Найди всё, что убивает идею: заглядывание в будущее, подгонка параметров, мартингейл/сетка, нет теста вне выборки, нет спреда и комиссий, нужен стакан/акции/крипта, субъективность. Ответ: JSON {\"against\": [\"...\"], \"fatal\": true|false}.",
    "judge": "Ты судья. Даны доводы адвоката и прокурора и текст статьи. Вынеси вердикт. PASS только если нет фатальных пороков и правило можно полностью записать формулой на закрытых барах. Ответ: JSON {\"verdict\": \"PASS\"|\"REJECT\", \"reject_reason\": \"\", \"formula_and_logic\": \"точные правила входа/выхода и параметры\", \"entry_long\": \"условие на закрытых барах [1],[2]\", \"entry_short\": \"\", \"exit_rule\": \"\", \"stop_rule\": \"\", \"parameters\": {\"имя\": \"значение\"}, \"timeframes\": [\"H1\"], \"forex_pairs\": [\"EURUSD\"], \"author_oos_metrics\": \"\", \"summary\": \"2 предложения\"}.",
}


def _client():
    """Возвращает (client, model, лимит_статей) или None. Проверяется один раз за запуск."""
    try:
        from openai import OpenAI
    except Exception as e:
        print(f"[JURY] библиотека openai недоступна: {e}")
        return None
    if os.getenv("DASHSCOPE_API_KEY"):
        return OpenAI(api_key=os.environ["DASHSCOPE_API_KEY"],
                      base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"), "qwen-plus", 20
    if os.getenv("OPENAI_API_KEY"):
        return OpenAI(api_key=os.environ["OPENAI_API_KEY"]), "gpt-4o-mini", 20
    if os.getenv("GITHUB_TOKEN"):
        # GitHub Models: бесплатно, ключ не нужен, но есть дневные лимиты запросов
        return OpenAI(api_key=os.environ["GITHUB_TOKEN"],
                      base_url="https://models.github.ai/inference"), os.getenv("JURY_MODEL", "openai/gpt-4o"), 5
    return None


def _ask(client, model: str, role: str, content: str) -> Optional[Dict]:
    r = client.chat.completions.create(
        model=model, temperature=0.0, max_tokens=1200,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": ROLES[role]},
                  {"role": "user", "content": content}],
    )
    return json.loads(r.choices[0].message.content)


def _excerpt(t: str) -> str:
    return t if len(t) <= 26000 else t[:14000] + "\n...\n" + t[-12000:]


def run_pending() -> None:
    files = sorted(glob.glob(os.path.join(CAND_DIR, "*.json")))
    pending = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        if d.get("status") == "pending":
            pending.append((f, d))
    print(f"[JURY] в очереди: {len(pending)}")
    if not pending:
        return
    cl = _client()
    if cl is None:
        print("[JURY] ключа нет - суд пропущен, кандидаты ждут. Сбор статей не затронут.")
        return
    client, model, default_limit = cl
    limit = JURY_LIMIT or default_limit
    done = 0
    for f, d in pending[:limit]:
        try:
            base = f"TITLE: {d['title']}\nYEAR: {d.get('published_year')}\n\nTEXT:\n{_excerpt(d['text'])}"
            adv = _ask(client, model, "advocate", base)
            pro = _ask(client, model, "prosecutor", base)
            ver = _ask(client, model, "judge", base + f"\n\nADVOCATE: {json.dumps(adv, ensure_ascii=False)}\nPROSECUTOR: {json.dumps(pro, ensure_ascii=False)}")
            verdict = str(ver.get("verdict", "")).upper()
            if verdict not in ("PASS", "REJECT"):
                raise ValueError("bad verdict")
            if verdict == "PASS" and len(str(ver.get("formula_and_logic", ""))) < 20:
                verdict, ver["reject_reason"] = "REJECT", "empty formula"
            d["status"] = "passed" if verdict == "PASS" else "rejected"
            d["jury"] = {"advocate": adv, "prosecutor": pro, "judge": ver}
            with open(f, "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False)
            if verdict == "PASS":
                with open(PASSED_PATH, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"url": d["url"], "title": d["title"],
                                         "published_year": d.get("published_year"), **ver},
                                        ensure_ascii=False) + "\n")
            if verdict == "PASS":
                os.makedirs(SPEC_DIR, exist_ok=True)
                with open(os.path.join(SPEC_DIR, os.path.basename(f)), "w", encoding="utf-8") as fh:
                    json.dump({"url": d["url"], "title": d["title"], "published_year": d.get("published_year"), **ver},
                              fh, ensure_ascii=False, indent=1)
            print(f"[JURY] {verdict}: {d['title']}")
            done += 1
            time.sleep(PAUSE_SEC)
        except Exception as e:
            print(f"[JURY] сбой на {d.get('url')}: {e} - останется в очереди")
            if "429" in str(e) or "rate" in str(e).lower():
                print("[JURY] лимит запросов исчерпан - остановка, продолжим в следующий запуск")
                break
    print(f"[JURY] обработано: {done}")
