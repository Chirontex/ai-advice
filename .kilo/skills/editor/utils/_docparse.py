"""Общие разборы текста для скриптов скилла editor (stdlib, без зависимостей).

Соглашение всех утилит: маскирование не-прозы сохраняет длину строк и
переводы строк, поэтому смещения из regex/LanguageTool всегда отображаются
на исходные номера строк документа.
"""
from __future__ import annotations

import re
from datetime import date

# Разделители разрядов, встречающиеся в русском тексте
SEPS = "\u00a0\u2007\u2008\u2009\u202f\u205f "
# Символы группировки разрядов ВНУТРИ числа (tab сюда не входит: это не разряд)
DIGIT_SEPS = "\u00a0\u2007\u2008\u2009\u202f\u205f "
_SEP_DROP = str.maketrans({c: "" for c in SEPS})

MONTHS_GEN = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11,
    "декабря": 12,
}
MONTHS_NOM = {
    "январь": 1, "февраль": 2, "март": 3, "апрель": 4, "май": 5, "июнь": 6,
    "июль": 7, "август": 8, "сентябрь": 9, "октябрь": 10, "ноябрь": 11,
    "декабрь": 12,
}
MONTHS = {**MONTHS_GEN, **MONTHS_NOM}
MONTH_ABBR = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "июн": 6, "июл": 7,
              "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12}
_MONTH_ALT = "|".join(sorted(list(MONTHS) + list(MONTH_ABBR) + ["янв", "фев", "мар", "апр",
                                                                "июн", "июл", "авг", "сен",
                                                                "окт", "ноя", "дек"],
                             key=len, reverse=True))
WEEKDAYS = {"понедельник": 0, "вторник": 1, "среда": 2, "четверг": 3, "пятница": 4,
            "суббота": 5, "воскресенье": 6, "воскренье": 6}
WEEKDAY_NAMES = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота",
                 "воскресенье"]

MULTS = {
    "тыс": 10 ** 3, "тысяча": 10 ** 3, "тысячи": 10 ** 3, "тысяч": 10 ** 3, "тысячу": 10 ** 3,
    "млн": 10 ** 6, "миллион": 10 ** 6, "миллиона": 10 ** 6, "миллионов": 10 ** 6,
    "миллионе": 10 ** 6,
    "млрд": 10 ** 9, "миллиард": 10 ** 9, "миллиарда": 10 ** 9, "миллиардов": 10 ** 9,
    "миллиарде": 10 ** 9,
}
CURRENCY_WORDS = re.compile(
    r"(?:₽|руб\.?|рубл[еияй]+|грн\.?|коп\.?|€|euros?|евро|usd|dollars?|\$|доллар[аов]?|"
    r"юан[еия]|£|фунт[аов]?|тенге|тг|сум[аов]?|бел\.?руб\.?)", re.I)

_NUM_CORE = re.compile(r"\d+(?:[" + re.escape(DIGIT_SEPS) + r"]\d{3}(?!\d))*(?:[.,]\d+)?")
_MIXED_GROUPING = re.compile(r"(?<=\d)[" + re.escape(DIGIT_SEPS) + r"]\d{4,}(?!\d)")
_MULT_TAIL = re.compile(r"^[" + re.escape(SEPS) + r"]{0,2}(?P<mult>тысяч[аиуе]?|тыс\.?|"
                        r"миллион[аиове]?|млн\.?|миллиард[аиове]?|млрд\.?)(?=["
                        + re.escape(SEPS) + r"]|\.|;|,|:|\)|\]|$|[^\w])", re.I)
_MULT_DOT = re.compile(r"^\.(?P<mult>тыс|млн|млрд)(?=[" + re.escape(SEPS) + r"]|$|[^\w])")
_CURRENCY_AT = re.compile(r"[" + re.escape(SEPS) + r"]{0,2}(?P<cur>" + CURRENCY_WORDS.pattern + r")")
_PCT_AT = re.compile(r"[" + re.escape(SEPS) + r"]{0,2}(?:%|процентов|процента|проценту|проценте|проценты)")
_YEAR_RE = re.compile(r"^(1[89]\d{2}|2[01]\d{2})$")


