#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""calc_verify.py — верификация расчётов документа и покрытие чисел проверками.

Каждое число-результат в документе должно иметь воспроизводимую формулу.
Скрипт пересчитывает заявленные расчёты и показывает, какие заметные числа
документа остались без проверки.

Запуск:
    # разовый пересчёт
    python .kilo/skills/editor/utils/calc_verify.py --expr "(8_000_000-5_000_000)*0.13" \
        --expect 390000 --label "НДФЛ с продажи"

    # пакетная проверка по журналу расчётов
    python .kilo/skills/editor/utils/calc_verify.py --doc develop/x/x.md \
        --checks develop/x/x-calcs.json [--asof 2026-11-10] [--tol 0.005]

Формат --checks (JSON-массив):
    [{"label": "НДФЛ", "expr": "(8_000_000-5_000_000)*0.13", "expected": 390000,
      "tol": 0.005, "note": "вычет 1 млн не применён"}]

Разрешено в выражениях: + - * / // % ** round abs min max sum, date('YYYY-MM-DD'),
today/asof, days_between(a,b) months_between(a,b) years_between(a,b)
add_days(d,n) add_months(d,n), sqrt floor ceil, число с % как доля (13% -> 0.13).
Ломать песочницу нельзя: доступ к именам, атрибутам и импортам закрыт.

