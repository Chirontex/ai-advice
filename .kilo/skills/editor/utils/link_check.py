#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""link_check.py — проверка ссылок документа: живость, назначение, форма.

Запуск:
    python .kilo/skills/editor/utils/link_check.py develop/<slug>/<slug>.md
    python .../link_check.py <doc> --max-links 60 --timeout 20

Проверяет:
  DEAD      ссылка не открывается / 4xx / 410 — BLOCKER
  UNVERIFIED 403/429/5xx — антибот или сбой: не доказательство смерти,
            но и не подтверждение — MINOR, проверяется вручную
  REDIRECT  диплинк съехал на главную или другой домен — MAJOR/INFO
  SCHEME    http вместо https, localhost, IP, локальный файл — MAJOR
  TEXT      текст ссылки «сюда»/пустой — MAJOR
  PRODUCT   маркетплейс без артикула или ссылка на поиск вместо карточки
  CONTEXT   абзац про цену/модель/артикул без какой-либо ссылки
  TITLE     заголовок страницы, куда ведёт ссылка (для сверки с утверждением)

Код выхода: 0 — замечаний нет, 1 — есть MAJOR, 2 — есть BLOCKER.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import sys

sys.path.insert(0, __file__.replace("\\", "/").rsplit("/", 1)[0])
try:
    import requests
except ImportError:
    requests = None
import _docparse as dp  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
BLOCKER, MAJOR, MINOR = "BLOCKER", "MAJOR", "MINOR"

MD_LINK = re.compile(r"(?<!\!)\[(?P<text>[^\]\n]{0,120})\]\((?P<url>[^)\s]+)"
                     r"(?:\s+\"[^\"]*\")?\)")
AUTOLINK = re.compile(r"<(?P<url>https?://[^\s>]+)>")
BARE = re.compile(r"(?<![\(\[<\"'])\b(?P<url>https?://[^\s<>)\]\"']+)")
TITLE = re.compile(r"<title[^>]*>(.{0,300}?)</title>", re.I | re.S)
JUNK_TEXT = re.compile(r"^(?:сюда|по (?:этой |эту |данн\w+ )?ссылк[еау]|эт[ой|у] "
                       r"(?:ссылк[еау]|страниц[еа]|ресурсу)|данн\w+ (?:ссылк[еау]|страниц[еа]|"
                       r"ресурсу|сайт)|тут|здесь|источник|сайт|ссылка|ссылочка|more|link|"
                       r"here|details|нажмите|кликните|подробнее|перейти|официальный сайт|"
                       r"read more|view|click)\W*$", re.I)
PRICE_CTX = re.compile(r"\b(?:цена|цен[аы]|стоимост[ьи]|артикул|sku|модель|тариф|вклад|курс|"
                       r"скидк|бюджет|смета|оф[еэ]рт|процентная ставк|акци[ияя])\w*", re.I)
# Известные маркетплейсы и крупные каталоги: проверка, что ссылка ведёт на карточку,
# а не на поиск/каталог. Список расширяется по мере надобности.
MARKETPLACES = ("ozon.ru", "wildberries.ru", "wb.ru", "yamarket.ru", "market.yandex.ru",
                "aliexpress.", "amazon.", "ebay.", "detmir.ru", "sportmaster.ru", "mvideo.ru",
                "citilink.ru", "rbt.ru", "dns-shop.ru", "mediamarkt.ru", "holodilnik.ru",
                "iz.ru", "sapb.ru", "book24.ru", "apteka.ru", "eapteka.ru", "magnit.ru",
                "perekrestok.ru", "vkusvill.ru", "samokat.ru", "uzd.ru", "utro.ru",
                "zoloto.ru", "sunlight.net", "lefranc.ru", "thecity.ru", "lime.ru",
                "12storeez.ru", "rendezvous.ru", "rivrech.ru", "kari.ru", "republic.ru")
SEARCH_PATH = re.compile(r"/(?:search|catalog|find|qs)/?\?|/catalog/|text=|query=", re.I)


