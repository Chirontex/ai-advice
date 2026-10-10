# -*- coding: utf-8 -*-
"""Проверка переполнения слайдов: каждый .slide влезает в экран без прокрутки
по вертикали, контент не вылезает по горизонтали.

Использование:
    python verify_layout.py <path-to-html> [width] [height]
По умолчанию тестирует 390x844 (iPhone) и 375x667 (iPhone SE).
Выходной код 0 — все слайды в порядке, 1 — есть нарушения.
"""
import os, sys, json
from playwright.sync_api import sync_playwright

def check(html, w, h):
    JS = """() => {
      document.querySelectorAll('.slide').forEach(s => s.classList.remove('active'));
      const out = [];
      const slides = document.querySelectorAll('.slide');
      slides.forEach((s, i) => {
        slides.forEach(x => x.classList.remove('active'));
        s.classList.add('active');
        const sr = s.getBoundingClientRect();
        const body = s.querySelector('.body') || s;
        const bh = body.getBoundingClientRect().height;
        const bs = body.scrollHeight;
        let maxRight = sr.left, minLeft = sr.right;
        const scan = (el) => { [...el.children].forEach(c => {
          // декоративные absolute-элементы (aria-hidden, напр. розетки/виньетки)
          // могут выходить за край слайда намеренно — не считаем переполнением
          if (c.getAttribute && c.getAttribute('aria-hidden') === 'true') return;
          const cr = c.getBoundingClientRect();
          if (cr.width > 0) { maxRight = Math.max(maxRight, cr.right); minLeft = Math.min(minLeft, cr.left);
            if (c.children.length) scan(c); }
        }); };
        scan(s);
        out.push({ id: s.id, slideH: Math.round(sr.height), bodyScroll: Math.round(bs),
          overflowY: bs > bh + 1, overflowX: maxRight > sr.right + 1 });
      });
      slides.forEach(x => x.classList.remove('active'));
      return out;
    }"""
    pg = browser.new_page(viewport={"width": w, "height": h})
    pg.goto("file:///" + html.replace("\\", "/"))
    pg.wait_for_timeout(500)
    return pg.evaluate(JS)

if len(sys.argv) < 2:
    print("usage: python verify_layout.py <path-to-html> [w] [h]")
    sys.exit(2)

html = os.path.abspath(sys.argv[1])
sizes = [(390, 844), (375, 667)]
if len(sys.argv) >= 4:
    sizes = [(int(sys.argv[2]), int(sys.argv[3]))]

fail = False
with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge")
    for (w, h) in sizes:
        print(f"--- {w}x{h} ---")
        for d in check(html, w, h):
            bad = d["overflowY"] or d["overflowX"]
            fail = fail or bad
            flag = "FAIL" if bad else "ok  "
            print(f"  [{flag}] {d['id']}: scrollY={d['bodyScroll']} overflowX={d['overflowX']}")
    browser.close()

print("\nИТОГ:", "FAIL — есть переполнение" if fail else "OK — все слайды влезают")
sys.exit(1 if fail else 0)