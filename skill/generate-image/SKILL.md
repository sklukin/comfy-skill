---
name: generate_image
description: Generate images from text descriptions using FLUX.1 AI model on local RTX 4090
user-invocable: true
metadata: {"openclaw": {"emoji": "🎨", "requires": {"bins": ["curl"]}, "primaryEnv": "IMAGES_API_URL"}}
---

# Генерация изображений

Генерируй изображения по текстовому описанию через FLUX.1 AI на локальной RTX 4090. Автоматический фолбэк в облако при перегрузке GPU.

## Переменные окружения

- `IMAGES_API_URL` — базовый URL сервиса генерации (например `http://192.168.1.41:8189`)

## Доступные модели

| Модель | Параметр | Время | Назначение |
|--------|----------|-------|------------|
| FLUX.1 Dev | `flux-dev` | 9-16с | Основная: фотореализм, текст, анатомия |
| FLUX.1 Schnell | `flux-schnell` | <1с | Быстрое прототипирование |
| SDXL | `sdxl` | 6-13с | Стилизация, огромная экосистема LoRA |

## Процесс

### 1. Проверь доступность API

```bash
curl -sf "${IMAGES_API_URL}/health"
```

Если API недоступен или `comfyui_connected` = false, сообщи пользователю что сервис генерации сейчас недоступен.

### 2. Генерация изображения

```bash
curl -s -o /tmp/generated.png -w "%{http_code}" \
  -X POST "${IMAGES_API_URL}/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "описание изображения",
    "model": "flux-dev",
    "width": 1024,
    "height": 1024,
    "steps": 20,
    "guidance_scale": 3.5,
    "seed": -1
  }' \
  --max-time 300
```

Параметры:
- `prompt` (обязательный) — текстовое описание изображения
- `model` — `flux-dev` (по умолчанию), `flux-schnell`, `sdxl`
- `width`, `height` — размер 256-2048 (по умолчанию 1024x1024)
- `steps` — шаги генерации (flux-dev: 20, flux-schnell: 4, sdxl: 25)
- `guidance_scale` — сила следования промпту (flux-dev: 3.5, sdxl: 7.0)
- `seed` — сид для воспроизводимости (-1 = случайный)
- `negative_prompt` — что исключить (только для SDXL, FLUX игнорирует)

Ответ содержит PNG файл. Метаданные в заголовках: `X-Source`, `X-Seed`, `X-Model`.

### 3. Обработка ошибок

Если HTTP код = 503 (GPU занят или ComfyUI недоступен), подожди 15 секунд и повтори. Максимум 3 попытки:

```bash
for i in 1 2 3; do
  HTTP_CODE=$(curl -s -o /tmp/generated.png -w "%{http_code}" \
    -X POST "${IMAGES_API_URL}/generate" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "описание", "model": "flux-dev"}' \
    --max-time 300)
  if [ "$HTTP_CODE" = "200" ]; then break; fi
  if [ "$HTTP_CODE" = "503" ]; then
    echo "GPU занят, жду 15 секунд... (попытка $i/3)"
    sleep 15
    continue
  fi
  echo "Ошибка: HTTP $HTTP_CODE"
  break
done
```

### 4. Image-to-Image (редактирование)

Для модификации существующего изображения используй отдельный endpoint:

```bash
curl -s -o /tmp/edited.png -w "%{http_code}" \
  -X POST "${IMAGES_API_URL}/generate/img2img" \
  -F "image=@/path/to/photo.png" \
  -F "prompt=опиши желаемые изменения" \
  -F "model=flux-dev" \
  -F "denoise=0.65" \
  --max-time 300
```

Параметр `denoise` (0.0-1.0) контролирует степень изменений:
- 0.3-0.5 — лёгкие правки (цвет, стиль)
- 0.5-0.7 — умеренные изменения (добавить/убрать элементы)
- 0.7-0.9 — сильные изменения (почти полная перегенерация)

### 5. Быстрая генерация

Для быстрых превью или прототипирования используй `flux-schnell` (менее 1 секунды):

```bash
curl -s -o /tmp/preview.png \
  -X POST "${IMAGES_API_URL}/generate" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "описание", "model": "flux-schnell", "steps": 4}'
```

### 6. Проверка доступных моделей

```bash
curl -sf "${IMAGES_API_URL}/models"
```

Возвращает JSON со списком установленных чекпоинтов и LoRA.

### 7. Верни результат

- Проверь что файл создан и не пустой: `test -s /tmp/generated.png`
- Сообщи пользователю что изображение готово и отправь его
- Если пользователь просит несколько изображений — генерируй последовательно

## Заметки

- FLUX.1 Dev даёт лучшее качество текста на изображениях и анатомию (особенно руки)
- Для FLUX моделей `negative_prompt` не используется — управление только через `prompt` и `guidance_scale`
- Для SDXL `negative_prompt` работает и важен для качества
- Сервис автоматически переключается на облачную генерацию (fal.ai) при перегрузке локального GPU
- Нельзя запускать одновременно с 3D-генерацией (TRELLIS.2) под нагрузкой — GPU один
