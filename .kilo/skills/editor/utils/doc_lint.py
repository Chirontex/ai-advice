#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""doc_lint.py — оффлайн-проверки редакционного чеклиста скилла editor.

Запуск:
    python .kilo/skills/editor/utils/doc_lint.py develop/<slug>/<slug>.md
    python .kilo/skills/editor/utils/doc_lint.py - --max-sentence-words 28

Проверяет локально (без сети):
  STRUCTURE  заголовок H1, уровни, пустые разделы, висячие отсылки,
             оглавление/блок «Суть», отметка актуальности
  MARKUP     парность кавычек/скобок/выделений, незакрытый fence, двойные
             пробелы, пробел перед пунктуацией, дефис вместо тире,
             латинские омоглифы в кириллице, таблицы, нумерация списков
  LEFTOVER   плейсхолдеры, остатки сессии и других версий, ссылки на
             внешние файлы/носители, утечка внутренней кухни
  GLOSSARY   кандидаты в глоссарий (аббревиатуры и жаргон без
             расшифровки), перебор — статьи о терминах, известных
             аудитории (--audience-known), о единичных упоминаниях
             и неиспользуемые статьи
  NUMBERS    несуществующие даты, день недели vs дата, английский формат
             разрядов, числа без разделения, близкие но не равные суммы,
             точка/запятая, валютные обозначения, проценты > 100
  TABLES     расхождение колонок, пустые ячейки, итоги против сумм строк
  WATER      канцелярит, самовторы, дубли абзацев, длинные предложения,
             мета-комментарии, текст ссылки «сюда»

Код выхода: 0 — чисто, 1 — есть MAJOR, 2 — есть BLOCKER.
Находки — сигналы: ложные срабатывания отбрасывает редактор, но каждую
он обязан либо исправить, либо отметить как отброшенную осознанно.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _docparse as dp  # noqa: E402

BLOCKER, MAJOR, MINOR = "BLOCKER", "MAJOR", "MINOR"
_SEV = {BLOCKER: 0, MAJOR: 1, MINOR: 2}

DEFAULT_WHITELIST = ("РФ,ООО,АО,ИП,ЗАО,ОАО,СНТ,ДНТ,ТСЖ,ЖК,ГУП,МУП,ПАО,НКО,УФ,ИФ,"
                     "URL,API,JSON,HTML,HTTP,HTTPS,SQL,CSV,PDF,UTF,IT,TV,PC,CD,DVD,"
                     "CM,GB,MB,KB,TZ,NN,ICQ,SKU,CRM,CMS,SEO,PPP")

# (regex, подсказка) — конструкции, несущие нулевую информацию
STOPLIST = [
    (r"\bосуществл(?:яется|яем|яют|яет|ление|ленные?|яется)\b", "«осуществляется» → нормальный глагол"),
    (r"\bпроизвод(?:ится|ится|им|ят|ит|ство)\b", "«производится» → глагол действия"),
    (r"\bвыполн(?:яется|ение|ен|ена)\b|\bпроведен[иеы]|выполнен[ие]", "номинализация вместо глагола"),
    (r"\bданн(?:ый|ая|ое|ому)\b", "«данный» → «этот» или убрать"),
    (r"\bуказанн(?:ый|ая|ое|ому)\b", "«указанный» → назвать прямо"),
    (r"\bрассматриваем(?:ый|ой|ые|ую)\b", "«рассматриваемый» → «этот»"),
    (r"\bвышеупомянут|ранее упомянут|нижеупомянут|указанн[ый|ые] выше", "отсылка вместо имени"),
    (r"\bв рамк[ае]х\b", "«в рамках» → «по» или убрать"),
    (r"\bсо сторон[аы]\b", "«со стороны» → существительное"),
    (r"\bимеет мест[оу]\b", "«имеет место» → «есть»"),
    (r"\bпредставляет соб[ой]\b", "→ «есть»"),
    (r"\bс целью\b", "«с целью» → «чтобы»"),
    (r"\bдля того,? чтобы\b", "→ «чтобы»"),
    (r"\bв ?виде того что|ввиду того что|по причин[еа] того что", "→ «потому что»"),
    (r"\bв связ[е] с тем что", "→ «так как»"),
    (r"\bв случа[е] если\b", "→ «если»"),
    (r"\bна сегодняшн[ий] ден[ь]|\bв настоящ[ее] время|\bв данный момент", "→ «сейчас»"),
    (r"\bв современн[ом] мир[е]|\bв наше время|\bв эпох[уи]\b", "клише-вступление"),
    (r"\b(?:необходимо|стоит|важно|нужно) (?:учитыват|помн|понимат|отмечат|замечат)|"
     r"\bследует отмечат|\bобратите внимани|\bхочется отметит", "мета-ввод без информации"),
    (r"\b(?:конечно|без сомнения|разумеется|очевидно|как известно)\b[,;]?",
     "усилитель без содержания"),
    (r"\b(?:в целом|в принципе|так сказать|по сути|как бы)\b", "смягчитель без содержания"),
    (r"\b(?:достаточно|вполне|известно|определённый|некий|ряд) (?:важно|сложно|много|вопрос|случай|фактор)",
     "размывание формулировки"),
    (r"\bявляет(?:ся|еся)\b", "«является» → «есть» или глагол"),
    (r"\b(?:реализаци|оптимизаци|автоматизаци|детализаци|организаци|взаимодейств)ие\b",
     "номинализация на -ие"),
    (r"\bнадеемся|\bбудем рад[ы]|\bс удовольствием|\bотличн\w+ вопрос|\bдавайте разбер"
     r"|\bмы с вами|\bнапишит\w+ нам|\bобратит\w+сь к нам|\bсвяжет\w+сь с нами",
     "чат-остаток или призыв, не информация"),
    (r"\bподвед\w+ итог|\bрезюмируя|\bитак,|\bтаким образом,|\bотсюда следует|\bподводя итог",
     "служебный переход — часто пуст"),
    (r"\b(?:вопрос|тема|аспект|момент) треб\w+ (?:отдельн|рассмотрени|внимания)",
     "номинализация без содержания"),
]