def norm_url(u: str) -> str:
    u = u.strip().strip("<>")
    while u and u[-1] in ".,;:!?»\"')":
        u = u[:-1]
    return u


def collect(text: str):
    """Уникальные ссылки: [{'url','text','line','kind'}] в порядке появления."""
    lines = text.split("\n")
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)

    def line_of(pos):
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    fence = set()
    in_code = False
    ch_mark, width = None, 0
    for i, ln in enumerate(lines, 1):
        m = re.match(r"^\s*(`{3,}|~{3,})", ln)
        if not in_code and m:
            in_code, ch_mark, width = True, m.group(1)[0], len(m.group(1))
            fence.add(i)
        elif in_code and m and m.group(1)[0] == ch_mark and len(m.group(1)) >= width:
            in_code = False
            fence.add(i)
        elif in_code:
            fence.add(i)

    out = []
    seen = set()
    # ссылки внутри кода и цитируемых примеров не проверяются: это не читательские ссылки
    inline = dp.merge_spans([(m.start(), m.end()) for m in
                             re.finditer(r"(?<!`)`[^`\n]+`(?!`)", text)])
    quotes = dp.quote_spans(text)

    def skip(pos):
        return (any(a <= pos < b for a, b in inline)
                or any(a <= pos < b for a, b in quotes)
                or line_of(pos) in fence)

    for m in MD_LINK.finditer(text):
        if skip(m.start()):
            continue
        url = norm_url(m.group("url"))
        out.append({"url": url, "text": m.group("text").strip(), "line": line_of(m.start()),
                    "kind": "md"})
    for rx, kind in ((AUTOLINK, "auto"), (BARE, "bare")):
        for m in rx.finditer(text):
            if skip(m.start()):
                continue
            url = norm_url(m.group("url"))
            if any(o["url"] == url for o in out):
                continue
            out.append({"url": url, "text": "", "line": ln, "kind": kind})
    dedup = {}
    for o in out:
        key = o["url"]
        if key not in dedup:
            dedup[key] = dict(o, lines=[o["line"]])
        else:
            dedup[key]["lines"].append(o["line"])
            if not dedup[key]["text"] and o["text"]:
                dedup[key]["text"] = o["text"]
    return list(dedup.values()), line_of, fence


def classify(url: str):
    if url.startswith("#"):
        return "anchor"
    if url.startswith("mailto:"):
        return "mailto"
    if url.startswith("tel:"):
        return "tel"
    if re.match(r"^https?://", url, re.I):
        return "http"
    return "local"


def fetch(url: str, timeout: float):
    """(status, final_url, title, note)."""
    if requests is None:
        return None, url, "", "requests не установлен — проверка сети пропущена"
    notes = []
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA, "Accept-Language": "ru,en;q=0.8",
                         "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    def attempt(method, verify):
        r = sess.request(method, url, timeout=timeout, allow_redirects=True, verify=verify,
                         stream=True)
        body = b""
        for chunk in r.iter_content(chunk_size=8192):
            body += chunk
            if len(body) > 200_000:
                break
        r.close()
        title = ""
        ctype = r.headers.get("content-type", "")
        if "html" in ctype and body:
            html = None
            cm = re.search(r"charset=([\w.-]+)", ctype, re.I)
            declared = cm.group(1).strip("\"'") if cm else None
            for enc in filter(None, [declared, r.encoding, "utf-8", "cp1251", "windows-1251"]):
                try:
                    html = body.decode(enc)
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            if html is None:
                html = body.decode("utf-8", errors="replace")
            tm = TITLE.search(html)
            if tm:
                raw_title = re.sub(r"<[^>]+>", "", tm.group(1))
                raw_title = re.sub(r"&[a-z#0-9]+;", " ", raw_title, flags=re.I)
                title = re.sub(r"\s+", " ", raw_title).strip()[:160]
        return r.status_code, str(r.url), title

    for method in ("HEAD", "GET"):
        try:
            status, final, title = attempt(method, True)
            if status in (403, 405, 429, 500, 501, 502, 503) and method == "HEAD":
                continue  # многие сайты не любят HEAD — пробуем GET
            return status, final, title, "; ".join(notes)
        except requests.exceptions.SSLError as exc:
            try:
                status, final, title = attempt(method, False)
                notes.append("CA не подтверждён (локальный MITM/прокси): сверь сертификат")
                return status, final, title, "; ".join(notes)
            except Exception as exc2:
                return None, url, "", f"TLS-ошибка: {type(exc).__name__}: {exc2}"
        except requests.exceptions.Timeout:
            return None, url, "", "таймаут"
        except requests.exceptions.ConnectionError as exc:
            return None, url, "", f"нет соединения: {type(exc).__name__}"
        except Exception as exc:
            notes.append(f"{type(exc).__name__}: {exc}")
    return None, url, "", "; ".join(notes) or "не удалось получить ответ"


