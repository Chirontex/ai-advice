---
name: ocr
description: Распознавание изображений и документов — OCR сканов, чтение рукописного текста, извлечение текста из фото, таблиц и PDF
---

# OCR Skill: Распознавание изображений и документов

Навык даёт компетенции по распознаванию текста из изображений:
сканы документов, фотографии страниц, рукописный текст, таблицы,
чеки, PDF-страницы — с точным извлечением текста (image → text).

Отличается от скилла `artist`: там — генерация и художественный анализ,
здесь — **точное чтение текста** с сохранением структуры документа.

## Окружение

Модель, URL провайдера, API-ключ и стиль API читаются из gitignored-файла
`.kilo/ocr-model.json`. **Перед любой работой с распознаванием:**
1. Прочитай `.kilo/ocr-model.json` через `read`
2. Извлеки оттуда все поля
3. Используй их как переменные в вызовах API

Поле `api_style` зарезервировано для совместимости со скиллом `artist`:
для OCR оно всегда `"chat"` — распознавание идёт через OpenAI-совместимый
chat completions с `image_url`. Media API для распознавания не нужен.

## Архитектура

Внешние vision-модели не используются как субагенты (не поддерживают tool use).
Советник обрабатывает изображения напрямую: загружает skill → читает конфиг →
вызывает API → возвращает распознанный текст в ответе (или сохраняет
результат через `write`, если пользователь просит сохранить).

---

### ⚠️ Шаг 0: Обнаружение доступных инструментов — ОБЯЗАТЕЛЬНО

**Этот шаг НЕЛЬЗЯ пропускать.** Пропуск Шага 0 — причина №1 всех ошибок
при API-вызовах (не та команда python, PowerShell-искажение base64,
неправильный парсинг ответа). Всегда начинай работу с распознаванием
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
`$PYTHON -c "..."`, `$PYTHON script.py`, `$PYTHON -m pip install ...`

**Python-метод — предпочтительный.** `json.dumps()` + `base64.b64encode()`
работают идентично на Linux и Windows, не искажают base64 в отличие от
PowerShell (`ConvertTo-Json`, `Invoke-WebRequest`). Python есть в stdlib
(`json`, `base64`, `urllib.request`) — не требует установки пакетов.

Если всё же нужен пакет (Pillow, PyMuPDF и т.п.) — используй
`$PYTHON -m pip install <пакет>`, а не голый `pip` (на Windows `pip`
часто отсутствует в PATH или ведёт не на тот Python).

**Curl-метод — fallback.** Если Python недоступен, используй `curl`
(на Linux: `curl`, на Windows: `curl.exe`) + OS-специфичный base64-кодировщик.

---

### Ключевые правила для всех API-вызовов (не зависят от метода)

1. **Распознавание — это image → text. Всегда есть `image_url`.**
   По этой причине **НЕ добавляй поле `modalities`** — OpenAI-совместимые
   провайдеры отвергают image_url с `modalities` («Invalid image_url format»).
   `modalities` нужен только для text→image генерации — в этом скилле он не нужен никогда.

2. **Распознанный текст приходит в `choices[0].message.content`**
   (строка). В отличие от генерации — никаких `images[0].url`.

3. **Файлы перед отправкой кодируются в base64**
   и передаются как `data:image/<format>;base64,<b64>`
   (PNG → `data:image/png;base64,...`, JPEG → `data:image/jpeg;base64,...`).

4. **PDF. Если файл — PDF (не изображение):**
   сначала конвертируй страницы в PNG через PyMuPDF
   (`$PYTHON -m pip install pymupdf`), затем распознавай каждую страницу
   отдельным запросом. Одной страницей за раз — точность выше.

5. **Таймаут для распознавания — 300 секунд (5 минут).**
   Сканы высокого разрешения и многостраничные документы обрабатываются
   долго — закладывай запас.

6. **Контракт вызова.** Распознавание — всегда image → text через
   chat completions с `image_url`; никаких Media API и `modalities`.
   Подходит любой OpenAI-совместимый шлюз из конфига.

---

## Python-метод (предпочтительный, кроссплатформенный)

Общий паттерн:
1. Вычисли временную директорию: `$PYTHON -c "import tempfile,os; p=os.path.join(tempfile.gettempdir(),'kilo'); os.makedirs(p,exist_ok=True); print(p)"`
2. Запиши `.py` скрипт в `<temp_dir>/<имя>.py` через `write`, подставив реальные значения `MODEL`, `PROVIDER_URL`, `API_KEY`, пути к файлам и текст промпта
3. Выполни: `$PYTHON <temp_dir>/<имя>.py` через `bash`

### Распознавание одного изображения (image → text)

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
            {"type": "text", "text": "<промпт — что нужно распознать>"},
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

if "error" in data:
    print(f"ERROR: {data['error']['message']}", file=sys.stderr)
    sys.exit(1)