# (regex, severity, code, подсказка) — следы сборки документа
LEFTOVER = [
    (r"\b(?:TODO|FIXME|TBD|XXX|COMING SOON|IN PROGRESS)\b", BLOCKER, "placeholder",
     "остался плейсхолдер"),
    (r"\?\?\?|\[\s*\]|<\s*>", BLOCKER, "placeholder", "пустое место или ???"),
    (r"\[\.{3}\]|\{\{[^}]{1,60}\}\}|<<[^>]{1,40}>>", BLOCKER, "placeholder",
     "незаполненный шаблон"),
    (r"(?<![\w-])(?:вставить|дописать|заполнить|подставить|впиши|указать)(?![\w-])\s*(?:здесь|тут|ниже|выше)?",
     MAJOR, "placeholder_word", "служебная пометка автору в теле"),
    (r"\b(?:в|во|для|после) предыдущ\w* верси\w*|\bверси[ияяи] \d|\bпрежн\w* редакц\w*|"
     r"\bстар\w+ вариант\w*|\bдо правок\b|\bизменён\w* по сравнени|\bэта версия (?:до|после)", MAJOR,
     "version_ref", "ссылка на другую версию этого же документа"),
    (r"\bchangelog\b|\bсписок изменений\b|\bистория правок\b|\bистория версий\b|\bчто нового\b",
     MINOR, "version_ref", "служебный блок версий (только если запрашивался)"),
    (r"как я (?:уже |ранее |выше |теперь )?(?:говорил|упоминал|писал|отмечал|сообщал|пояснял|"
     r"показывал|делал)", BLOCKER, "session_residue", "обрубок диалога: читатель не знает, о чём «я»"),
    (r"как мы (?:обсуждали|договорились|говорили|выяснили|решали|считали|смотрели)", BLOCKER,
     "session_residue", "обрубок диалога"),
    (r"в (?:наш(?:ем|ей|их|е|и)|этом|этой|текущ(?:ем|ей|их)) (?:разговоре|чате|диалоге|обсуждении|"
      r"переписке|беседе|сессии|ветке|трее)|\bнашей сессии|\bв наш[еем] чате|\bв этом чате",
      BLOCKER, "session_residue",
     "обрубок диалога"),
    (r"(?:ты|вы) (?:просил[и]?|спрашивал[и]?|задавал[и]?|уточнял[и]?)\b|"
     r"(?:по|согласно|как) (?:твоему|вашему|тебя|вас) (?:запросу|вопросу|сообщению|списку|словам)|"
     r"отвечая на (?:вопрос|запрос)|как ты хотел[и]?", MAJOR, "session_residue",
     "опора на незафиксированный в документе вопрос/договорённость"),
    (r"\bкак (?:указано|описано|показано|видно|отмечено|сказано) выше\b|\bвыше сказан|"
     r"\bкак отмечено ниже\b", MINOR, "dangling_ref", "отсылка «выше/ниже» вместо имени раздела"),
    (r"\bсм\.? ниже\b|\bниже перечислен|\bсм\. рисунок\b|\bсм\. таблицу\b|\bсм\. пример\b",
     MINOR, "dangling_ref", "отсылка без имени раздела"),
    (r"sequential[ -]?think|\bскилл\w*\b|\bskills?\b|субагент\w*|\bsubagent\w*|"
     r"agent[ -]manager|\bMCP\b|Playwright|SearXNG|webfetch|\.kilo\b|develop/|\bпромпт\w*|"
     r"\bтокен[аыов]*\b|контекст сессии|\bLLM\b|language model|\bнейросет\w+|"
     r"как (?:AI|ИИ|нейросеть|модель|ассистент|чат-бот)\b", MAJOR, "kitchen_sink",
     "утечка внутренней кухни: читателю это не нужно"),
    (r"\b(?:AI|ИИ|нейросеть|ChatGPT|GPT-\d|Claude|Gemini|Copilot) (?:сгенерировал|подготовил|"
     r"написал|составил|проверил)", MAJOR, "kitchen_sink", "упоминание авторства модели"),
    (r"\b(?:в|на) (?:отдельн\w*|друг\w*|соседн\w*|следующ\w*) (?:файле|документе|папке|архиве|"
     r"носитель[ее]|сервере)|\bприл\.\s*\d|\bприлага[еется|ется]|идёт в комплект|по пути\b|"
     r"file://|\bв архив\w*|\bна диск\w*", MAJOR, "external_ref",
     "ссылка на другой документ или носитель"),
    (r"(?:см\.|смотри|ищи|открой|найди|посмотри)[^.\n]{0,30}?\b(?:файл\w*|документ\w*|отчёт\w*|"
     r"отчет\w*|приложен\w*|папк\w*|архив\w*|репозитор\w*|wiki|confluence|notion|excel|word|"
     r"презентац\w*|таблиц\w*|схем\w*|диаграмм\w*)", MAJOR, "external_ref",
     "отсылка к другому документу вместо содержания здесь"),
]

LINK_TEXT_JUNK = re.compile(
    r"\[(?:сюда|по (?:этой |эту |данн\w+ )?ссылк[еау]|эт[ой|у] (?:ссылк[еау]|страниц[еа]|ресурсу)|"
    r"данн\w+ (?:ссылк[еау]|страниц[еа]|ресурсу|сайт)|тут|здесь|источник|сайт|ссылка|ссылочка|"
    r"more|link|here|details|нажмите|кликните|подробнее|перейти|официальный сайт)\b[^\]]*\]", re.I)
LOCAL_LINK = re.compile(r"(?<!\!)\[[^\]\n]{1,80}\]\((?!https?:|mailto:|tel:|#)([^)\s]{1,120})\)")
ACRONYM = re.compile(r"\b[А-ЯЁA-Z]{2,}(?:[-/][А-ЯЁA-Z]{2,})*\b")
CAMELCASE = re.compile(r"\b[A-Z][a-z]{2,}(?:[A-Z][a-z]+)+\b")
JARGON = re.compile(
    r"\b(?:к[эе]шбэк\w*|cashback|шеринг|sharing|фрилан\w*|freelanc\w*|аутсорс\w*|outsource\w*|"
    r"аутстафф\w*|дедлайн\w*|deadline|бенчмарк\w*|benchmark|стендап|деплой\w*|deploy|бэкап\w*|"
    r"backup|фаервол\w*|firewall|репозиторий|мердж\w*|merge|коммит\w*|сабмит|аптайм|uptime|"
    r"эскроу|escrow|лидген|воронк[аи]|промокод|купон|реферал\w*|аффилиат\w*|хостинг|домен|"
    r"физлиц\w*|юрлиц\w*|самозанят\w*|обременен\w*|рефинанс\w*|реструктур\w*|неустойк\w*|"
    r"взыскан\w*|удержан\w*|начислен\w*|поручител\w*|залогодат\w*|кредитор\w*|дебитор\w*|"
    r"банкрот\w*|вычет\w*|эмисси\w*|дивиденд\w*|купон\w*|волатильн\w*|ликвидн\w*|"
    r"СПб|ЛО|МО|СФР|ПФР|ФСС|ФНС|ИФНС|Росреестр|ЕГРН|ЕГРИП|ГИБДД|МЧС|МВД|РЖД|ДДУ|ОСАГО|КАСКО|"
    r"SSL|TLS|VPN|DNS|API|SDK|IDE|QA|UX|UI|ERP|BPM|CRM|CMS|SEO|SLA|KPI|ROI|APR|CAGR|ETF|ОФЗ|"
    r"ИИС|МРОТ|УСН|НДС|НДФЛ|ФЗ|ОГРН|ИНН|КПП|СНИЛС)\b", re.I)
