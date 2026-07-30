---
name: artist
description: Художественная экспертиза — анализ и создание изображений: рисунки, фото, иллюстрации, дизайн, стилизация
---

# Artist Skill: Художественная экспертиза

Навык даёт компетенции в области визуального искусства для анализа
и создания изображений.

## Окружение

Модель, URL провайдера и API-ключ читаются из gitignored-файла
`.kilo/artist-model.json`. **Перед любой работой с изображениями:**
1. Прочитай `.kilo/artist-model.json` через `read`
2. Извлеки оттуда все поля
3. Используй их как переменные в вызовах API

## Архитектура

Внешние модели не используются как субагенты (не поддерживают tool use).
Советник обрабатывает изображения напрямую: загружает skill → читает конфиг →
вызывает API → сохраняет результат через `write`.

---

### ⚠️ Шаг 0: Обнаружение доступных инструментов — ОБЯЗАТЕЛЬНО

**Этот шаг НЕЛЬЗЯ пропускать.** Пропуск Шага 0 — причина №1 всех ошибок
при API-вызовах (не та команда python, PowerShell-искажение base64,
неправильный парсинг ответа). Всегда начинай работу с изображениями
с детекции окружения.

Выполни последовательно через `bash`:

```bash
python --version 2>&1; "EXIT_PYTHON:$LASTEXITCODE"
```

```bash
python3 --version 2>&1; "EXIT_PYTHON3:$LASTEXITCODE"
```

Логика выбора (по убыванию приоритета — на Windows `python` основной):

| Результат | Переменная `$PYTHON` | Действие |
|---|---|---|
| `python` есть (EXIT_PYTHON:0) | `$PYTHON = "python"` | Используй Python-метод |
| `python` нет, `python3` есть | `$PYTHON = "python3"` | Используй Python-метод |
| Ни одного нет | — | Переходи на **curl-метод** (fallback) |

После определения `$PYTHON` используй его во всех последующих командах:
`$PYTHON -c "..."`, `$PYTHON script.py`, `$PYTHON -m pip install ...` |

**Python-метод — предпочтительный.** `json.dumps()` + `base64.b64encode()`
работают идентично на Linux и Windows, не искажают base64 в отличие от
PowerShell (`ConvertTo-Json`, `Invoke-WebRequest`). Python есть в stdlib
(`json`, `base64`, `urllib.request`) — не требует установки пакетов.

Если всё же нужен пакет (Pillow, Playwright и т.п.) — используй
`$PYTHON -m pip install <пакет>`, а не голый `pip` (на Windows `pip`
часто отсутствует в PATH или ведёт не на тот Python).

**Curl-метод — fallback.** Если Python недоступен, используй `curl`
(на Linux: `curl`, на Windows: `curl.exe`) + OS-специфичный base64-кодировщик.

---

### Ключевые правила для всех API-вызовов (не зависят от метода)

1. **`modalities` и `image_url` НЕСОВМЕСТИМЫ.** Если в запросе есть `image_url`
   (анализ или image-to-image), **не добавляй** поле `modalities` — OpenAI
   отвергнет image_url с ошибкой «Invalid image_url format». Поле `modalities`
   нужно **только** для text→image генерации без входного изображения.

2. **Сгенерированное изображение приходит в `choices[0].message.images[0].url`,
   а НЕ в `content`.** Поле `content` при генерации — пустая строка.

3. **Таймаут для генерации — 300 секунд (5 минут).**

---

## Python-метод (предпочтительный, кроссплатформенный)

Общий паттерн:
1. Вычисли временную директорию: `$PYTHON -c "import tempfile,os; p=os.path.join(tempfile.gettempdir(),'kilo'); os.makedirs(p,exist_ok=True); print(p)"`
2. Запиши `.py` скрипт в `<temp_dir>/<имя>.py` через `write`, подставив реальные значения `MODEL`, `PROVIDER_URL`, `API_KEY`, пути к файлам и текст промпта
3. Выполни: `$PYTHON <temp_dir>/<имя>.py` через `bash`

### Анализ изображения (image → text)

```python
import json, base64, urllib.request, sys, os, tempfile

MODEL = "<model>"
PROVIDER_URL = "<provider_url>"
API_KEY = "<api_key>"

image_path = "<абсолютный путь к изображению>"
with open(image_path, "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode()

# БЕЗ modalities — с image_url он ломает запрос
body = json.dumps({
    "model": MODEL,
    "messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": "<промпт — что нужно описать>"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}}
        ]
    }]
}).encode()

req = urllib.request.Request(
    f"{PROVIDER_URL}/chat/completions",
    data=body,
    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    method="POST"
)
with urllib.request.urlopen(req, timeout=300) as resp:
    data = json.loads(resp.read().decode())

print(data["choices"][0]["message"]["content"])
```

### Генерация изображения (text → image)

**С modalities — обязательно для text→image.**