Код выхода: 0 — всё сходится, 1 — есть расхождения, 2 — есть неверные выражения
или расхождение больше 1%.
"""
from __future__ import annotations

import argparse
import ast
import json
import math
import os
import re
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _docparse as dp  # noqa: E402


class CalcError(Exception):
    pass


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    mo = m % 12 + 1
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1])
    return date(y, mo, day)


def _coerce_date(v):
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        return datetime.strptime(v, "%Y-%m-%d").date()
    raise CalcError(f"ожидалась дата, получено {v!r}")


FUNCS = {
    "round": round, "abs": abs, "min": min, "max": max, "sum": sum, "len": len,
    "sqrt": math.sqrt, "floor": math.floor, "ceil": math.ceil,
    "date": lambda s: _coerce_date(s),
    "days_between": lambda a, b: dp.days_between(_coerce_date(a), _coerce_date(b)),
    "months_between": lambda a, b: dp.months_between(_coerce_date(a), _coerce_date(b)),
    "years_between": lambda a, b: dp.years_between(_coerce_date(a), _coerce_date(b)),
    "add_days": lambda d, n: _coerce_date(d) + timedelta(days=int(n)),
    "add_months": lambda d, n: _add_months(_coerce_date(d), int(n)),
}


def prepare_expr(expr: str) -> str:
    """Нормализация записи: русские разделители, %, десятичная запятая."""
    s = expr.replace("\u00a0", " ").replace("\u2009", " ").replace("\u202f", " ")
    s = re.sub(r"(?<=\d)[ ](?=\d{3}(?:\D|$))", "", s)          # группировка разрядов
    s = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", s)             # 1,500 -> 1500
    s = re.sub(r"(?<=\d),(?=\d+$|\d{1,2}(?:\D|$))", ".", s)     # 13,7 -> 13.7
    s = re.sub(r"(\d(?:\.\d+)?)\s*%", r"(\1/100)", s)           # 13% -> 0.13
    s = re.sub(r"[₽]|руб\w*", "", s, flags=re.I)
    return s.strip()


def safe_eval(expr: str, asof: date):
    src = prepare_expr(expr)
    if not src:
        raise CalcError("пустое выражение")
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as exc:
        raise CalcError(f"не разбирается выражение «{expr}»: {exc.msg}") from exc
    allowed = {"today", "asof", "pi"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS:
                raise CalcError("разрешены только вызовы функций из списка документирования")
            allowed.add(node.func.id)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id not in allowed:
                raise CalcError(f"неизвестное имя «{node.id}»: в выражениях разрешены только "
                                "числа, даты и функции из списка")
        elif isinstance(node, (ast.Attribute, ast.Subscript, ast.Starred, ast.Lambda,
                               ast.Dict, ast.Set, ast.comprehension, ast.NamedExpr)):
            raise CalcError(f"конструкция {type(node).__name__} в выражениях запрещена")
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float, str)):
                raise CalcError("допустимы числа и строки-даты в формате YYYY-MM-DD")
    env = {"today": asof, "asof": asof, "pi": math.pi}
    code = compile(ast.Expression(body=tree.body), "<calc>", "eval")
    try:
        value = eval(code, {"__builtins__": {}}, dict(env, **FUNCS))  # noqa: S307 — песочница выше
    except Exception as exc:
        raise CalcError(f"выражение «{expr}» упало: {type(exc).__name__}: {exc}") from exc
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return float(value)
    raise CalcError(f"не числовой результат: {value!r}")


def compare(got, expected, tol):
    if isinstance(expected, str):
        return str(got) == expected, ""
    exp = float(expected)
    denom = max(abs(exp), 1e-9)
    diff = abs(got - exp)
    rel = diff / denom if exp else diff
    return rel <= tol or diff <= 1e-9, rel


def significant_numbers(doc_text: str):
    """Числа документа, требующие проверки: >=1000, проценты, дробные, с валютой."""
    prose = dp.mask_dates(dp.mask_nonprose(doc_text)[0])
    out = []
    for n in dp.extract_numbers(prose):
        if n.is_year:
            continue
        if n.value >= 1000 or n.is_pct or n.unit or re.search(r"\d[.,]\d", n.raw):
            out.append(n)
    return out


def main():
    ap = argparse.ArgumentParser(description="Верификация расчётов документа")
    ap.add_argument("--doc", help="файл документа для отчёта покрытия чисел")
    ap.add_argument("--checks", help="JSON-журнал расчётов")
    ap.add_argument("--expr", help="одиночное выражение")
    ap.add_argument("--expect", help="ожидаемое значение одиночного выражения")
    ap.add_argument("--label", default="расчёт")
    ap.add_argument("--tol", type=float, default=0.005)
    ap.add_argument("--asof", default=None)
    ap.add_argument("--coverage", type=int, default=40, help="сколько неверифицированных чисел показывать")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    asof = datetime.strptime(args.asof, "%Y-%m-%d").date() if args.asof else date.today()
    rows, errors = [], []

    if args.expr:
        try:
            got = safe_eval(args.expr, asof)
        except CalcError as exc:
            errors.append(str(exc))
            got = None
        if got is not None:
            ok, rel = (True, 0.0) if args.expect is None else compare(got, args.expect, args.tol)
            rows.append({"label": args.label, "expr": args.expr, "expected": args.expect,
                         "got": got, "ok": ok, "rel": rel, "note": ""})

    if args.checks:
        with open(args.checks, "r", encoding="utf-8") as fh:
            checks = json.load(fh)
        for c in checks:
            label = c.get("label") or c.get("expr")
            try:
                got = safe_eval(c["expr"], asof)
            except CalcError as exc:
                errors.append(f"{label}: {exc}")
                continue
            if "expected" not in c:
                rows.append({"label": label, "expr": c["expr"], "expected": None, "got": got,
                             "ok": True, "rel": 0.0, "note": "нет expected — только пересчёт"})
                continue
            ok, rel = compare(got, c["expected"], float(c.get("tol", args.tol)))
            rows.append({"label": label, "expr": c["expr"], "expected": c["expected"], "got": got,
                         "ok": ok, "rel": rel, "note": c.get("note", "")})

    uncovered = []
    if args.doc:
        with open(args.doc, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read().replace("\r\n", "\n")
        starts = dp.line_starts(text)
        expected_vals = [r["got"] for r in rows if isinstance(r["got"], float)]
        expected_vals += [float(c["expected"]) for c in (json.load(open(args.checks, encoding="utf-8"))
                        if args.checks else []) if isinstance(c.get("expected"), (int, float))]
        for n in significant_numbers(text):
            hit = any(abs(n.value - e) <= max(abs(e) * args.tol, 1e-9) for e in expected_vals)
            if not hit:
                uncovered.append({"value": n.value, "raw": n.raw, "pct": n.is_pct,
                                  "line": dp.line_of(n.start, starts)})

    fails = [r for r in rows if not r["ok"]]
    if args.json:
        print(json.dumps({"asof": str(asof), "rows": rows, "errors": errors,
                          "uncovered": uncovered}, ensure_ascii=False, indent=1))
    else:
        print(f"=== CALC VERIFY (срез {asof}) ===")
        if rows:
            print("\n--- РАСЧЁТЫ ---")
            for r in rows:
                mark = "PASS" if r["ok"] else "FAIL"
                exp = dp.fmt(float(r["expected"])) if isinstance(r["expected"], (int, float)) else "—"
                print(f"[{mark}] {r['label']}: {r['expr']} = {dp.fmt(r['got'])} (ожидалось {exp})"
                      + (f" | откл. {r['rel']:.2%}" if not r["ok"] else "")
                      + (f" | {r['note']}" if r["note"] else ""))
        if errors:
            print("\n--- ОШИБКИ ВЫРАЖЕНИЙ (BLOCKER) ---")
            for e in errors:
                print(f"  {e}")
        if args.doc:
            print(f"\n--- ПОКРЫТИЕ ЧИСЕЛ ДОКУМЕНТА ({len(uncovered)} без проверки) ---")
            if not uncovered:
                print("  все заметные числа совпадают с пересчитанными значениями")
            for u in uncovered[:args.coverage]:
                print(f"  строка {u['line']}: {u['raw']} -> {dp.fmt(u['value'])}"
                      + ("%" if u["pct"] else "")
                      + " не верифицирован (нет формулы в журнале)")
            if len(uncovered) > args.coverage:
                print(f"  ... ещё {len(uncovered) - args.coverage}")
        print(f"\nСВОДКА: проверено={len(rows)} расхождений={len(fails)} "
              f"ошибок выражений={len(errors)} неверифицированных чисел={len(uncovered)}")
        print("Не проверяется: правильность выбора формулы и исходных данных — только арифметика.")
    if errors:
        return 2
    if fails:
        return 2 if any(r["rel"] > 0.01 for r in fails) else 1
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
