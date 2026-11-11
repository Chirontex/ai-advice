#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""spell_ru.py — орфография, пунктуация и грамматика ru-RU через LanguageTool.

Единственная проверка скилла, уходящая во ВНЕШНИЙ сервис. Приватные правила —
в SKILL.md, раздел «Приватность»: документы с персональными данными отправляются
только с явного согласия пользователя, иначе — --pii (маскирование ПИИ) или
отказ от проверки в пользу локальных паттернов doc_lint.

Запуск:
    python .kilo/skills/editor/utils/spell_ru.py develop/<slug>/<slug>.md
    python .../spell_ru.py <doc> --pii                 # замаскировать ФИО/адреса/номера
    python .../spell_ru.py <doc> --endpoint http://localhost:8081/v2/check
    python .../spell_ru.py <doc> --allow-send          # согласен отправить ПИИ как есть

Маппинг категорий LanguageTool в severity скилла:
  TYPOS, GRAMMAR, PUNCTUATION, CONFUSED_WORDS, HOMOPHONES, DUPLICATED_TEXT -> MAJOR
  TYPOGRAPHY, STYLE, REPEAT, CASING, COLLATING, ACCESSIBILITY, WORD_CHOICE  -> MINOR

Код выхода: 0 — чисто, 1 — есть MAJOR, 2 — сервис недоступен/отказ по приватности.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _docparse as dp  # noqa: E402

try:
    import requests
except ImportError:
    requests = None

ENDPOINT_DEFAULT = "https://api.languagetool.org/v2/check"
MAJOR_CATS = {"TYPOS", "GRAMMAR", "PUNCTUATION", "CONFUSED_WORDS", "HOMOPHONES",
              "DUPLICATED_TEXT", "MISSING_WORD", "WRONG_WORD_CHOICE", "LANGUAGE_CHANGE",
              "LOGIC", "SEMANTICS", "CONSISTENCY"}

PII_PATTERNS = [
    re.compile(r"\b[А-ЯЁ][а-яё]{2,}\s+[А-ЯЁ][а-яё]{1,}\s+[А-ЯЁ][а-яё]{1,}\b"),   # ФИО
    re.compile(r"\b\d{2}\s?\d{2}\s?\d{6}\b"),                                     # паспорт
    re.compile(r"\b\d{3}-\d{3}-\d{3}\b"),                                         # СНИЛС
    re.compile(r"\b\d{10}\b|\b\d{12}\b"),                                         # ИНН
    re.compile(r"\b(?:ул\.|улица|просп\.|проспект|пер\.|ш\.|б-р|наб\.)\s+[А-ЯЁ][\w.-]{1,30}", re.I),
    re.compile(r"\b(?:дом|д\.|влад[еение]|кв\.|квартира|офис|оф\.|помещени[ее])\s*№?\s*\d+", re.I),
    re.compile(r"\b(?:зарегистрирован|прож[ии]ва[ею]т|фактически жив[ёт]|адрес регистрации)"
               r"[^.]{0,60}", re.I),
]
ALWAYS_MASK = [
    dp._URL, dp._EMAIL, dp._WIN_PATH, dp._REL_PATH, dp._FILE_EXT, dp._HTML_TAG,
    dp._INLINE_CODE, dp._PHONE, dp._ID_NUM,
]
LATIN_ONLY = re.compile(r"\b[A-Za-z][A-Za-z0-9+.#/_-]{2,}\b")
LONG_DIGITS = re.compile(r"\b\d{5,}\b")


def compress_masked(line: str, spans):
    """Схлопывает замаскированные прогоны пробелов в один (шум TYPOGRAPHY не кормить).

    Двойные пробелы автора сохраняются: это реальная находка.
    """
    flags = [False] * len(line)
    for s, e in spans:
        for i in range(s, min(e, len(line))):
            flags[i] = True
    chars, keep = [], []
    for i, ch in enumerate(line):
        if ch == " " and flags[i] and keep and keep[-1] and chars[-1] == " ":
            continue
        chars.append(ch)
        keep.append(flags[i])
    text = "".join(chars)
    intervals, i = [], 0
    while i < len(keep):
        if keep[i]:
            j = i
            while j < len(keep) and keep[j]:
                j += 1
            intervals.append((i, j))
            i = j
        else:
            i += 1
    return text, intervals


