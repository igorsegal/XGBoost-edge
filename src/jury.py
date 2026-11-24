"""Фильтр 2: суд из трёх ролей. Необязателен: без ключа или при сбое
кандидаты просто остаются в очереди. Сканер от него не зависит."""
import glob
import json
import os
import time
import urllib.error
import urllib.request
from typing import Dict, Optional

DATA_DIR = os.getenv("XGB_DATA", "data")
CAND_DIR = os.path.join(DATA_DIR, "candidates")
PASSED_PATH = os.path.join(DATA_DIR, "passed_edges.jsonl")
SPEC_DIR = os.path.join(DATA_DIR, "specs")
JURY_LIMIT = int(os.getenv("JURY_LIMIT", "0"))  # 0 = по умолчанию для провайдера
PAUSE_SEC = float(os.getenv("JURY_PAUSE", "6"))
LOG_PATH = os.path.join(DATA_DIR, "jury_log.txt")


def _log(msg: str) -> None:
    """Печать + файл в репозитории: итог каждого запуска виден без захода в журнал GitHub."""
    print(msg)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(msg) + "\n")

ROLES = {
    "advocate": (
        "Ты адвокат идеи из статьи про торговлю на спот-форексе. Твоя задача: найти в тексте статьи конкретные "
        "основания считать, что описанное правило или признак может давать торговое преимущество и что его можно "
        "проверить на исторических данных. Опирайся только на то, что реально написано в статье, и называй "
        "конкретные элементы (формулу, условие входа, фильтр, параметр, результат автора). Не повторяй общие слова. "
        "Если оснований нет, так и скажи. Ответ только JSON с ключами: for (список конкретных доводов из текста, "
        "по одной фразе) и strength (целое число от 0 до 10)."
    ),
    "prosecutor": (
        "Ты прокурор. Найди в статье конкретные пороки идеи, опираясь только на текст статьи. Фатальными считай "
        "только такие: (1) в самом торговом сигнале используются данные будущих баров; (2) правило нельзя записать "
        "точной формулой, потому что статья даёт лишь общее описание или архитектуру модели без условий входа "
        "(выход и стоп отсутствовать могут); (3) нужны данные, которых нет у спот-форекса (биржевой стакан, реальные объёмы, акции, криптовалюта); "
        "(4) в основе мартингейл, сетка или усреднение убытков; (5) статья не про торговое правило, а про "
        "инфраструктуру, графику, оптимизатор или учебный пример. Отсутствие у автора теста вне выборки, спреда или "
        "комиссий фатальным НЕ считай: мы проверим идею сами. Назови такие недостатки отдельно. Ответ только JSON с "
        "ключами: against (список конкретных пороков с указанием, где в статье это видно), fatal (true или false), "
        "non_fatal (список недостатков, которые мы исправим при собственной проверке)."
    ),
    "judge": (
        "Ты судья. Даны текст статьи и доводы адвоката и прокурора. Вынеси вердикт PASS или REJECT. PASS, если из "
        "статьи можно составить полное детерминированное правило для проверки на закрытых барах спот-форекса: "
        "чётко описанное условие входа (направление и условия) с параметрами и их значениями. Если выход или стоп "
        "в статье не описаны, это НЕ причина отказа: напиши в exit_rule или stop_rule 'не указан в статье', выход "
        "подставит наш тестер. Если статья описывает фильтр сигналов или ансамбль простых правил и способ получения "
        "итогового направления очевиден из формул (например знак взвешенной суммы), это PASS, а очевидное "
        "допущение запиши в formula_and_logic словами 'допущение'. Отсутствие теста вне "
        "выборки у автора не причина отказа, мы проверим сами. Причина отказа только фатальный порок: данные "
        "будущего в сигнале, невозможность записать правило, неприменимые данные, мартингейл или сетка, статья не про "
        "правило. При PASS извлеки правило как можно точнее, строго по тексту статьи, ничего не выдумывая; если "
        "какой-то параметр в статье не назван, напиши, что он не указан. Пиши по-русски. Ответ только JSON с ключами: verdict "
        "(PASS или REJECT), reject_reason (текст, пусто при PASS), formula_and_logic (точное описание правила), "
        "entry_long, entry_short, exit_rule, stop_rule (условия строкой, пусто если нет), parameters (словарь "
        "имя параметра и значение из статьи), timeframes (список), forex_pairs (список), author_oos_metrics "
        "(что автор сообщает о результатах, строкой), summary (два предложения)."
    ),
}


def _read_key_file(name: str) -> str:
    """Ключ из локального файла рядом со скриптом (в репозиторий не попадает: см. .gitignore)."""
    try:
        with open(name, encoding="utf-8-sig") as f:
            return f.read().strip()
    except OSError:
        return ""