FRESHNESS = re.compile(
    r"актуальн\w+ на|по состояни\w+ на|по данным на|данны\w+ на|срез на|проверено на|"
    r"актуальность|состояние на|по состоянию|на \d{1,2}[.]\d{1,2}[.]\d{2,4}", re.I)
NORM_MARKERS = re.compile(
    r"\b(?:ставк[а-иы]|процент\w*|%|₽|руб\w*|\bФЗ\b|стат\w* \d|пункт\w* \d|\bМРОТ\b|цен[аыы]|"
    r"стоимост\w*|тариф\w*|штраф\w*|пен\w*|вычет\w*|налог\w*|вклад\w*|кредит\w*|ипотек\w*|"
    r"лекарств\w*|доз\w*|препарат\w*|анализ\w*|верси[яа] \d|\bPNPLA\b|\bМВД\b)", re.I)
MIXED_TOKEN = re.compile(r"[0-9A-Za-zА-Яа-яЁё#_.-]+")
CYR = re.compile(r"[А-Яа-яЁё]")
LAT = re.compile(r"[A-Za-z]")
PRICE_MARK = re.compile(r"\b(?:цена|стоимост[ьи]|артикул|sku|модель|тариф|вклад|курс|скидк|"
                        r"бюджет|смета|оф[еэ]рт)\w*", re.I)
WEEKDAY_BY_FORM = {}
for _i, _name in enumerate(dp.WEEKDAY_NAMES):
    WEEKDAY_BY_FORM[_name] = _i
for _i, _short in enumerate(["пн", "вт", "ср", "чт", "пт", "сб", "вс"]):
    WEEKDAY_BY_FORM[_short] = _i
WEEKDAY_BY_FORM.update({"воскренье": 6, "среду": 2, "средой": 2, "среды": 2,
                        "четверг": 3, "четверга": 3, "четвергу": 3, "четвергом": 3,
                        "пятницу": 4, "пятницы": 4, "понедельника": 0, "понедельнику": 0,
                        "вторника": 1, "вторнику": 1, "вторником": 1, "субботу": 5,
                        "субботы": 5, "воскресенья": 6, "воскресенью": 6})
WEEKDAY_INFLECTED = re.compile(r"\b(" + "|".join(sorted(WEEKDAY_BY_FORM, key=len, reverse=True))
                               + r")\b", re.I)
PLACEHOLDER_TOKENS = {"TODO", "FIXME", "TBD", "XXX", "NOTE", "INFO", "WARN", "ERROR"}
ROMAN = {"II", "III", "IV", "VI", "VII", "VIII", "IX", "XI", "XII", "XIII", "XIV", "XV", "XX"}
# Капслок для выделения и служебные коды скриптов: не аббревиатуры для читателя
EMPHASIS = {"НЕ", "ДА", "ВСЕ", "НИ", "ОТ", "ДО", "ИЗ", "НЕТ", "ТО", "ЧЕТ", "XX", "YY",
            "ДД", "ММ", "ГГ", "ГГГГ", "RU", "EN", "US", "EU", "GB", "DE", "FR", "WWW",
            "BLOCKER", "MAJOR", "MINOR", "STRUCTURE", "MARKUP", "LEFTOVER", "GLOSSARY",
            "NUMBERS", "TABLES", "WATER", "DEAD", "UNVERIFIED", "PRODUCT", "SCHEME",
            "TEXT", "CONTEXT", "TITLE", "REDIRECT", "INTERNAL", "SERVICE", "PASS", "FAIL",
            "TYPOS", "GRAMMAR", "PUNCTUATION", "LOGIC", "MISC", "TYPOGRAPHY", "STYLE"}
MONEY_CONTEXT = re.compile(r"₽|руб\w*|стоимост\w*|сумм\w*|итог\w*|цен[аы]|взнос|платеж\w*|"
                           r"налог\w*|вычет\w*|доход\w*|расход\w*|тариф\w*|смет\w*|бюджет\w*|"
                           r"вклад\w*|кредит\w*|долг\w*|штраф\w*|пен\w*|зарплат\w*|гонорар\w*|"
                           r"млн|млрд|тыс|тысяч", re.I)
# Служебные слова в отсылке «см. раздел X»: не часть имени раздела
REF_HEAD_WORDS = {"раздел", "раздела", "разделу", "разделе", "секция", "секции", "глава",
                  "главы", "главе", "пункт", "пункта", "пункту", "подраздел", "подраздела",
                  "список", "списка", "списку", "абзац", "абзаца", "блок", "блока",
                  "таблица", "таблицы", "формат", "формата", "см", "смотри", "найди",
                  "открой", "перейди", "ниже", "выше", "в", "на", "к", "у", "от", "и", "с",
                  "по", "что", "это", "далее", "следующий", "указанный",
                  "скилл", "скилла", "навык", "навыка", "файл", "файла", "документ",
                  "документа", "схема", "схемы", "инструкция", "инструкции"}
REF_SKIP_WORDS = {"ВАЖНО", "ВНИМАНИЕ", "IMPORTANT", "NOTE", "ПРИМЕЧАНИЕ", "СМ", "СМОТРИ"}