class Number:
    __slots__ = ("start", "end", "raw", "value", "unit", "is_pct", "is_year",
                 "grouped", "flags")

    def __init__(self, start, end, raw, value, unit=None, is_pct=False, is_year=False,
                 grouped=False, flags=()):
        self.start, self.end, self.raw = start, end, raw
        self.value, self.unit = value, unit
        self.is_pct, self.is_year, self.grouped = is_pct, is_year, grouped
        self.flags = list(flags)

    def __repr__(self):
        return f"Number({self.raw!r} -> {self.value}{'%' if self.is_pct else ''})"


def _mult_lookup(key: str):
    key = key.lower().rstrip(".")
    if key in MULTS:
        return MULTS[key], key
    for n in range(len(key), 2, -1):
        if key[:n] in MULTS:
            return MULTS[key[:n]], key[:n]
    return None, key


def parse_number_token(core: str):
    """Ядро числа -> (значение, есть_разряды, флаги)."""
    flags = []
    s = core
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", s):
        flags.append("en_grouping")
        s = s.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        flags.append("en_grouping_dot")
        s = s.replace(".", "")
    grouped = any(c in s for c in DIGIT_SEPS)
    s_clean = s.translate(_SEP_DROP)
    if "," in s_clean:
        s_clean = s_clean.replace(",", ".")
        flags.append("decimal_comma")
    try:
        return float(s_clean), grouped, flags
    except ValueError:
        return None, grouped, flags


def mixed_grouping(text: str):
    """«8 150000», «1 23456» — сломанная группировка разрядов."""
    return [(m.start(), m.end(), m.group(0)) for m in _MIXED_GROUPING.finditer(text)]


def extract_numbers(text: str):
    """Числа в (замаскированном под прозу) тексте."""
    out = []
    for m in _NUM_CORE.finditer(text):
        core = m.group(0)
        value, grouped, flags = parse_number_token(core)
        if value is None:
            continue
        end = m.end()
        raw, unit, is_pct = core, None, False
        tm = _MULT_TAIL.match(text, end) or _MULT_DOT.match(text, end)
        if tm:
            mult, key = _mult_lookup(tm.group("mult"))
            if mult:
                value *= mult
                unit = key
                end = tm.end()
                raw = text[m.start():end]
        cm = _CURRENCY_AT.match(text, end)
        if cm:
            cur = cm.group("cur").lower().rstrip(".")
            unit = f"{unit}|{cur}" if unit else cur
            end = cm.end()
            raw = text[m.start():end]
        pm = _PCT_AT.match(text, end)
        if pm:
            is_pct = True
            end = pm.end()
            raw = text[m.start():end]
        digits = core.translate(_SEP_DROP).replace(",", ".")
        is_year = (bool(_YEAR_RE.match(digits.split(".")[0])) and not grouped
                   and not unit and not is_pct
                   and not re.search(_MONTH_ALT, text[max(0, m.start() - 18):m.start()], re.I)
                   and not re.search(_MONTH_ALT, text[end:end + 18], re.I))
        out.append(Number(m.start(), end, raw.strip(), value, unit, is_pct, is_year,
                          grouped, flags))
    return out


_DATE_DOT = re.compile(r"\b(?P<d>\d{1,2})[.](?P<m>\d{1,2})[.](?P<y>\d{2,4})\b")
_DATE_TEXT = re.compile(r"\b(?P<d>\d{1,2})[" + re.escape(SEPS) + r"]*(?P<mon>" + _MONTH_ALT + r")\.?["
                        + re.escape(SEPS) + r"]*(?P<y>\d{4})\b", re.I)
_DATE_TEXT_NOYEAR = re.compile(r"\b(?P<d>\d{1,2})[" + re.escape(SEPS) + r"]*(?P<mon>"
                               + "|".join(MONTHS) + r")\.?\b", re.I)
_WEEKDAY_NEAR = re.compile(r"(понедельник|вторник|среда|четверг|пятница|суббота|воскресенье|воскренье|"
                           r"пн|вт|ср|чт|пт|сб|вс)\b", re.I)


