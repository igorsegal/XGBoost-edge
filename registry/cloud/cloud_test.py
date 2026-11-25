# -*- coding: utf-8 -*-
"""Проверка на сервере GitHub: база против локального паспорта, прогон тестов разработки, сверка с локальными
результатами. Экзаменационный период здесь не открывается никогда (ключ --exam не используется).

Использование: python cloud_test.py <папка базы> <отчёт.md>
"""
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REG = HERE.parent
sys.path.insert(0, str(HERE))
import make_manifest as mm


def run(cmd):
    print("$ " + " ".join(map(str, cmd)), flush=True)
    return subprocess.run([str(c) for c in cmd], cwd=REG).returncode


def check_base(base, lines):
    manifest = json.loads((HERE / "bars_manifest.json").read_text(encoding="utf-8"))["files"]
    lines += ["## База: сверка с локальной", "", "| Файл | Баров в облаке | Баров локально | Итог |", "|---|---|---|---|"]
    bad = 0
    for name, want in manifest.items():
        symbol = name.split("_")[0]
        path = base / symbol / f"{name}.bin"
        if not path.is_file():
            lines.append(f"| {name} | нет файла | {want['bars']} | **не собран** |")
            bad += 1
            continue
        have = mm.describe(path)
        if have["sha256"] == want["sha256"]:
            verdict = "совпал полностью"
        else:
            years = sorted(set(have["years"]) | set(want["years"]))
            diff = [y for y in years if have["years"].get(y) != want["years"].get(y)]
            verdict = "**расходится**, годы: " + (", ".join(diff) or "только заголовок")
            bad += 1
        lines.append(f"| {name} | {have['bars']} | {want['bars']} | {verdict} |")
    lines.append("")
    return bad


def run_tests(base, lines):
    work = REG / "_cloud"
    (work / "results").mkdir(parents=True, exist_ok=True)
    tester = work / "tester"
    if run(["g++", "-O2", "-std=c++17", "-o", tester, REG / "tester" / "tester.cpp"]):
        lines += ["## Тестер", "", "**не скомпилировался**", ""]
        return 1
    bad = 0
    lines += ["## Проверки программы", "", "| Проверка | Итог |", "|---|---|"]
    bars = base / "EURUSD" / "EURUSD_H1.bin"
    checks = [("реестр правил", [sys.executable, "validate_registry.py"]),
              ("индикаторы, часть 1", [sys.executable, "tests/xcheck_indicators.py", tester, bars]),
              ("индикаторы, часть 2", [sys.executable, "tests/xcheck_indicators2.py", tester, bars])]
    for title, script, prefix in (("Лондонский капкан", "xcheck_london.py", "london_trap"),
                                  ("Классический след", "xcheck_classic.py", "classic_trace"),
                                  ("Продолжение в Нью-Йорк", "xcheck_ny.py", "ny_continuation")):
        for pair in ("EURUSD", "GBPUSD", "USDJPY"):
            checks.append((f"{title}, {pair}", [sys.executable, f"tests/{script}", tester,
                                                f"configs/{prefix}_{pair}_M5.json", base]))
    for title, cmd in checks:
        code = run(cmd)
        bad += code != 0
        lines.append(f"| {title} | {'пройдена' if not code else '**не пройдена**'} |")
    lines += ["", "## Тесты, разработка 2020–2024", "",
              "| Тест | Правило | Сделок | Пунктов | Профит-фактор | Критерии | Сверка с локальным |",
              "|---|---|---|---|---|---|---|"]
    for cfg_path in sorted((REG / "configs").glob("*.json")):
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        name = cfg["test_name"]
        out = work / "results" / f"{name}.json"
        out.unlink(missing_ok=True)
        cfg["data"]["bars_dir"] = str(base)
        cfg["output"] = str(out)
        tmp = work / cfg_path.name
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        code = run([tester, tmp, "--selftest"])
        if code or not out.is_file():
            lines.append(f"| {name} | – | – | – | – | – | **ошибка тестера, код {code}** |")
            bad += 1
            continue
        got = json.loads(out.read_text(encoding="utf-8"))
        local_path = REG / "results" / f"{name}.json"
        if not local_path.is_file():
            match = "локального результата нет"
        elif json.loads(local_path.read_text(encoding="utf-8")) == got:
            match = "совпал"
        else:
            match = "**расходится**"
            bad += 1
        for rule in got["rules"]:
            s = rule["segments"][0]
            lines.append(f"| {name} | {rule['id']} | {s['trades']} | {s['net_pips']} | {s['profit_factor']} "
                         f"| {rule['verdict']} | {match} |")
    lines.append("")
    return bad