def build_payload(text: str, pii: bool):
    """(list[(line_no, transformed, masked_intervals)]) по строкам вне кода."""
    fence = dp.code_fence_lines(text)
    lines = text.split("\n")
    out = []
    for i, ln in enumerate(lines, 1):
        if i in fence or not ln.strip():
            continue
        if re.match(r"^\s*(?:\|[\s:|-]*\|\s*)$", ln) or re.match(r"^\s*```", ln):
            continue
        # отступы продолжения markdown и заголовки не являются дефектами текста:
        # срезаем ведущие пробелы, а заголовок заканчиваем точкой, чтобы LT не
        # склеивал его со следующим предложением
        ln = ln.lstrip()
        hm = re.match(r"^(#{1,6})\s+(.+?)\s*#*$", ln)
        if hm:
            ln = hm.group(2).strip().rstrip(".!?") + "."
        spans = []
        for rx in ALWAYS_MASK:
            for m in rx.finditer(ln):
                spans.append((m.start(), m.end()))
        for m in LATIN_ONLY.finditer(ln):
            spans.append((m.start(), m.end()))
        for m in LONG_DIGITS.finditer(ln):
            spans.append((m.start(), m.end()))
        if pii:
            for rx in PII_PATTERNS:
                for m in rx.finditer(ln):
                    spans.append((m.start(), m.end()))
        spans = dp.merge_spans(spans)
        body, spans_c = compress_masked(dp.mask(ln, spans), spans)
        out.append((i, body, spans_c))
    return out


def detect_pii(text: str):
    hits = []
    for rx in PII_PATTERNS:
        for m in rx.finditer(text):
            hits.append(m.group(0)[:60])
    return hits[:8]


def chunk(items, max_chars):
    chunks, cur, cur_len = [], [], 0
    for it in items:
        add_len = len(it[1]) + 1
        if cur and cur_len + add_len > max_chars:
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(it)
        cur_len += add_len
    if cur:
        chunks.append(cur)
    return chunks


