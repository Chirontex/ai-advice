# -*- coding: utf-8 -*-
"""Проверка вертикального центрирования: контент каждого слайда имеет
РАВНЫЕ отступы сверху и снизу внутри .body (или внутри слайда, если body нет).

Использование:
    python verify_centering.py <path-to-html> [width] [height]
Выходной код 0 — центрирование ок, 1 — смещение (сообщает разницу в px).
"""
import os, sys, json
from playwright.sync_api import sync_playwright

def check(html, w, h):
    JS = """() => {
      const slides = document.querySelectorAll('.slide');
      let curHtml = null;
      // прогоняем по одному активному
      const probe = (i) => {
        slides.forEach(x => x.classList.remove('active'));
        slides[i].classList.add('active');
        const s = slides[i];
        const b = s.querySelector('.body') || s;
        const br = b.getBoundingClientRect();
        const kids = [...b.children].filter(k => k.getBoundingClientRect().height > 0);
        if (!kids.length) return null;
        const top = kids[0].getBoundingClientRect().top - br.top;
        const bottom = br.bottom - kids[kids.length-1].getBoundingClientRect().bottom;
        return { id: s.id, padTop: Math.round(top), padBottom: Math.round(bottom), diff: Math.abs(top-bottom) };
      };
      const out = [];
      for (let i = 0; i < slides.length; i++) { const r = probe(i); if (r) out.push(r); }
      slides.forEach(x => x.classList.remove('active'));
      return out;
    }"""
    pg = browser.new_page(viewport={"width": w, "height": h})
    pg.goto("file:///" + html.replace("\\", "/"))
    pg.wait_for_timeout(500)
    return pg.evaluate(JS)

if len(sys.argv) < 2:
    print("usage: python verify_centering.py <path-to-html> [w] [h]")
    sys.exit(2)

html = os.path.abspath(sys.argv[1])
w, h = (390, 844)
if len(sys.argv) >= 4:
    w, h = int(sys.argv[2]), int(sys.argv[3])

fail = False
with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge")
    print(f"--- {w}x{h} ---")
    for d in check(html, w, h):
        ok = d["diff"] <= 2
        fail = fail or not ok
        print(f"  [{'ok  ' if ok else 'FAIL'}] {d['id']}: сверху={d['padTop']}px снизу={d['padBottom']}px (разница {d['diff']}px)")
    browser.close()

print("\nИТОГ:", "FAIL — контент смещён" if fail else "OK — контент отцентрован")
sys.exit(1 if fail else 0)