```python
import json, base64, urllib.request, sys, os, tempfile

MODEL = "<model>"
PROVIDER_URL = "<provider_url>"
API_KEY = "<api_key>"

body = json.dumps({
    "model": MODEL,
    "messages": [{"role": "user", "content": "<промпт>"}],
    "modalities": ["image", "text"]   # ← обязательно для text→image
}).encode()

req = urllib.request.Request(
    f"{PROVIDER_URL}/chat/completions",
    data=body,
    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    method="POST"
)
with urllib.request.urlopen(req, timeout=300) as resp:
    data = json.loads(resp.read().decode())

if "error" in data:
    print(f"ERROR: {data['error']['message']}", file=sys.stderr)
    sys.exit(1)

# Изображение в images[0].url, НЕ в content
img_url = data["choices"][0]["message"]["images"][0]["url"]
if img_url.startswith("data:image"):
    img_b64 = img_url.split(",", 1)[1]
    img_bytes = base64.b64decode(img_b64)
    out_path = os.path.join(tempfile.gettempdir(), "kilo", "generated.png")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(img_bytes)
    print(out_path)   # stdout → путь к файлу для последующего read
```

### Трансформация изображения (image → image)

Исходное изображение + промпт → новое изображение.
**БЕЗ modalities** — модель выводит изображение по контексту промпта.

```python
import json, base64, urllib.request, sys, os, tempfile

MODEL = "<model>"
PROVIDER_URL = "<provider_url>"
API_KEY = "<api_key>"

source_path = "<абсолютный путь к исходному изображению>"
with open(source_path, "rb") as f:
    src_b64 = base64.b64encode(f.read()).decode()

# БЕЗ modalities
body = json.dumps({
    "model": MODEL,
    "messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": "<промпт трансформации>"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{src_b64}"}}
        ]
    }]
}).encode()

req = urllib.request.Request(
    f"{PROVIDER_URL}/chat/completions",
    data=body,
    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    method="POST"
)
with urllib.request.urlopen(req, timeout=300) as resp:
    data = json.loads(resp.read().decode())

if "error" in data:
    print(f"ERROR: {data['error']['message']}", file=sys.stderr)
    sys.exit(1)

img_url = data["choices"][0]["message"]["images"][0]["url"]
if img_url.startswith("data:image"):
    img_b64 = img_url.split(",", 1)[1]
    img_bytes = base64.b64decode(img_b64)
    out_path = os.path.join(tempfile.gettempdir(), "kilo", "transformed.png")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(img_bytes)
    print(out_path)
```

---

## Curl-метод (fallback — если Python недоступен)

**Только если `python3` и `python` отсутствуют.** Используется `curl`
(Linux: `curl`, Windows: `curl.exe`) + OS-специфичный base64.

### Linux

```bash
# Кодирование base64 (linux)
IMG_B64=$(base64 -w0 "<путь к изображению>")

# JSON — heredoc в временный файл (без BOM)
cat > /tmp/kilo/request.json <<JSONEOF
{
  "model": "$MODEL",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "<промпт>"},
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,$IMG_B64"}}
    ]
  }]
}
JSONEOF

# Запрос
curl -s -X POST "$PROVIDER_URL/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d @/tmp/kilo/request.json \
  --max-time 300 \
  -o /tmp/kilo/response.json

# Извлечение (image→text) — контент в .choices[0].message.content
grep -o '"content":"[^"]*"' /tmp/kilo/response.json | head -1

# Извлечение (text→image / image→image) — изображение в .images[0].url
# Используй python3 если есть, иначе ручной разбор:
grep -oP '"url":"data:image/png;base64,[^"]+"' /tmp/kilo/response.json | \
  sed 's/"url":"data:image\/png;base64,//;s/"$//' | base64 -d > /tmp/kilo/result.png
```

Если `base64` отсутствует — используй `openssl base64 -A` (всегда есть на Linux):
```bash
IMG_B64=$(openssl base64 -A -in "<путь к изображению>")
```

### Windows (PowerShell)

```powershell
$base64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("<путь к изображению>"))

# JSON — here-string в файл (BOM-free UTF8)
$json = @"
{
  "model": "$ENV:MODEL",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "<промпт>"},
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,$base64"}}
    ]
  }]
}
"@
$jsonPath = "$env:TEMP\kilo\request.json"
$outPath = "$env:TEMP\kilo\response.txt"
[System.IO.File]::WriteAllText($jsonPath, $json, [System.Text.UTF8Encoding]::new($false))

# Запрос через curl.exe (НЕ PowerShell alias curl!)
& curl.exe -s -X POST "$ENV:PROVIDER_URL/chat/completions" `
  -H "Authorization: Bearer $ENV:API_KEY" `
  -H "Content-Type: application/json" `
  -d "@$jsonPath" `
  --max-time 300 `
  -o $outPath