def extract_dates(text: str, asof: date | None = None):
    """[(start, end, date|None, raw, reason)] — date=None, если года в тексте нет."""
    asof = asof or date.today()
    res = []
    for m in _DATE_DOT.finditer(text):
        d, mo, y = int(m.group("d")), int(m.group("m")), int(m.group("y"))
        if y < 100:
            y += 2000 if y < 70 else 1900
        dt, reason = None, None
        if not 1 <= mo <= 12:
            reason = f"месяц {mo} вне 1..12"
        elif not 1 <= d <= 31:
            reason = f"день {d} вне 1..31"
        else:
            try:
                dt = date(y, mo, d)
            except ValueError:
                reason = f"{d}.{mo}.{y} — такого дня нет"
        res.append((m.start(), m.end(), dt, m.group(0), reason))
    for rx, has_year in ((_DATE_TEXT, True), (_DATE_TEXT_NOYEAR, False)):
        for m in rx.finditer(text):
            mon = m.group("mon").lower()
            mo = MONTHS.get(mon) or MONTH_ABBR.get(mon[:3])
            if mo is None:
                continue
            y = int(m.group("y")) if has_year else asof.year
            d = int(m.group("d"))
            dt, reason = None, None
            try:
                dt = date(y, mo, d)
            except ValueError:
                reason = f"{m.group(0)} — такого дня нет"
            if has_year and not 1900 <= y <= 2100:
                reason = reason or f"год {y} неправдоподобен"
            res.append((m.start(), m.end(), dt, m.group(0), reason))
    res.sort(key=lambda r: (r[0], -(r[1] - r[0])))
    dedup = []
    for s, e, dt, raw, reason in res:
        if dedup and s < dedup[-1][1] - 1:   # более короткий вариант внутри уже взятого
            continue
        dedup.append((s, e, dt, raw, reason))
    return dedup


def mask_dates(text: str):
    """Даты -> пробелы (чтобы разбор чисел не принимал «10.11» за 10,11)."""
    spans = [(s, e) for s, e, _, _, _ in extract_dates(text)]
    return mask(text, merge_spans(spans))


def weekday_name(d: date) -> str:
    return WEEKDAY_NAMES[d.weekday()]


# ---------------------------------------------------------------- маскирование

_FENCE = re.compile(r"^(?P<f>```+|~~~+)[^\n]*\n.*?(?:^(?P=f)[ \t]*$|\Z)", re.S | re.M)
_INLINE_CODE = re.compile(r"(?<!`)`[^`\n]+`(?!`)")
_URL = re.compile(r"\b(?:https?|ftp|ws|wss)://[^\s<>\"'`)\]}]+|\bwww\.[^\s<>\"'`)\]}]+", re.I)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_BARE_DOMAIN = re.compile(
    r"\b(?:[\w-]+\.)+(?:ru|рф|com|org|net|io|ai|app|dev|de|fr|it|es|uk|eu|ch|at|pl|fi|cz|nl|"
    r"se|no|dk|be|pt|gr|tr|ae|cn|jp|kr|in|sg|hk|tw|by|kz|ua|su|info|biz|me|co|xyz|online|site|"
    r"tech|store|shop|cloud|host|tv|gg|edu|gov|mil|int|bank|fin|money|news)\b(?::\d{2,5})?"
    r"(?:/[^\s<>\"'`)\]}]*)?", re.I)
_WIN_PATH = re.compile(r"\b[A-Za-z]:[\\/][^\s<>\"'`)*\]}]+")
_EXT = (r"md|markdown|txt|csv|tsv|xlsx?|docx?|pptx?|pdf|json|ya?ml|toml|xml|ini|cfg|conf|log|"
        r"sql|py|php|go|js|ts|tsx|jsx|rs|java|cs|rb|sh|ps1|bat|html?|css|scss|svg|png|jpe?g|"
        r"gif|webp|ico|zip|7z|tar|gz|exe|msi|whl|lock|env")