class Lint:
    def __init__(self, text, name, args):
        self.text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.name = name
        self.args = args
        self.lines = self.text.split("\n")
        self.starts = dp.line_starts(self.text)
        self.masked, self.spans = dp.mask_nonprose(self.text)
        self.quotes = dp.quote_spans(self.masked)
        self.masked_lines = self.masked.split("\n")
        self.fence = dp.code_fence_lines(self.text)
        self.headings = dp.headings(self.text)
        self.tables = dp.parse_tables(self.text)
        self.findings = []
        self.stats = {}

    # ---- helpers
    def add(self, sev, code, line, msg, ev=""):
        self.findings.append({"sev": sev, "code": code, "line": line, "msg": msg,
                              "evidence": (ev or "").strip()[:150]})

    def line_text(self, n):
        return self.lines[n - 1] if 1 <= n <= len(self.lines) else ""

    def is_code(self, n):
        return n in self.fence

    def line_of(self, pos):
        return dp.line_of(pos, self.starts)

    def in_quote(self, pos):
        """Позиция внутри цитаты: там документ приводит пример чужой речи."""
        return any(s <= pos < e for s, e in self.quotes)

    def is_checkbox_line(self, n):
        return bool(re.match(r"^\s*[-*+]\s+\[[ xX]\]", self.line_text(n)))

    def prose(self):
        """Замаскированная проза: без кода, таблиц, URL, путей, идентификаторов."""
        t = list(self.masked)
        for tb in self.tables:
            for n in range(tb["start_line"], tb["end_line"] + 1):
                if not (1 <= n <= len(self.lines)):
                    continue
                s = self.starts[n - 1]
                e = self.starts[n] - 1 if n < len(self.starts) else len(self.text)
                for i in range(s, min(e, len(t))):
                    if t[i] != "\n":
                        t[i] = " "
        return "".join(t)

    # ---- 1. структура
    def check_structure(self):
        hs = self.headings
        if not any(lvl == 1 for lvl, _, _, _ in hs):
            self.add(MAJOR, "STRUCTURE", 1, "нет заголовка H1: документ не назван")
        prev = 0
        for lvl, ln, title, _ in hs:
            if prev and lvl > prev + 1:
                self.add(MINOR, "STRUCTURE", ln, f"прыжок уровня заголовка {prev}→{lvl}: «{title}»")
            prev = lvl
        for i, (lvl, ln, title, _) in enumerate(hs):
            if i + 1 < len(hs) and hs[i + 1][0] > lvl:
                continue  # заголовок-контейнер: содержание в подразделах
            nxt = hs[i + 1][1] if i + 1 < len(hs) else len(self.lines) + 1
            if not "\n".join(self.lines[ln:nxt - 1]).strip():
                self.add(MAJOR, "STRUCTURE", ln, f"раздел «{title}» без содержания")
        titles = {t.lower() for _, _, t, _ in hs}
        slugs = {s for _, _, _, s in hs}
        for m in re.finditer(r"(?:см\.|см\s|смотри|перейди к)\s+"
                             r"[«\"]?([А-Яа-яЁёA-Za-z0-9][А-Яа-яЁёA-Za-z0-9 .:&-]{2,50})[»\"]?",
                             self.prose()):
            if self.in_quote(m.start()):
                continue
            words = [w for w in m.group(1).strip(" .:«»,;").split()
                     if w.lower().strip(",.;:«»") not in REF_HEAD_WORDS]
            ref = " ".join(words).lower()
            if not ref or len(ref.split()) > 3 or any(ch.isdigit() for ch in ref):
                continue
            if any(w.upper().strip(",.;:«»") in REF_SKIP_WORDS for w in words):
                continue
            matched = (any(ref == t or ref in t or t.startswith(ref) for t in titles)
                       or dp.slugify(ref) in slugs)
            if not matched:
                ln = self.line_of(m.start())
                if self.line_text(ln).lstrip().startswith("#"):
                    continue  # это сам заголовок, а не отсылка
                self.add(MINOR if self.args.internal else MAJOR, "STRUCTURE", ln,
                         f"отсылка к несуществующему разделу: «{m.group(1).strip()}»")
        prose = self.prose()
        if NORM_MARKERS.search(prose) and not FRESHNESS.search(self.text) \
                and not self.args.internal:
            self.add(MAJOR, "STRUCTURE", 1,
                     "в документе нормы/ставки/цены, но нет отметки актуальности «на ДД.ММ.ГГГГ»")
        for m in FRESHNESS.finditer(self.text):
            dm = re.search(r"(\d{1,2})[.](\d{1,2})[.](\d{2,4})", m.group(0))
            if dm:
                try:
                    d0 = date(int(dm.group(3)) if int(dm.group(3)) > 100 else
                              2000 + int(dm.group(3)), int(dm.group(2)), int(dm.group(1)))
                except ValueError:
                    continue
                age = (self.args.asof - d0).days
                if age > 180:
                    self.add(MINOR, "STRUCTURE", self.line_of(m.start()),
                             f"отметка актуальности устарела на {age // 30} мес.: {d0} — "
                             "обнови данные или дату")
        if len(hs) >= 6 and not re.search(r"\bоглавлен[иеи]|\bсодержани[ея]|\btable of contents|"
                                          r"\btl;dr|\bсуть\b|\bкратко\b", self.text, re.I):
            self.add(MINOR, "STRUCTURE", 1, "6+ разделов без оглавления или блока «Суть»")

    # ---- 2. разметка и типографика
    def check_markup(self):
        markers = [n for n in sorted(self.fence)
                   if re.match(r"^\s*(`{3,}|~{3,})", self.line_text(n))]
        if len(markers) % 2:
            self.add(BLOCKER, "MARKUP", markers[-1] if markers else 1,
                     "незакрытый блок кода ``` — текст после него читается как код")
        for s, e, block in dp.paragraphs(self.masked):
            for o_rx, c_rx, label in ((r"«", r"»", "«»"), (r"\(", r"\)", "()"), (r"\[", r"\]", "[]")):
                o, c = len(re.findall(o_rx, block)), len(re.findall(c_rx, block))
                if o != c and not self.is_code(self.line_of(s)):
                    self.add(MAJOR, "MARKUP", self.line_of(s),
                             f"нераспарены {label}: {o} откр. / {c} закр.", block[:70].replace("\n", " "))
        for s, e, block in dp.paragraphs(self.masked):
            if block.count("**") % 2 and not self.is_code(self.line_of(s)):
                self.add(MAJOR, "MARKUP", self.line_of(s),
                         "незакрытое выделение ** в абзаце", block[:70].replace("\n", " "))
            if block.count("__") % 2 and "__" in block and not re.match(r"^\s*_+\s*$", block):
                self.add(MAJOR, "MARKUP", self.line_of(s),
                         "незакрытое выделение __ в абзаце", block[:70].replace("\n", " "))
        for n, ln in enumerate(self.lines, 1):
            if self.is_code(n) or not ln.strip():
                continue
            mln = self.masked_lines[n - 1] if n - 1 < len(self.masked_lines) else ""
            if '"' in mln and not re.search(r"=\s*\"|href=|src=|title=", mln):
                self.add(MINOR, "MARKUP", n, "прямая кавычка \" вместо «»", mln.strip()[:70])
            if re.search(r"(?<=[А-Яа-яЁё])'|(?<=[А-Яа-яЁё])‘|’(?=[А-Яа-яЁё])", mln):
                self.add(MINOR, "MARKUP", n, "латинский апостроф в кириллическом слове",
                         mln.strip()[:70])
            for tok in MIXED_TOKEN.findall(ln):
                for part in re.split(r"[#. _\-]+", tok):
                    if len(part) >= 2 and CYR.search(part) and LAT.search(part):
                        self.add(MAJOR, "MARKUP", n,
                                 f"смешаны кириллица и латиница (омоглифы): «{part}» — ломаются "
                                 "поиск и копирование", ln.strip()[:70])
            if re.search(r"(?<=[\wА-Яа-яЁё]) - (?=[\wА-Яа-яЁё])", ln):
                self.add(MINOR, "MARKUP", n, "дефис с пробелами вместо тире « — »", ln.strip()[:70])
            if re.search(r"(?<=\d)-(?=\d)", ln):
                self.add(MINOR, "MARKUP", n, "в диапазоне нужна черта: 10–15", ln.strip()[:70])
            if re.search(r"[\wА-Яа-яЁё]—[\wА-Яа-яЁё]", ln):
                self.add(MINOR, "MARKUP", n, "тире без пробелов", ln.strip()[:70])
            if "|" not in ln and re.search(r"\S  +\S", ln.replace("\t", " ")):
                self.add(MINOR, "MARKUP", n, "двойной пробел", ln.strip()[:70])
            if re.search(r"\s[,;:.](?=\s|$)", ln):
                self.add(MINOR, "MARKUP", n, "пробел перед знаком препинания", ln.strip()[:70])
            for m in re.finditer(r"\b([А-Яа-яЁёA-Za-z][\wА-Яа-яЁё]{2,})\s+\1\b", mln, re.I):
                if self.in_quote(self.starts[n - 1] + m.start()):
                    continue  # цитируемый пример чужой речи
                self.add(MAJOR, "MARKUP", n, f"удвоенное слово: «{m.group(1)} {m.group(1)}» — "
                         "типовая опечатка сборки текста", mln.strip()[:70])
        seq = []
        for n, ln in enumerate(self.lines, 1):
            m = re.match(r"^\s*(\d{1,2})[.)]\s+", ln)
            if m:
                seq.append((n, int(m.group(1))))
            elif ln.strip():
                self._flush_seq(seq)
                seq = []
        self._flush_seq(seq)
        for tb in self.tables:
            w = len(tb["header"])
            for k, row in enumerate(tb["rows"]):
                if len(row) != w:
                    self.add(MAJOR, "MARKUP", tb["sep_index"] + 1 + k,
                             f"в таблице строка {k + 1}: {len(row)} ячеек вместо {w}")
            if any(not c for c in tb["header"]):
                self.add(MINOR, "MARKUP", tb["start_line"], "пустая колонка в шапке таблицы")

    def _flush_seq(self, seq):
        prev = None
        for ln, num in seq:
            if prev is not None and num not in (prev + 1, 1):
                self.add(MINOR, "MARKUP", ln, f"нумерация списка: после {prev} идёт {num}")
            prev = num

    # ---- 3. самодостаточность
    def check_leftover(self):
        compiled = [(re.compile(rx, re.I), sev, code, note) for rx, sev, code, note in LEFTOVER]
        for rx, sev, code, note in compiled:
            for m in rx.finditer(self.masked):
                ln = self.line_of(m.start())
                if self.is_code(ln):
                    continue
                if self.in_quote(m.start()) and code in (
                        "session_residue", "kitchen_sink", "version_ref", "placeholder",
                        "placeholder_word", "dangling_ref"):
                    continue  # в кавычках документ приводит пример, а не говорит сам
                if code == "placeholder" and self.is_checkbox_line(ln) and m.group(0) in ("[]", "[ ]"):
                    continue  # маркер списка задач, а не пустое место
                if self.args.internal and code in ("kitchen_sink", "placeholder_word"):
                    continue  # служебный документ ссылается на механизмы и содержит инструкции
                self.add(sev, code, ln, note, self.line_text(ln))
        for m in re.finditer(r"<[А-Яа-яЁёA-Za-z][^<>\n]{1,30}>", self.masked):
            ln = self.line_of(m.start())
            if self.is_code(ln):
                continue
            if re.match(r"^</?(?:br|b|i|u|em|strong|span|div|p|li|ul|ol|h[1-6])\b", m.group(0), re.I):
                continue
            self.add(MAJOR, "placeholder", ln, "похоже на незаполненный шаблон", m.group(0))
        for m in LOCAL_LINK.finditer(self.text):
            ln = self.line_of(m.start())
            if self.is_code(ln):
                continue
            self.add(MAJOR, "external_ref",
                     ln, f"ссылка на локальный файл «{m.group(1)}» — читатель документа его не "
                     "получит: замени содержимым или публичным URL", self.line_text(ln))

    # ---- 4. глоссарий
    def check_glossary(self):
        """Кандидаты в глоссарий и перебор.

        Линтер не решает за редактора: он перечисляет аббревиатуры и жаргон
        без расшифровки как КАНДИДАТЫ и отдельно ловит перебор — статьи о
        терминах, которые аудитория знает по условию (--audience-known), и
        статьи о единичных упоминаниях, где достаточно скобок.
        """
        head, body, body_start = self._glossary()
        wl = {w.strip().upper() for w in self.args.acronym_whitelist.split(",") if w.strip()}
        known = {w.strip().upper() for w in self.args.audience_known.split(",") if w.strip()}
        prose = self.prose()
        # проза без тела глоссария — для подсчёта реальных употреблений
        body_prose = prose
        if head and body:
            a = body_start
            b = min(len(body_prose), body_start + len(body))
            body_prose = body_prose[:a] + " " * (b - a) + body_prose[b:]
        found = {}
        for m in ACRONYM.finditer(prose):
            tok = m.group(0).upper()
            if tok in wl or tok in PLACEHOLDER_TOKENS or tok in ROMAN or tok in EMPHASIS \
                    or self.is_code(self.line_of(m.start())):
                continue
            found.setdefault(tok, []).append(m.start())
        for m in JARGON.finditer(prose):
            found.setdefault(m.group(0).upper(), []).append(m.start())
        self.stats["terms"] = sorted(found)

        def occurrences(tok):
            n = 0
            for m in re.finditer(rf"(?<![А-Яа-яA-Za-z]){re.escape(tok)}(?![А-Яа-яA-Za-z])",
                                 body_prose, re.I):
                ln = self.line_of(m.start())
                if not self.is_code(ln):
                    n += 1
            return n

        undefined = []
        for tok, positions in sorted(found.items()):
            if tok in known:
                continue  # аудитория знает по условию: объяснять — шум
            if body and re.search(rf"(?<![А-Яа-яA-Za-z]){re.escape(tok)}(?![А-Яа-яA-Za-z])", body, re.I):
                continue
            first = min(positions)
            window = prose[max(0, first - 70):first + 110]
            defined = False
            for pm in re.finditer(r"\(([^)]{4,140})\)", window):
                inner = pm.group(1)
                if re.search(rf"^\s*{re.escape(tok)}\b", inner, re.I) or \
                        re.search(rf"{re.escape(tok)}\s*[—:=\-]", inner, re.I) or \
                        (tok in inner and dp.word_count(inner) >= 2):
                    defined = True
                    break
            if not defined:
                undefined.append((tok, self.line_of(first)))
        if undefined:
            sev = MINOR if (head or self.args.internal) else MAJOR
            for tok, ln in undefined[:25]:
                self.add(sev, "GLOSSARY", ln,
                         f"кандидат в глоссарий: «{tok}» без расшифровки при первом употреблении "
                         "— реши по уровню аудитории, нужна ли она")
            if not head and not self.args.internal and len(undefined) >= 2:
                self.add(MAJOR, "GLOSSARY", 1,
                         f"{len(undefined)} терминов/аббревиатур без расшифровки, раздела "
                         "«Глоссарий» нет — проверь, что из этого за пределами уровня аудитории")
        if head and body:
            for m in re.finditer(r"^\s*[-*+]\s+(.+)$", body, re.M):
                entry = m.group(1).strip()
                abs_pos = body_start + m.start(1)
                if dp.word_count(entry) < 3 and not re.search(r"[—:=\(]", entry):
                    self.add(MINOR, "GLOSSARY", self.line_of(abs_pos),
                             f"статья глоссария без расшифровки: «{entry[:40]}»")
            for m in re.finditer(r"^\s*[-*+]\s*(?:\*{1,2}|_{2})?([А-ЯЁA-Za-z][\w/-]{1,24})", body, re.M):
                tok = m.group(1).rstrip("-/")
                key = tok.upper()
                ln = self.line_of(body_start + m.start(1))
                if key in known:
                    self.add(MAJOR, "GLOSSARY", ln,
                             f"статья «{tok}» объясняет термин, который аудитория знает по "
                             "условию (--audience-known): удали статью")
                    continue
                n = occurrences(tok)
                if n == 0:
                    self.add(MINOR, "GLOSSARY", ln,
                             f"статья «{tok}» в глоссарии не встречается в тексте")
                elif n <= 1:
                    self.add(MINOR, "GLOSSARY", ln,
                             f"статья «{tok}» о единичном термине: достаточно скобок при первом "
                             "употреблении")
        for tok in sorted({m.group(0) for m in CAMELCASE.finditer(prose)}):
            if body and tok.lower() in body.lower():
                continue
            if tok.upper() in known:
                continue
            pos = prose.find(tok)
            self.add(MINOR, "GLOSSARY", self.line_of(pos),
                     f"название «{tok}» — проверь по уровню аудитории: пояснить в тексте или "
                     "вынести в глоссарий")

    def _glossary(self):
        rx = re.compile(self.args.glossary_heading, re.I)
        for i, (lvl, ln, title, _) in enumerate(self.headings):
            if rx.search(title):
                end_ln = len(self.lines)
                for lvl2, ln2, _, _ in self.headings[i + 1:]:
                    if lvl2 <= lvl:
                        end_ln = ln2 - 1
                        break
                body_start = self.starts[ln - 1] + len(title) + 1
                body = self.text[body_start:self.starts[min(end_ln, len(self.lines)) - 1]
                                 if end_ln < len(self.lines) else len(self.text)]
                return (lvl, ln, title), body, body_start
        return None, "", 0

    # ---- 5. числа и даты
    def check_numbers(self):
        prose = dp.mask_dates(self.prose())
        nums = [n for n in dp.extract_numbers(prose) if not self.is_code(self.line_of(n.start))]
        self.stats["numbers"] = len(nums)
        asof = self.args.asof
        for s, e, dt, raw, reason in dp.extract_dates(self.prose(), asof):
            ln = self.line_of(s)
            if self.is_code(ln):
                continue
            if reason:
                self.add(BLOCKER, "NUMBERS", ln, f"некорректная дата: {reason}", raw)
                continue
            if dt and dt.year > asof.year + 1:
                self.add(MAJOR, "NUMBERS", ln, f"год {dt.year} в будущем — проверь опечатку", raw)
            if dt:
                window = self.prose()[max(0, s - 45):e + 45]
                wm = re.search(WEEKDAY_INFLECTED, window)
                if wm:
                    want = WEEKDAY_BY_FORM.get(wm.group(1).lower())
                    if want is not None and want != dt.weekday():
                        self.add(MAJOR, "NUMBERS", ln,
                                 f"день недели не сходится: {raw} — это {dp.weekday_name(dt)}, "
                                 f"в тексте «{wm.group(1).lower()}»", window.strip()[:70])
        mixed_spans = [(a, b) for a, b, _ in dp.mixed_grouping(self.prose())]
        for a, b, raw in dp.mixed_grouping(self.prose()):
            ln = self.line_of(a)
            if not self.is_code(ln) and not self.in_quote(a):
                self.add(MAJOR, "NUMBERS", ln,
                         f"сломанная группировка разрядов: «{raw.strip()}» — число разбирается "
                         "неоднозначно, сверь с источником", raw.strip())
        for n in nums:
            if self.in_quote(n.start):
                continue  # формат в цитируемом примере — не дефект документа
            if any(s <= n.start < e for s, e in mixed_spans) and not (
                    "en_grouping" in n.flags or "en_grouping_dot" in n.flags):
                continue  # уже описан находкой сломанной группировки
            if "en_grouping" in n.flags or "en_grouping_dot" in n.flags:
                self.add(MAJOR, "NUMBERS", self.line_of(n.start),
                         f"английский формат разрядов: «{n.raw}» — по-русски {dp.fmt(n.value)}", n.raw)
            elif not n.grouped and not n.is_pct and not n.is_year and n.value >= 10000 \
                    and "." not in n.raw and "," not in n.raw:
                self.add(MINOR, "NUMBERS", self.line_of(n.start),
                         f"число без разрядов: «{n.raw}» — читается тяжело, пиши {dp.fmt(n.value)}",
                         n.raw)
        def is_amount(n):
            """Величина, а не номер/год/порт: валюта при числе или денежный контекст рядом."""
            if n.unit and any(p in n.unit for p in ("₽", "руб", "грн", "$", "€", "доллар", "фунт")):
                return True
            ctx = prose[max(0, n.start - 45):n.end + 45]
            return bool(MONEY_CONTEXT.search(ctx))

        money = [n for n in nums if not n.is_year and not n.is_pct and n.value >= 1000
                 and is_amount(n)]
        by_value = {}
        for n in money:
            by_value.setdefault(int(round(n.value)), []).append(n)
        for n in money:
            if not n.grouped and any(m.grouped for m in by_value.get(int(round(n.value)), [])):
                self.add(MINOR, "NUMBERS", self.line_of(n.start),
                         f"одно число записано и «{n.raw}», и с разрядами — унифицируй", n.raw)
        vals = sorted(by_value)
        pairs = 0
        for i, a in enumerate(vals):
            if pairs > 8:
                break
            for b in vals[i + 1:]:
                diff = b - a
                if diff > max(1000, a * 0.05):
                    break
                la = self.line_of(by_value[a][0].start)
                lb = self.line_of(by_value[b][0].start)
                rel = diff / a if a else 1
                sev = MAJOR if rel <= 0.01 else MINOR
                note = ("опечатка или потерянный член" if rel <= 0.01
                        else "похожие суммы рядом — убедись, что это разные величины")
                self.add(sev, "NUMBERS", la,
                         f"близкие, но не равные суммы: {dp.fmt(a)} и {dp.fmt(b)} "
                         f"(строки {la} и {lb}, разница {rel:.1%}) — {note}", "")
                pairs += 1
        dot = [n for n in nums if re.search(r"\d\.\d", n.raw.replace("\u00a0", ""))
               and "en_grouping_dot" not in n.flags]
        comma = [n for n in nums if "decimal_comma" in n.flags]
        if dot and comma:
            self.add(MINOR, "NUMBERS", self.line_of(dot[0].start),
                     "десятичные записаны и точкой, и запятой — унифицируй")
        cur = set()
        for n in nums:
            for part in (n.unit or "").split("|"):
                if part and part not in dp.MULTS:
                    cur.add(part)
        rub = {c for c in cur if c in {"₽", "руб", "рубль", "рубли", "рублей", "рублю", "руб."}}
        if len(rub) > 1:
            self.add(MINOR, "NUMBERS", 1, f"разные обозначения рублей: {sorted(rub)} — выбери одно")
        for n in nums:
            if n.is_pct and n.value > 100:
                pre = prose[max(0, n.start - 30):n.start]
                if not re.search(r"более|свыше|до |от |не менее|выше|эквивалент|в пересч", pre, re.I):
                    self.add(MINOR, "NUMBERS", self.line_of(n.start),
                             f"процент больше 100: «{n.raw}» — не перепутаны ли % и доля/множитель",
                             n.raw)

    # ---- 6. таблицы
    def check_tables(self):
        for tb in self.tables:
            if len(tb["rows"]) < 2:
                continue
            for k, row in enumerate(tb["rows"]):
                label = (row[0] if row else "").lower()
                if not re.search(r"итог|всего|сумма|разр[еe]шено|максимум|всего за|нужно всего", label):
                    continue
                for col in range(1, len(tb["header"])):
                    data = []
                    ok = True
                    for r in tb["rows"][:k]:
                        if col >= len(r) or not r[col].strip():
                            ok = False
                            break
                        ns = [n for n in dp.extract_numbers(dp.mask_dates(r[col])) if not n.is_year]
                        if len(ns) != 1:
                            ok = False
                            break
                        data.append(ns[0].value)
                    if not ok or len(data) < 2 or col >= len(row) or not row[col].strip():
                        continue
                    tn = [n for n in dp.extract_numbers(dp.mask_dates(row[col])) if not n.is_year]
                    if len(tn) != 1:
                        continue
                    want, got = sum(data), tn[0].value
                    if want and abs(want - got) / max(abs(want), 1) > 0.01:
                        self.add(MAJOR, "TABLES", tb["sep_index"] + 1 + k,
                                 f"итог в столбце «{tb['header'][col]}» не сходится: строки дают "
                                 f"{dp.fmt(want)}, в итоге {dp.fmt(got)}", row[col])
            for k, row in enumerate(tb["rows"]):
                filled = sum(1 for c in row if c.strip())
                if filled < 2:
                    continue
                for ci, c in enumerate(row):
                    if not c.strip() and ci < len(tb["header"]):
                        self.add(MINOR, "TABLES", tb["sep_index"] + 1 + k,
                                 f"пустая ячейка в колонке «{tb['header'][ci]}» — поставь «—»")

    # ---- 7. вода
    def check_water(self):
        prose = self.prose()
        total = dp.word_count(prose)
        hits = 0
        for rx, note in STOPLIST:
            for m in re.finditer(rx, prose, re.I):
                ln = self.line_of(m.start())
                if self.is_code(ln):
                    continue
                hits += 1
                if hits <= 40:
                    self.add(MINOR, "WATER", ln, f"вода: {note}", self.line_text(ln))
        if total and hits >= 8 and hits / total > 0.012:
            self.add(MAJOR, "WATER", 1,
                     f"{hits} пустых конструкций на ≈{total} слов — текст раздут, сожми")
        seen = {}
        for n, ln in enumerate(self.lines, 1):
            if self.is_code(n) or not ln.strip() or ln.strip().startswith("|"):
                continue
            norm = re.sub(r"[^\wА-Яа-яЁё\s]", "", ln.lower())
            norm = re.sub(r"\s+", " ", norm).strip()
            if dp.word_count(norm) < 6:
                continue
            if norm in seen:
                self.add(MAJOR, "WATER", n, f"дословный повтор строки {seen[norm]}", ln.strip()[:80])
            else:
                seen[norm] = n
        blocks = [(s, b) for s, _, b in dp.paragraphs(prose) if dp.word_count(b) >= 12]
        for i in range(len(blocks) - 1):
            ratio = difflib.SequenceMatcher(None, blocks[i][1].lower(), blocks[i + 1][1].lower()).ratio()
            if ratio > 0.72:
                self.add(MAJOR, "WATER", self.line_of(blocks[i + 1][0]),
                         f"соседние абзацы дублируют смысл ({ratio:.0%} сходства) — оставь один")
        lens = []
        reported = 0
        for ps, pe, _block in dp.paragraphs(prose):
            base = prose[ps:pe]
            blines = base.split("\n")
            is_list = any(re.match(r"^\s*(?:[-*+]\s+|\d{1,2}[.)]\s+|\|)", l) for l in blines)
            if is_list:
                segs, pos = [], 0
                for l in blines:
                    segs.append((pos, l))
                    pos += len(l) + 1
            else:
                segs = [(0, base)]
            for off, seg_text in segs:
                for s, _, sent in dp.split_sentences(seg_text):
                    w = dp.word_count(sent)
                    if not w:
                        continue
                    lens.append(w)
                    abs_pos = ps + off + s
                    if w > self.args.max_sentence_words and not self.is_code(self.line_of(abs_pos)) \
                            and reported < 12:
                        reported += 1
                        self.add(MINOR, "WATER", self.line_of(abs_pos),
                                 f"предложение из {w} слов (порог {self.args.max_sentence_words}) — "
                                 "разбей", sent[:110])
        self.stats["sentences"] = len(lens)
        self.stats["avg_sentence_words"] = round(sum(lens) / len(lens), 1) if lens else 0
        self.stats["max_sentence_words"] = max(lens) if lens else 0
        for m in LINK_TEXT_JUNK.finditer(self.text):
            if self.in_quote(m.start()):
                continue
            self.add(MAJOR, "WATER", self.line_of(m.start()),
                     "текст ссылки ничего не сообщает — пиши, куда ведёт", m.group(0))
        for m in re.finditer(r"\[\s*\]\(", self.text):
            self.add(MAJOR, "WATER", self.line_of(m.start()), "пустой текст ссылки")
        for m in re.finditer(r"\b(?:в этом|в настоящ\w+|данны\w+) документ\w*|"
                             r"(?:я|мы) подготовил\w*|\bниже приведён\w*|\bдалее рассказано|"
                             r"\bв этом ответе|\bв этом сообщении|\bкак советник|\bмоя задача",
                             prose, re.I):
            self.add(MINOR, "WATER", self.line_of(m.start()),
                     "мета-комментарий о самом документе", self.line_text(self.line_of(m.start())))
        # цены/артикулы без ссылки (оффлайн-сигнал; живость проверяет link_check)
        for s, e, block in dp.paragraphs(self.text):
            if PRICE_MARK.search(block) and "http" not in block and "@" not in block:
                if len(block.split("\n")) <= 3 and dp.word_count(block) >= 4:
                    self.add(MINOR, "WATER", self.line_of(s),
                             "абзац про цену/модель/артикул без ссылки на источник или карточку",
                             block[:80].replace("\n", " "))