def check(endpoint, payload, timeout, retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(endpoint, data={"text": payload, "language": "ru-RU"},
                              timeout=timeout, headers={"User-Agent": "kilo-editor/1.0"})
            if r.status_code == 200:
                return r.json(), None
            last = f"HTTP {r.status_code}: {r.text[:120]}"
            if r.status_code in (403, 429):
                time.sleep(2.0 * (attempt + 1))
                continue
            if r.status_code >= 500:
                time.sleep(1.0 * (attempt + 1))
                continue
            return None, last
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(1.0 * (attempt + 1))
    return None, last


def main():
    ap = argparse.ArgumentParser(description="Орфография/грамматика ru-RU через LanguageTool")
    ap.add_argument("path")
    ap.add_argument("--endpoint", default=ENDPOINT_DEFAULT)
    ap.add_argument("--max-chars", type=int, default=12000)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--pii", action="store_true", help="замаскировать персональные данные")
    ap.add_argument("--allow-send", action="store_true",
                    help="явно согласен отправить документ с ПИИ как есть")
    ap.add_argument("--limit", type=int, default=60, help="сколько находок печатать")
    ap.add_argument("--ignore", default="", help="список принятых терминов через запятую")
    ap.add_argument("--ignore-file", default=None,
                    help="файл со списком принятых терминов (по одному на строку)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    ignore = {w.strip().lower() for w in args.ignore.split(",") if w.strip()}
    if args.ignore_file:
        try:
            with open(args.ignore_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    w = line.strip().lower()
                    if w and not w.startswith("#"):
                        ignore.add(w)
        except OSError as exc:
            print(f"spell_ru: список терминов не прочитан ({exc})")

    with open(args.path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read().replace("\r\n", "\n")

    pii_hits = detect_pii(text)
    if pii_hits and not (args.pii or args.allow_send):
        print("=== SPELL RU: ОТКАЗ (приватность) ===")
        print(f"В документе обнаружены признаки персональных данных ({len(pii_hits)} мест):")
        for h in pii_hits:
            print(f"  • {h}")
        print("Внешний сервис получит текст. Выбери вариант:")
        print("  --pii        замаскировать ФИО/адреса/номера и отправить остальное")
        print("  --allow-send отправить как есть (сознательное согласие)")
        print("  либо пропусти проверку: орфографию закрой перечитыванием + doc_lint")
        return 2

    if requests is None:
        print("spell_ru: библиотека requests не установлена — проверка пропущена")
        return 2

    items = build_payload(text, args.pii)
    findings = []
    served = 0
    failed_chunks = 0
    for ch in chunk(items, args.max_chars):
        payload = "\n".join(x[1] for x in ch)
        data, err = check(args.endpoint, payload, args.timeout)
        if data is None:
            failed_chunks += 1
            findings.append({"sev": "MAJOR", "code": "UNVERIFIED", "line": ch[0][0],
                             "msg": f"LanguageTool не ответил для строк {ch[0][0]}–{ch[-1][0]}: "
                                    f"{err}", "evidence": "", "cat": "SERVICE"})
            continue
        served += 1
        # карта глобального смещения -> (номер строки, локальное смещение)
        offset = 0
        marks = []
        for line_no, transformed, spans in ch:
            marks.append((offset, offset + len(transformed), line_no, spans))
            offset += len(transformed) + 1
        for m in data.get("matches", []):
            go, gl = m.get("offset", 0), m.get("length", 1)
            host = None
            for a, b, line_no, spans in marks:
                if a <= go < b or a <= go + gl <= b:
                    local = go - a
                    # подавляем артефакты маскирования: пересечение с замаскированным участком
                    # или касание его краем (пробелы, скобки, пунктуация рядом)
                    if any(local < e + 1 and s - 1 < local + gl for s, e in spans):
                        host = None
                        break
                    host = (line_no, local, spans)
                    break
            if host is None:
                continue
            line_no, local, _ = host
            cat = (m.get("rule", {}).get("category", {}) or {}).get("id", "?")
            rule_id = m.get("rule", {}).get("id", "")
            msg = (m.get("message", "") or "").strip()
            sev = "MAJOR" if cat in MAJOR_CATS else "MINOR"
            # удвоение слова и потеря отрицания — всегда содержательная ошибка
            if cat not in MAJOR_CATS and (re.search(r"повтор слова|удвоен", msg, re.I)
                                          or "DOUBLED" in rule_id or "DOUBLE" in rule_id):
                sev = "MAJOR"
            ctx = (m.get("context", {}) or {})
            snippet = ctx.get("text", "")
            c_off, c_len = ctx.get("offset", 0), ctx.get("length", 0)
            token = snippet[c_off:c_off + c_len].strip().lower()
            if token and (token in ignore or any(w in token for w in ignore if len(w) >= 4)):
                continue  # принятый термин служебного словаря
            reps = [x.get("value") for x in m.get("replacements", [])][:3]
            findings.append({
                "sev": sev, "code": "SPELL", "line": line_no, "cat": cat,
                "msg": msg,
                "evidence": snippet.strip()[:150],
                "suggest": reps,
                "rule": m.get("rule", {}).get("id", ""),
            })
        time.sleep(0.7)

    order = {"MAJOR": 0, "MINOR": 1}
    findings.sort(key=lambda f: (order.get(f["sev"], 2), f["line"]))
    counts = {k: sum(1 for f in findings if f["sev"] == k) for k in ("MAJOR", "MINOR")}

    if args.json:
        print(json.dumps({"file": args.path, "endpoint": args.endpoint, "pii_masked": args.pii,
                          "chunks_ok": served, "chunks_failed": failed_chunks,
                          "counts": counts, "findings": findings}, ensure_ascii=False, indent=1))
    else:
        print(f"=== SPELL RU: {args.path} ===")
        print(f"сервис: {args.endpoint} | маскирование ПИИ: {'вкл' if args.pii else 'нет'} | "
              f"чанков успешно: {served}, сбой: {failed_chunks}")
        cur = None
        for f in findings[:args.limit]:
            if f["sev"] != cur:
                cur = f["sev"]
                print(f"\n--- {cur} ({counts[cur]}) ---")
            sug = f" → {f['suggest']}" if f.get("suggest") else ""
            print(f"[{f.get('cat', '?')}:{f['line']}] {f['msg']}{sug}")
            if f.get("evidence"):
                print(f"    ↳ {f['evidence']}")
        if len(findings) > args.limit:
            print(f"... ещё {len(findings) - args.limit} (подними --limit)")
        if not findings:
            print("замечаний нет")
        print(f"\nСВОДКА: MAJOR={counts['MAJOR']} MINOR={counts['MINOR']}")
        print("LanguageTool не ловит: опечатки в собственных именах, числах, терминах из "
              "белого списка, а также смысл и согласованность — это чеклист редактора.")
    return 2 if failed_chunks and not served else (1 if counts["MAJOR"] else 0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