_REL_PATH = re.compile(r"\b[\w.@-]+(?:[/\\][\w.@-]+)+\.(?:" + _EXT + r")\b", re.I)
_FILE_EXT = re.compile(r"\b[\w.@-]+\.(?:" + _EXT + r")\b", re.I)
_HTML_TAG = re.compile(r"</?[a-zA-Z][\w-]*(?:\s[^<>]*)?/?>")
_MD_LINK_TARGET = re.compile(r"!?\[[^\]\n]*\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
_ANCHOR = re.compile(r"#[\w-]+")
_PHONE = re.compile(r"(?:\+?\d{1,3}[" + re.escape(SEPS) + r"-()]?)?\d{3}[" + re.escape(SEPS)
                    + r"-()]\d{3}[" + re.escape(SEPS) + r"-()]\d{2}(?:[" + re.escape(SEPS)
                    + r"-()]\d{2})?\b")
_ID_NUM = re.compile(r"\b\d{10,12}\b|\b\d{4}\s?\d{3}\s?\d{3}\b|\b\d{3}-\d{3}-\d{3}\b")


def nonprose_spans(text: str):
    """Интервалы не-прозы: код, URL, email, пути, теги, якоря, цели ссылок, телефоны, идентификаторы."""
    spans = []
    for rx in (_FENCE, _INLINE_CODE, _URL, _EMAIL, _WIN_PATH, _REL_PATH, _FILE_EXT,
               _HTML_TAG, _ANCHOR, _PHONE, _ID_NUM):
        for m in rx.finditer(text):
            spans.append((m.start(), m.end()))
    for m in _MD_LINK_TARGET.finditer(text):
        t = m.group("target")
        pos = text.find(t, m.start())
        if pos >= 0:
            spans.append((pos, pos + len(t)))
    for m in _BARE_DOMAIN.finditer(text):
        spans.append((m.start(), m.end()))
    return merge_spans(spans)


def merge_spans(spans):
    if not spans:
        return []
    spans = sorted(spans)
    out = [list(spans[0])]
    for s, e in spans[1:]:
        if s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [tuple(x) for x in out]


def mask(text: str, spans):
    """Замена интервалов пробелами: длина и переводы строк сохраняются."""
    if not spans:
        return text
    buf = list(text)
    for s, e in spans:
        for i in range(s, min(e, len(buf))):
            if buf[i] != "\n":
                buf[i] = " "
    return "".join(buf)


def mask_nonprose(text: str):
    spans = nonprose_spans(text)
    return mask(text, spans), spans


# ---------------------------------------------------------------- предложения

_ABBREV = re.compile(
    r"\b(?:г|gg|ул|пер|пр|ш|б-р|просп|р-н|обл|д|к|стр|с|т|ч|пп|п|ст|см|напр|разд|гл|рис|"
    r"таб|прил|prim|note|etc|vs|id|№|N|осн|мин|сек|тыс|млн|млрд|руб|шт|экз|чел|инв|до|после|"
    r"т\. ?е|и т\. ?д|и т\. ?п|итд|итп|др|проч)\.", re.I)
_INITIALS = re.compile(r"\b[А-ЯЁA-Z]\.")
_DECIMAL_DOT = re.compile(r"(?<=\d)\.(?=\d{1,2}\b)")
_DOTS = re.compile(r"(?<=[.!?…])[" + re.escape(SEPS) + r"]+")


def _protect(text: str) -> str:
    """Точки, не заканчивающие предложение, -> «․» (та же длина, не конец фразы)."""
    buf = list(text)
    for rx in (_ABBREV, _INITIALS, _DECIMAL_DOT):
        for m in rx.finditer(text):
            i = m.end() - 1
            if buf[i] == ".":
                buf[i] = "\u2024"
    return "".join(buf)


def split_sentences(prose: str):
    """[(start, end, sentence)]; смещения совпадают с оригиналом."""
    prot = _protect(prose)
    out = []
    start = 0
    for m in _DOTS.finditer(prot):
        prev = prot[m.start() - 1] if m.start() else ""
        if prev in ".!?…":
            chunk = prose[start:m.start()]
            seg = chunk.strip()
            if seg:
                s = start + chunk.find(seg)
                out.append((s, s + len(seg), seg))
            start = m.end()
    chunk = prose[start:]
    seg = chunk.strip()
    if seg:
        s = start + chunk.find(seg)
        out.append((s, s + len(seg), seg))
    return out


def word_count(text: str) -> int:
    return len(re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", text))


def line_starts(text: str):
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def line_of(pos: int, starts) -> int:
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= pos:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1


# ---------------------------------------------------------------- markdown

def code_fence_lines(text: str):
    """Номера строк внутри fenced-блоков, включая маркеры."""
    lines = text.split("\n")
    in_code = False
    ch = None
    width = 0
    out = set()
    for i, ln in enumerate(lines, 1):
        m = re.match(r"^\s*(`{3,}|~{3,})", ln)
        if not in_code and m:
            in_code, ch, width = True, m.group(1)[0], len(m.group(1))
            out.add(i)
        elif in_code and m and m.group(1)[0] == ch and len(m.group(1)) >= width:
            in_code = False
            out.add(i)
        elif in_code:
            out.add(i)
    return out


def parse_tables(text: str):
    """Markdown-таблицы: start_line/end_line/header/rows/sep_index."""
    lines = text.split("\n")
    tables = []
    i = 0
    while i < len(lines):
        if ("|" in lines[i] and i + 1 < len(lines)
                and re.match(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", lines[i + 1])
                and lines[i].strip().count("|") >= 2):
            header = split_row(lines[i])
            sep = i + 1
            rows = []
            j = sep + 1
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                rows.append(split_row(lines[j]))
                j += 1
            tables.append({"start_line": i + 1, "end_line": j, "header": header,
                           "sep": lines[sep], "rows": rows, "sep_index": sep + 1})
            i = j
        else:
            i += 1
    return tables


def split_row(line: str):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


_CAPS_LABEL = re.compile(r"^(?P<label>[A-ZА-ЯЁ][A-ZА-ЯЁ0-9 _/+. -]{1,29})\s*(?:—|--)\s+\S")


def headings(text: str):
    """[(level, line_no, title, slug)] вне кодовых блоков.

    Помимо markdown-заголовков распознаёт псевдозаголовки вида
    «LABEL — описание» (сплошные капсы), которые часто используются в
    инструкциях и конфигах.
    """
    fence = code_fence_lines(text)
    out = []
    for i, ln in enumerate(text.split("\n"), 1):
        if i in fence:
            continue
        m = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", ln)
        if m:
            out.append((len(m.group(1)), i, m.group(2).strip(), slugify(m.group(2))))
            continue
        stripped = ln.strip()
        if stripped.startswith(("-", "*", "|", ">", "#", "`")):
            continue
        cm = _CAPS_LABEL.match(stripped)
        if cm:
            out.append((2, i, cm.group("label").strip(), slugify(cm.group("label"))))
    return out


def slugify(title: str) -> str:
    t = title.lower().strip()
    t = re.sub(r"[^\w\s-]", "", t, flags=re.U)
    return re.sub(r"[\s_]+", "-", t, flags=re.U)


def quote_spans(text: str):
    """Интервалы цитат: «...», „...“, "...". Внутри них документ приводит
    примеры чужой речи, а не говорит сам — редакционные «остатки» там не находки."""
    spans = []
    for rx in (r"«[^»]*»", r"„[^“]*“", r"\"[^\"\n]*\""):
        for m in re.finditer(rx, text):
            spans.append((m.start(), m.end()))
    return merge_spans(spans)


def paragraphs(text: str):
    """[(start, end, block)] — блоки, отделённые пустой строкой (по замаскированному тексту)."""
    masked = mask_nonprose(text)[0]
    out = []
    for m in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", masked):
        s, e = m.start(), m.end()
        block = text[s:e]
        if block.strip():
            out.append((s, e, block))
    return out


def days_between(a, b) -> int:
    return abs((b - a).days)


def months_between(a, b) -> float:
    return abs((b.year - a.year) * 12 + (b.month - a.month) + (b.day - a.day) / 30.44)


def years_between(a, b) -> float:
    return abs((b - a).days) / 365.2425


def fmt(value: float) -> str:
    """Число в русской записи разрядов."""
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}".replace(",", "\u00a0")
    return f"{value:,.2f}".replace(",", "\u00a0").replace(".", ",")