def main():
    ap = argparse.ArgumentParser(description="Редакционный линтер документа (оффлайн)")
    ap.add_argument("path", help="файл или - для stdin")
    ap.add_argument("--max-sentence-words", type=int, default=30)
    ap.add_argument("--acronym-whitelist", default=DEFAULT_WHITELIST)
    ap.add_argument("--audience-known", default="",
                    help="термины, которые аудитория знает по условию задачи (через запятую): "
                         "по ним не выдаются кандидаты в глоссарий, а статьи глоссарии о них "
                         "отмечаются как перебор")
    ap.add_argument("--glossary-heading",
                    default=r"глоссар|термины|расшифровк|определени|словар[ьиеу]")
    ap.add_argument("--asof", default=None, help="дата среза YYYY-MM-DD (сегодня по умолчанию)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--internal", action="store_true",
                    help="служебный документ (конфиг, инструкция, навык): разрешены ссылки на "
                         "механизмы проекта, глоссарий не блокируется")
    args = ap.parse_args()

    if args.path == "-":
        # sys.stdin в Windows декодирует по локали (cp1251) -> кириллица в мусор;
        # читаем байты и декодируем utf-8 явно
        stream = getattr(sys.stdin, "buffer", None)
        text = stream.read().decode("utf-8", errors="replace") if stream else sys.stdin.read()
        name = "<stdin>"
    else:
        with open(args.path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        name = args.path
    args.asof = (datetime.strptime(args.asof, "%Y-%m-%d").date() if args.asof else date.today())

    lint = Lint(text, name, args)
    for fn in (lint.check_structure, lint.check_markup, lint.check_leftover,
               lint.check_glossary, lint.check_numbers, lint.check_tables, lint.check_water):
        try:
            fn()
        except Exception as exc:  # fail loud: сбой проверки не прячет остальные
            lint.add(BLOCKER, "INTERNAL", 0, f"{fn.__name__} упал: {type(exc).__name__}: {exc}")

    merged = {}
    for f in lint.findings:
        key = (f["sev"], f["code"], f["line"], f["msg"])
        if key in merged:
            merged[key]["n"] = merged[key].get("n", 1) + 1
        else:
            f.setdefault("n", 1)
            merged[key] = f
    lint.findings = list(merged.values())
    lint.findings.sort(key=lambda f: (_SEV[f["sev"]], f["code"], f["line"]))
    counts = {s: sum(1 for f in lint.findings if f["sev"] == s) for s in (_SEV)}

    if args.json:
        print(json.dumps({"file": name, "asof": str(args.asof), "counts": counts,
                          "stats": lint.stats, "findings": lint.findings},
                         ensure_ascii=False, indent=1))
    else:
        print(f"=== DOC LINT: {name} (срез {args.asof}) ===")
        cur = None
        for f in lint.findings:
            if f["sev"] != cur:
                cur = f["sev"]
                print(f"\n--- {cur} ({counts[cur]}) ---")
            print(f"[{f['code']}:{f['line'] or '-'}] {f['msg']}"
                  + (f" (×{f['n']})" if f.get("n", 1) > 1 else ""))
            if f["evidence"]:
                print(f"    ↳ {f['evidence']}")
        print("\n--- СВОДКА ---")
        print(f"BLOCKER={counts[BLOCKER]} MAJOR={counts[MAJOR]} MINOR={counts[MINOR]}")
        words = dp.word_count(lint.prose())
        print(f"строк={len(lint.lines)} слов≈{words} разделов={len(lint.headings)} "
              f"таблиц={len(lint.tables)} чисел={lint.stats.get('numbers', 0)} "
              f"предложений={lint.stats.get('sentences', 0)} "
              f"ср.длина={lint.stats.get('avg_sentence_words', 0)} слов "
              f"макс={lint.stats.get('max_sentence_words', 0)}")
        if lint.stats.get("terms"):
            print("термины/аббревиатуры: " + ", ".join(lint.stats["terms"][:30]))
        print("Здесь НЕ проверяется: орфография и грамматика (spell_ru.py), живость ссылок "
              "(link_check.py), верность расчётов (calc_verify.py), понимание читателем "
              "(холодный читатель).")
    return 2 if counts[BLOCKER] else (1 if counts[MAJOR] else 0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
