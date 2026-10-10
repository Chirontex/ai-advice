# -*- coding: utf-8 -*-
"""Проверка точек прогресса: активная точка в таб-баре совпадает с активным слайдом
при переключении через window.go(i). Слайды должны экспортировать window.go
(см. SKILL.md — принцип «рендер через window.go»).

Использование:
    python verify_dots.py <path-to-html> [width] [height]
Выходной код 0 — точки следуют за слайдами, 1 — расхождение (или нет window.go).
"""
import os, sys, json
from playwright.sync_api import sync_playwright

JS_STATE = """() => {
  const slide = [...document.querySelectorAll('.slide')].findIndex(s => s.classList.contains('active'));
  const dots = [...document.querySelectorAll('.bar .dot, .dots .dot, .dot-row .dot')];
  const dot = dots.findIndex(d => d.classList.contains('on'));
  return { activeSlide: slide, activeDot: dot };
}"""

def probe(browser, html, w, h):
    pg = browser.new_page(viewport={"width": w, "height": h})
    pg.goto("file:///" + html.replace("\\", "/"))
    pg.wait_for_timeout(500)
    n = pg.evaluate("document.querySelectorAll('.slide').length")
    return pg, n

if len(sys.argv) < 2:
    print("usage: python verify_dots.py <path-to-html> [w] [h]")
    sys.exit(2)

html = os.path.abspath(sys.argv[1])
w, h = (390, 844)
if len(sys.argv) >= 4:
    w, h = int(sys.argv[2]), int(sys.argv[3])

fail = False
with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge")
    pg, n = probe(browser, html, w, h)
    if not n:
        print("FAIL: нет слайдов .slide")
        sys.exit(1)
    has_go = pg.evaluate("typeof window.go === 'function'")
    if not has_go:
        print("FAIL: window.go не экспортирован — точки не смогут обновиться при внешнем переключении")
        fail = True
    for i in range(n):
        if has_go:
            pg.evaluate("i => window.go(i)", i)
            pg.wait_for_timeout(60)
        st = pg.evaluate(JS_STATE)
        ok = st["activeSlide"] == i and st["activeDot"] == i
        fail = fail or not ok
        print(f"  [{'ok  ' if ok else 'FAIL'}] слайд {i}: слайд={st['activeSlide']} точка={st['activeDot']}")
    browser.close()

print("\nИТОГ:", "FAIL — точки не следуют за слайдами" if fail else "OK — точки следуют за слайдами")
sys.exit(1 if fail else 0)