def _client():
    """Возвращает (cfg, model, лимит_статей) или None. Без библиотеки openai: обычный HTTP."""
    dash = os.getenv("DASHSCOPE_API_KEY") or _read_key_file("dashscope_key.txt")
    if dash:
        return {"base": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                "alt_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "key": dash, "json_mode": True}, "qwen-plus", 20
    if os.getenv("OPENAI_API_KEY"):
        return {"base": "https://api.openai.com/v1",
                "key": os.environ["OPENAI_API_KEY"], "json_mode": True}, "gpt-4o-mini", 20
    if os.getenv("GITHUB_TOKEN"):
        # GitHub Models: бесплатно, ключ не нужен, но есть дневные лимиты запросов
        return {"base": "https://models.github.ai/inference",
                "key": os.environ["GITHUB_TOKEN"], "json_mode": False}, os.getenv("JURY_MODEL", "openai/gpt-4o"), 5
    return None


MAX_TOKENS = {"advocate": 1500, "prosecutor": 1500, "judge": 4000}


def _ask(cfg, model: str, role: str, content: str) -> Optional[Dict]:
    body = {"model": model, "temperature": 0.0, "max_tokens": MAX_TOKENS[role],
            "messages": [{"role": "system", "content": ROLES[role] + " Отвечай только JSON."},
                         {"role": "user", "content": content}]}
    if cfg.get("json_mode"):
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(
        cfg["base"] + "/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": "Bearer " + cfg["key"], "Content-Type": "application/json",
                 "Accept": "application/json", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 401 and cfg.get("alt_base"):
            # ключ может быть от другого региона DashScope: пробуем второй адрес и запоминаем
            cfg["base"], cfg["alt_base"] = cfg["alt_base"], None
            _log("[JURY] 401 на первом адресе DashScope, пробую второй регион")
            return _ask(cfg, model, role, content)
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
    try:
        text = json.loads(raw)["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError(f"неожиданный ответ сервера: {raw[:300]}")
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
    return json.loads(text)


def _ask_retry(cfg, model: str, role: str, content: str) -> Optional[Dict]:
    """Один повтор, если модель вернула битый JSON (например, оборванный ответ)."""
    try:
        return _ask(cfg, model, role, content)
    except json.JSONDecodeError:
        _log(f"[JURY] битый JSON от роли {role}, повторяю один раз")
        return _ask(cfg, model, role, content)


def _excerpt(t: str) -> str:
    """Статья целиком: параметры и логика лежат в середине текста, обрезать нельзя.
    Верхняя граница нужна только как защита от аномально длинного текста."""
    return t if len(t) <= 90000 else t[:50000] + "\n...\n" + t[-40000:]


def run_pending() -> None:
    files = sorted(glob.glob(os.path.join(CAND_DIR, "*.json")))
    pending = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        if d.get("status") == "pending" or (os.getenv("XGB_REJUDGE") == "1" and d.get("status") == "rejected"):
            pending.append((f, d))
    _log(f"[JURY] в очереди: {len(pending)}")
    if not pending:
        return
    cl = _client()
    if cl is None:
        _log("[JURY] ключа нет - суд пропущен, кандидаты ждут. Сбор статей не затронут.")
        return
    client, model, default_limit = cl
    limit = JURY_LIMIT or default_limit
    done = 0
    for f, d in pending[:limit]:
        try:
            base = f"TITLE: {d['title']}\nYEAR: {d.get('published_year')}\n\nTEXT:\n{_excerpt(d['text'])}"
            adv = _ask_retry(client, model, "advocate", base)
            pro = _ask_retry(client, model, "prosecutor", base)
            ver = _ask_retry(client, model, "judge", base + f"\n\nADVOCATE: {json.dumps(adv, ensure_ascii=False)}\nPROSECUTOR: {json.dumps(pro, ensure_ascii=False)}")
            verdict = str(ver.get("verdict", "")).upper()
            if verdict not in ("PASS", "REJECT"):
                raise ValueError("bad verdict")
            if verdict == "PASS":
                has_entry = any(len(str(ver.get(k) or "").strip()) >= 10 for k in ("entry_long", "entry_short"))
                if len(str(ver.get("formula_and_logic", ""))) < 20 or not has_entry:
                    verdict, ver["reject_reason"] = "REJECT", "PASS без формулы или без условия входа"
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
            _log(f"[JURY] {verdict}: {d['title']}")
            done += 1
            time.sleep(PAUSE_SEC)
        except Exception as e:
            _log(f"[JURY] сбой на {d.get('url')}: {e} - останется в очереди")
            if "HTTP 429" in str(e) or "rate limit" in str(e).lower():
                _log("[JURY] лимит запросов исчерпан - остановка, продолжим в следующий запуск")
                break
    _log(f"[JURY] обработано: {done}")
