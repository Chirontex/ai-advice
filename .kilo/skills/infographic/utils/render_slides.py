# -*- coding: utf-8 -*-
"""Рендер слайдов HTML-инфографики в PNG через Playwright (локальный Edge, 2x).

Использование:
    python render_slides.py <path-to-html> <out-dir> [width] [height] [deviceScaleFactor]
По умолчанию: 390x844, масштаб 2 (iPhone). Переключение слайдов — через
window.go(i) (обязателен, иначе точки прогресса в PNG останутся на первом слайде).
"""
import os, sys
from playwright.sync_api import sync_playwright

if len(sys.argv) < 3:
    print("usage: python render_slides.py <path-to-html> <out-dir> [w] [h] [dpr]")
    sys.exit(2)

html = os.path.abspath(sys.argv[1])
outdir = os.path.abspath(sys.argv[2])
w, h, dpr = (390, 844, 2)
if len(sys.argv) >= 5:
    w, h = int(sys.argv[3]), int(sys.argv[4])
if len(sys.argv) >= 6:
    dpr = float(sys.argv[5])
os.makedirs(outdir, exist_ok=True)

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=dpr)
    pg.goto("file:///" + html.replace("\\", "/"))
    pg.wait_for_timeout(700)
    n = pg.evaluate("document.querySelectorAll('.slide').length")
    for i in range(n):
        pg.evaluate("i => window.go(i)", i)      # штатное переключение → точки тоже
        pg.wait_for_timeout(150)
        sid = pg.evaluate("i => document.querySelectorAll('.slide')[i].id", i)
        out = os.path.join(outdir, f"slide-{i+1}-{sid}.png")
        pg.screenshot(path=out)
        print("OK", os.path.basename(out))
    b.close()
print("DONE")