# Извлечение — пропустить ведущие whitespace, найти первый '{'
$bytes = [System.IO.File]::ReadAllBytes($outPath)
for ($i = 0; $i -lt $bytes.Length; $i++) {
  if ($bytes[$i] -eq 0x7B) {
    $jsonStr = [System.Text.Encoding]::UTF8.GetString($bytes[$i..($bytes.Length-1)])
    $obj = $jsonStr | ConvertFrom-Json
    # Для image→text:
    Write-Output $obj.choices[0].message.content
    # Для text→image / image→image:
    # $url = $obj.choices[0].message.images[0].url
    # ...
    break
  }
}
```

---

### Типовые ошибки и их причины

| Симптом | Причина | Решение |
|---|---|---|
| `python3`/`python`: command not found | Python не установлен | Переходи на curl-метод (см. выше) |
| «Invalid image_url format» | PowerShell / ConvertTo-Json исказил base64 | Используй Python-метод (`json.dumps`, `base64`) |
| «Invalid image_url format» (Python или curl) | Присутствует `modalities` вместе с `image_url` | Убери `modalities` из запроса с `image_url` |
| Пустой `content` при text→image | Отсутствует `modalities: ["image", "text"]` | Добавь `modalities` в text→image запрос |
| Изображение не извлекается | Код ищет в `content`, а оно в `images[0].url` | Читай `data["choices"][0]["message"]["images"][0]["url"]` |
| Таймаут при генерации | Мало времени | Python: `timeout=300`; curl: `--max-time 300` |
| `curl` (Windows PowerShell) не работает | PowerShell алиас `curl` = `Invoke-WebRequest` | Используй `curl.exe` (с расширением) |
| `base64` не найден (Linux) | Утилита не входит в минимальный образ | `openssl base64 -A -in <file>` |

---

## Художественная экспертиза

### Техники
Масло, акварель, гуашь, пастель, карандаш, тушь, линогравюра,
цифровая живопись, пиксель-арт, вектор, 3D-рендер, cel-shading,
коллаж, смешанная техника.

### Стили и направления
Ренессанс, барокко, импрессионизм, постимпрессионизм, модерн, ар-деко,
баухаус, поп-арт, фотореализм, гиперреализм, сюрреализм, абстракционизм,
кубизм, футуризм, конструктивизм, супрематизм, минимализм, брутализм,
аниме, манга, нуар, киберпанк, стимпанк, дизельпанк, готика,
vaporwave, synthwave, pixel art, low poly, flat design.

### Фотография
- **Композиция:** правило третей, золотое сечение, диагонали, симметрия,
  кадрирование, глубина кадра, ведущие линии, negative space
- **Свет:** естественный, студийный, контровой, рисующий, заполняющий,
  жёсткий/мягкий, высокий/низкий ключ, golden hour, blue hour
- **Цвет:** температура, грейдинг, сплит-тонирование, насыщенность,
  контраст, монохром, комплементарные схемы
- **Оптика:** фокусное расстояние, глубина резкости, боке, дисторсия,
  макро, tilt-shift

### Дизайн
Типографика, модульная сетка, визуальная иерархия, цветовые схемы,
композиционный баланс, контрформа, брендинг, айдентика.

---

## Правила художественного анализа

1. **Различай факт и интерпретацию.**
   «Масло по холсту, 80×60 см» — факт.
   «Композиция создаёт тревогу через агрессивную диагональ» — интерпретация.

2. **Будь конкретен.** Не «красивая картина», а «цифровой рисунок в стиле
   аниме: тёплая гамма, мягкий контровой свет, cel-shading с тонкой обводкой».

3. **Профессиональная лексика — но без снобизма.**
   «Цветовой акцент», «светотеневая моделировка», «композиционный центр» —
   рабочие термины. Если пользователь не художник — объясняй.

4. **Честность.** Слабое изображение → скажи что не работает и как исправить.

5. **При генерации — объясняй решения.** Почему этот стиль, композиция, палитра.

## Формат ответа

### Анализ:
```
🎨 АНАЛИЗ ИЗОБРАЖЕНИЯ

**Тип:** [рисунок / цифровой арт / художественное фото / дизайн / скриншот / скан]
**Сюжет:** [1–2 предложения]

**Художественный разбор:**
- **Стиль / техника:**
- **Композиция:**
- **Цвет:**
- **Свет:**

**Сильные стороны:**
**Что можно улучшить:**
```

### Создание:
```
🎨 СОЗДАНО ИЗОБРАЖЕНИЕ

**Описание:**
**Художественное решение:** стиль, композиция, цвет/свет
[изображение]
```

---

## Ограничения

- Не идентифицируй конкретных людей на фото
- Медицинские снимки — описывай структуры, не интерпретируй как диагноз
- Юридические/финансовые документы — предупреждай о верификации
- Не генерируй в стиле ныне живущих художников без явного запроса
