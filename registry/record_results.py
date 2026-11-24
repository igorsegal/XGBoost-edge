#!/usr/bin/env python3
"""record_results.py - переносит результаты тестов (results\\*.json) в реестр.
Правило получает статус tested_pass, если ВСЕ основные (role=primary) тесты прошли по чистому отрезку,
иначе tested_fail. Правило со статусом tested_fail выключается по умолчанию.
Использование: python record_results.py [rules_registry.json] [results_dir]"""
import json, sys, os, glob, datetime
here = os.path.dirname(os.path.abspath(__file__))
reg_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "rules_registry.json")
res_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "results")
reg = json.load(open(reg_path, encoding="utf-8-sig"))
byid = {r["id"]: r for r in reg["rules"]}
today = datetime.date.today().isoformat()
prim = {}
for f in sorted(glob.glob(os.path.join(res_dir, "*.json"))):
    d = json.load(open(f, encoding="utf-8-sig"))
    for rr in d.get("rules", []):
        r = byid.get(rr["id"])
        if not r or r.get("status") == "example": continue   # учебные примеры в реестр результатов не заносятся
        clean = next((s for s in rr["segments"] if s["segment"] == "clean"), {})
        rec = {"date": today, "test": d["test_name"], "role": d.get("role", "primary"), "pair": d["pair"], "timeframe": d["timeframe"],
               "period": d["period"], "overrides": rr.get("overrides", "").strip(), "clean": clean,
               "validation": next((s for s in rr["segments"] if s["segment"] == "validation"), {}),
               "train": next((s for s in rr["segments"] if s["segment"] == "train"), {}), "verdict": rr["verdict"], "tester": d.get("tester")}
        r["results"] = [x for x in r["results"] if x.get("test") != rec["test"]] + [rec]
        if rec["role"] == "primary": prim.setdefault(r["id"], []).append(rr["verdict"])
for rid, vs in prim.items():
    r = byid[rid]
    r["status"] = "tested_pass" if all(v == "PASS" for v in vs) else "tested_fail"
    if r["status"] == "tested_fail": r["enabled_by_default"] = False
json.dump(reg, open(reg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for rid, vs in prim.items(): print(rid, byid[rid]["status"], vs)