XGBOOST = "xgboost==2.1.4"


def run_ml(base, lines):
    """XGB_WF_01: столбцы H1, обучение по окнам, сделки считает тестер. Пишет раздел отчёта, возвращает число замечаний."""
    lines += ["## XGBoost (XGB_WF_01), разработка 2020–2024", ""]
    work = REG / "_cloud"
    builder = work / "build_indicators"
    try:
        if run([sys.executable, "-m", "pip", "install", "--quiet", XGBOOST]):
            raise RuntimeError("не установилась библиотека " + XGBOOST)
        if run(["g++", "-O2", "-std=c++17", "-o", builder, REG.parent / "tools" / "build_indicators.cpp"]):
            raise RuntimeError("не скомпилировалось построение столбцов")
    except Exception as e:  # отчёт должен записаться и при сбое
        lines += [f"**не запустился:** {e}", ""]
        return 1
    rows, bad, version = [], 0, ""
    for pair in ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"):
        ind = work / "ind" / pair
        ind.mkdir(parents=True, exist_ok=True)
        got, tail = None, ""
        if not run([builder, base / pair, ind, pair, "H1"]):
            cmd = [sys.executable, REG / "ml" / "xgb_wf.py", work / "tester", REG / "ml" / "configs" / f"xgb_{pair}_H1.json",
                   base, work / "ind", work / "ml"]
            p = subprocess.run([str(c) for c in cmd], cwd=REG, capture_output=True, text=True, errors="replace")
            print(p.stdout, p.stderr, flush=True)
            found = [s for s in p.stdout.splitlines() if s.startswith("RESULT ")]
            got = json.loads(found[-1][7:]) if found else None
            tail = (p.stderr or p.stdout).strip().splitlines()[-1:]
        else:
            tail = ["не построились столбцы"]
        if not got:
            rows.append(f"| {pair} | – | – | – | – | – | – | **ошибка:** {' '.join(tail)[:300]} |")
            bad += 1
            continue
        version = got["xgboost"]
        checks = "пройдены" if not got["mismatch"] and not got["leak_windows"] else \
            f"**не пройдены:** расхождений {got['mismatch']}, окон с подглядыванием {got['leak_windows']}"
        bad += checks != "пройдены"
        rows.append(f"| {pair} | {got['trades']} | {got['win_pct']} | {got['net_pips']} | {got['profit_factor']} "
                    f"| {got['pos_windows']} | {got['verdict']} | {checks} |")
    lines += [f"Версия библиотеки: {version or 'неизвестна'}.", "",
              "| Инструмент | Сделок | Прибыльных, % | Пунктов | Профит-фактор | Плюсовых окон | Критерии | Проверки |",
              "|---|---|---|---|---|---|---|---|"] + rows + [""]
    return bad


def main(base, report):
    base = Path(base).resolve()
    now = f"{dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC"
    lines = ["# Облачная сборка и тесты", "",
             f"Запуск: {now}, версия программ: {os.environ.get('GITHUB_SHA', '')[:7] or 'не с сервера'}.",
             "Экзамен (с 2025 года) в облаке не открывается.", ""]
    bad = check_base(base, lines)
    bad += run_tests(base, lines)
    if (REG / "_cloud" / "tester").exists():
        bad += run_ml(base, lines)
    lines += ["## Итог", "", "ВСЁ СОВПАЛО" if not bad else f"ЕСТЬ ЗАМЕЧАНИЯ: {bad}", ""]
    report = Path(report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    sys.exit(main(sys.argv[1], sys.argv[2]))
