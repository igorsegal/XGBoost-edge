import json
import os
from typing import Dict, Optional
from openai import OpenAI

DEFAULT_BASE_URL = "https://models.inference.ai.azure.com"
DEFAULT_MODEL = "MAI-Code-2-Flash"

SYSTEM_PROMPT = """
Ты — судейская коллегия «Протокола Гриль» (Адвокат, Прокурор, Судья) для отбора торговых идей и признаков (features) в движок AHexaTraderEngine (XGBoost для валютных пар Forex Majors и Crosses).

Твоя задача: проанализировать статью MQL5 и вынести СТРОГИЙ БИНАРНЫЙ ВЕРДИКТ: "PASS" или "REJECT".

Правила отсева (мгновенный REJECT):
1. Статья про графику (GUI, Canvas, Cairo), сетевые утилиты (SFTP, Telegram, Watchdog), управление ордерами без торговой логики.
2. Стратегия требует биржевой стакан (Level 2), реальные фьючерсные объемы или акции/крипту и неприменима к спот-форексу (Forex Majors/Crosses).
3. Присутствует заглядывание в будущее (look-ahead bias, использование Close[0] или старшего таймфрейма до его закрытия) или субъективность ("на глаз").

Правила допуска (PASS):
- Есть строгая, замкнутая математика индикатора, фильтра рыночного режима (волатильность, смена режима, корреляция) или правила входа/выхода, пригодная для вычисления на закрытых барах [t-1] в C++/Python.

Верни ТОЛЬКО валидный JSON строго в следующем формате:
{
  "verdict": "PASS" или "REJECT",
  "reject_reason": "краткая причина отказа (если REJECT, иначе пустая строка)",
  "edge_type": "Feature_Engineering" | "Regime_Filter" | "Strategy_Rule",
  "forex_pairs": ["EURUSD", "GBPUSD", "USDJPY"],
  "timeframes": ["H1", "H4", "D1"],
  "formula_and_logic": "точное математическое описание признака или правила без утечки будущего",
  "author_oos_metrics": "метрики тестирования автора из статьи (если есть)",
  "judge_verdict_summary": "резюме судьи в 2 предложениях"
}
"""


def get_client() -> OpenAI:
    api_key = os.getenv("MAI_API_KEY") or os.getenv("GITHUB_TOKEN")
    base_url = os.getenv("MAI_BASE_URL") or DEFAULT_BASE_URL
    return OpenAI(api_key=api_key, base_url=base_url)


def evaluate_article(article: Dict) -> Optional[Dict]:
    client = get_client()
    model = os.getenv("MAI_MODEL") or DEFAULT_MODEL

    user_content = (
        f"TITLE: {article['title']}\n"
        f"YEAR: {article['published_year']}\n"
        f"URL: {article['url']}\n\n"
        f"TEXT:\n{article['text'][:24000]}"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        raw_json = response.choices[0].message.content
        result = json.loads(raw_json)
        result["url"] = article["url"]
        result["title"] = article["title"]
        result["published_year"] = article["published_year"]
        return result
    except Exception as e:
        print(f"[AI_WARN] Failed to evaluate {article['url']}: {e}")
        return None