def main():
    ap = argparse.ArgumentParser(description="Проверка ссылок документа")
    ap.add_argument("path")
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--max-links", type=int, default=60)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--skip-network", action="store_true",
                    help="только форма ссылок и контекст, без HTTP")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    with open(args.path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read().replace("\r\n", "\n")
    links, _, _ = collect(text)
    findings = []

    def add(sev, code, line, msg, ev=""):
        findings.append({"sev": sev, "code": code, "line": line, "msg": msg,
                         "evidence": (ev or "")[:160]})

    http_links = [l for l in links if classify(l["url"]) == "http"]
    for l in links:
        kind = classify(l["url"])
        line = l["lines"][0]
        if kind == "local":
            add(MAJOR, "SCHEME", line, f"ссылка на локальный ресурс «{l['url']}» — читатель не "
                "получит его: вставь содержимое или дай публичный URL", l["text"])
            continue
        if kind == "mailto" and not re.match(r"^mailto:[\w.+-]+@[\w.-]+\.\w{2,}$", l["url"], re.I):
            add(MAJOR, "SCHEME", line, f"некорректный mailto: {l['url']}")
        if kind == "http":
            if l["url"].startswith("http://"):
                add(MINOR, "SCHEME", line, "http вместо https", l["url"])
            host = re.sub(r"^https?://", "", l["url"]).split("/")[0].split(":")[0].lower()
            if host in ("localhost", "127.0.0.1", "0.0.0.0") or re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
                add(MAJOR, "SCHEME", line, f"адрес внутренней машины: {host}", l["text"])
            if any(m in host for m in MARKETPLACES):
                if SEARCH_PATH.search(l["url"]):
                    add(MAJOR, "PRODUCT", line, "ссылка ведёт на поиск/каталог, а не на карточку "
                        "товара — читатель не найдёт нужный вариант", l["url"])
                elif not re.search(r"\d{5,}", l["url"]):
                    add(MAJOR, "PRODUCT", line, "маркетплейс без артикула в URL — это не карточка "
                        "товара", l["url"])
        if l["text"] and JUNK_TEXT.match(l["text"]):
            add(MAJOR, "TEXT", line, "текст ссылки ничего не сообщает — напиши, куда ведёт",
                f"[{l['text']}]({l['url'][:60]})")
        if not l["text"] and l["kind"] == "md":
            add(MAJOR, "TEXT", line, "пустой текст ссылки", l["url"][:80])

    # контекст: абзацы про цену/модель/артикул без ссылки
    paras = [(m.start(), m.group(0)) for m in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", text)]
    starts = [0]
    for i, chx in enumerate(text):
        if chx == "\n":
            starts.append(i + 1)

    def line_of(pos):
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    for pos, block in paras:
        if PRICE_CTX.search(block) and "http" not in block and "@" not in block:
            if dp_words(block) >= 4 and len(block.split("\n")) <= 4:
                add(MINOR, "CONTEXT", line_of(pos),
                    "абзац про цену/модель/артикул/ставку без ссылки на источник или карточку",
                    block[:90].replace("\n", " "))

    results = []
    if not args.skip_network and http_links:
        todo = http_links[:args.max_links]
        if len(http_links) > args.max_links:
            add(MINOR, "DEAD", 0, f"проверено только {args.max_links} из {len(http_links)} ссылок "
                "— остальные вручную или повтори с --max-links")
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(fetch, l["url"], args.timeout): l for l in todo}
            for fut in cf.as_completed(futs):
                l = futs[fut]
                status, final, title, note = fut.result()
                results.append({"url": l["url"], "line": l["lines"][0], "status": status,
                                "final": final, "title": title, "note": note})
                line = l["lines"][0]
                if status is None:
                    add(BLOCKER, "DEAD", line, f"ссылка не открывается: {note}", l["url"])
                elif status in (404, 410, 400, 422, 451):
                    add(BLOCKER, "DEAD", line, f"страница отвечает {status}: ссылка мертва",
                        l["url"])
                elif status in (403, 401, 429, 500, 502, 503):
                    add(MINOR, "UNVERIFIED", line,
                        f"ответ {status} — вероятно антибот/вход по авторизации, живость НЕ "
                        "подтверждена: открой вручную или замени источник", l["url"])
                elif status in (301, 302, 307, 308):
                    add(MAJOR, "REDIRECT", line, f"не разобранный редирект {status}", l["url"])
                if status and 200 <= status < 300:
                    orig_path = re.sub(r"^https?://[^/]+", "", l["url"]).rstrip("/")
                    final_path = re.sub(r"^https?://[^/]+", "", final).rstrip("/")
                    if orig_path and not final_path:
                        add(MAJOR, "REDIRECT", line,
                            "глубокая ссылка редиректит на главную — страница переехала или "
                            "умерла", f"{l['url']} → {final}")
                    elif orig_path and final_path and final_path != orig_path:
                        add(MINOR, "REDIRECT", line, "адрес изменился — обнови ссылку на итоговый",
                            f"{l['url']} → {final}")
                    if title:
                        add("INFO", "TITLE", line, "заголовок страницы (сверь с утверждением)",
                            f"{l['url'][:70]} → {title}")
    elif not args.skip_network:
        add(MINOR, "DEAD", 0, "в документе нет http-ссылок: проверь, нужны ли они по содержанию")

    order = {BLOCKER: 0, MAJOR: 1, MINOR: 2, "INFO": 3}
    findings.sort(key=lambda f: (order[f["sev"]], f["code"], f["line"]))
    counts = {k: sum(1 for f in findings if f["sev"] == k) for k in order}

    if args.json:
        print(json.dumps({"file": args.path, "counts": counts, "links": results,
                          "findings": findings}, ensure_ascii=False, indent=1))
    else:
        print(f"=== LINK CHECK: {args.path} (ссылок: {len(links)}, http: {len(http_links)}) ===")
        if results:
            print("\n--- ОТВЕТЫ СЕРВЕРОВ ---")
            for r in sorted(results, key=lambda x: x["line"]):
                t = f" | {r['title'][:70]}" if r["title"] else ""
                n = f" | {r['note']}" if r["note"] else ""
                print(f"{r['line']:>4}: {r['status'] if r['status'] is not None else 'ERR'} "
                      f"{r['url'][:78]}{t}{n}")
        print("\n--- НАХОДКИ ---")
        if not findings:
            print("нет")
        cur = None
        for f in findings:
            if f["sev"] != cur:
                cur = f["sev"]
                print(f"\n[{cur} ({counts[cur]})]")
            print(f"  [{f['code']}:{f['line'] or '-'}] {f['msg']}")
            if f["evidence"]:
                print(f"      ↳ {f['evidence']}")
        print(f"\nСВОДКА: BLOCKER={counts[BLOCKER]} MAJOR={counts[MAJOR]} MINOR={counts[MINOR]} "
              f"INFO={counts['INFO']}")
        print("Не проверяется: уместность и достаточность ссылок по смыслу — это редактор и "
              "холодный читатель.")
    return 2 if counts[BLOCKER] else (1 if counts[MAJOR] else 0)


def dp_words(block: str) -> int:
    return len(re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", block))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