print(data["choices"][0]["message"]["content"])
```

### Формат изображения в image_url

Подбирай MIME по расширению файла:

```python
ext = os.path.splitext(image_path)[1].lower()
mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}
mime = mime_map.get(ext, "image/png")
# ... в image_url: f"data:{mime};base64,{img_b64}"
```

---

## Curl-метод (fallback — если Python недоступен)

**Только если `python3` и `python` отсутствуют.** Используется `curl`
(Linux: `curl`, Windows: `curl.exe`) + OS-специфичный base64.

### Linux

```bash
# Кодирование base64 (linux)
IMG_B64=$(base64 -w0 "<путь к изображению>")
# если base64 отсутствует:
# IMG_B64=$(openssl base64 -A -in "<путь к изображению>")

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

curl -s -X POST "$PROVIDER_URL/chat/completions" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d @/tmp/kilo/request.json \
  --max-time 300 \
  -o /tmp/kilo/response.json

# Распознанный текст — в .choices[0].message.content
grep -o '"content":"[^"]*"' /tmp/kilo/response.json | head -1
```

### Windows (PowerShell)

```powershell
$base64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("<путь к изображению>"))

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

& curl.exe -s -X POST "$ENV:PROVIDER_URL/chat/completions" `
  -H "Authorization: Bearer $ENV:API_KEY" `
  -H "Content-Type: application/json" `
  -d "@$jsonPath" `
  --max-time 300 `
  -o $outPath

$bytes = [System.IO.File]::ReadAllBytes($outPath)
for ($i = 0; $i -lt $bytes.Length; $i++) {
  if ($bytes[$i] -eq 0x7B) {
    $jsonStr = [System.Text.Encoding]::UTF8.GetString($bytes[$i..($bytes.Length-1)])
    $obj = $jsonStr | ConvertFrom-Json
    Write-Output $obj.choices[0].message.content
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
| «Invalid image_url format» (Python или curl) | Присутствует `modalities` вместе с `image_url` | Убери `modalities` — в OCR-скилле он не нужен никогда |
| Распознанный текст пустой / `content` отсутствует | Модель вернула ошибку или пустую строку | Проверь `data["error"]`, затем громкость/качество изображения |
| Распознавание «мусорит» (цифры/буквы перепутаны) | Низкое разрешение или мусор на скане | Увеличь изображение (Pillow), убедись что это не фото под углом |
| Таймаут при распознавании | Слишком большое изображение | Уменьши (max сторона ~2000px через Pillow), таймаут 300 |
| `curl` (Windows PowerShell) не работает | PowerShell алиас `curl` = `Invoke-WebRequest` | Используй `curl.exe` (с расширением) |
| `base64` не найден (Linux) | Утилита не входит в минимальный образ | `openssl base64 -A -in <file>` |

---

## Правила распознавания

1. **Точность важнее скорости.** Переписывай текст так, как он написан:
   орфография, пунктуация, регистр, переносы строк — без «исправлений».
   Единственное исключение — явно проси пользователя о нормализации
   (тогда приводи к стандарту и отмечай это).

2. **Различай распознанное и интерпретированное.**
   «Петров И.И., 14.11.1992» — распознано. «Судя по формату, это
   паспортные данные» — интерпретация. Сначала дай чистый текст,
   потом, если нужно, аналитику отдельным блоком.

3. **Не читай нечитаемое.** Если фрагмент размыт, перекрыт печатью или
   неразборчив — честно пометь `[неразборчиво]` вместо угадывания.

4. **Рукописный текст** — распознавай буквально, включая ошибки автора.
   Не «домысливай» слова по контексту, если почерк неоднозначен.
   При сомнении дай варианты: «[вероятно: "приобретение", возможно "приобритение"]».

5. **Таблицы и структуры** сохраняй: Markdown-таблицы, списки, нумерацию.
   Не превращай таблицу в прозу и наоборот.

6. **Язык.** Распознавай на том языке, которым написан документ.
   Переводи только если пользователь явно попросил.

7. **Конфиденциальность.** При распознавании персональных документов
   (паспорта, договоры, медкарты) не выводи полные конфиденциальные
   данные без необходимости — спрашивай, что именно нужно извлечь.

## Формат ответа

### Распознавание (стандарт):
```
🔍 РАСПОЗНАНО

**Тип документа:** [скан / фото / рукописный / таблица / PDF-страница]
**Язык(и):** [например: русский]

**Текст:**
[распознанный текст или структурированное извлечение]

**Неразборчивые фрагменты:**
- [местоположение]: почему не читается, что мешает (размытие, печать, почерк)

**Если просили извлечение данных:**
- Поле: значение
```

### Извлечение данных (структурированное, по запросу пользователя):
Когда пользователь просит «вытащи дату/сумму/номер», отвечай таблицей
или списком полей, а не пересказом.

---

## Ограничения

- Качество OCR зависит от разрешения и чистоты скана: размытие,
  сильный перекос, блики, плотный рукописный текст могут давать ошибки —
  сообщай о сниженной уверенности
- Не идентифицируй конкретных людей по фото — только текст
- Медицинские документы — распознавай текст, но НЕ интерпретируй
  как диагноз (это к MEDICAL-субагенту)
- Юридические/финансовые документы — распознанный текст не является
  юридическим заключением; предупреждай о необходимости верификации
  документа специалистом
- Очень старые или повреждённые документы могут не распознаваться —
  предложи более качественный скан