# OpenClaw Images — AI Image Generation

Сервис генерации изображений для OpenClaw. Локальная генерация на RTX 4090 через ComfyUI + облачный фолбэк.

## Стек

- **ComfyUI** — headless GPU worker (FLUX.1 Dev FP8, 9-16с на картинку 1024x1024)
- **REST API** — FastAPI, принимает запросы на генерацию, маршрутизирует между локальным GPU и облаком
- **OpenClaw Skill** — `skill/generate-image/` — учит агента генерировать изображения через API
- **Cloud Fallback** — fal.ai (SFW) / RunPod (NSFW) при перегрузке GPU

## Требования

- NVIDIA GPU с 24GB VRAM (RTX 4090)
- Docker + NVIDIA Container Toolkit
- ~30GB для моделей

## Быстрый старт

```bash
# 1. Скачать модели (~30GB, пропускает уже скачанные)
make download-models

# 2. Собрать и запустить
make build
make up

# 3. Проверить
make health
```

## Сервисы

| Сервис | Порт | Описание |
|--------|------|----------|
| ComfyUI | 8188 | GPU inference worker |
| Images API | 8189 | REST API для генерации |

## API Endpoints

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/health` | Статус сервиса, GPU, очередь |
| `POST` | `/generate` | Text-to-image (JSON body) |
| `POST` | `/generate/img2img` | Image-to-image (multipart form) |
| `GET` | `/models` | Список установленных моделей |

### Пример генерации

```bash
curl -s -o image.png \
  -X POST http://localhost:8189/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a cat astronaut, photorealistic", "model": "flux-dev"}'
```

## Модели

| Модель | VRAM | Время | Назначение |
|--------|------|-------|------------|
| FLUX.1 Dev FP8 | ~12GB | 9-16с | Основная: фотореализм, текст, анатомия |
| FLUX.1 Schnell FP8 | ~12GB | <1с | Быстрое прототипирование |
| SDXL | ~6-8GB | 6-13с | Стилизация, огромная экосистема LoRA |

Файлы хранятся в `models/` (volume-mount, не в Docker image).

## Конфигурация

```bash
cp .env.example .env
```

| Переменная | Описание |
|-----------|----------|
| `FAL_KEY` | API-ключ fal.ai для облачного фолбэка |
| `RUNPOD_API_KEY` | API-ключ RunPod (NSFW фолбэк) |
| `MAX_QUEUE_DEPTH` | Макс. очередь ComfyUI до переключения на облако (default: 3) |
| `HF_TOKEN` | Токен HuggingFace (для gated моделей) |
| `IMAGES_API_URL` | URL API для OpenClaw skill (default: http://localhost:8189) |

## OpenClaw Skill

Skill в `skill/generate-image/SKILL.md` учит OpenClaw-агента:
- Генерировать изображения по текстовому описанию
- Редактировать изображения (img2img)
- Обрабатывать ошибки (503 GPU busy → retry)
- Выбирать модель по задаче

Для подключения скопируйте `skill/generate-image/` в директорию skills вашего OpenClaw workspace.

## Архитектура

```
┌─────────────────┐
│  OpenClaw Agent │
└────────┬────────┘
         │ curl (через skill)
         ▼
┌─────────────────┐
│  Images API     │ :8189
│  ┌───────────┐  │
│  │  Router   │──┼──→ fal.ai / RunPod (cloud fallback)
│  └─────┬─────┘  │
│        ▼        │
│  ComfyUI Client │
└────────┬────────┘
         │ HTTP/WebSocket
         ▼
┌─────────────────┐
│  ComfyUI        │ :8188
│  RTX 4090       │
│  FLUX.1 Dev FP8 │
└─────────────────┘
```

Роутер проверяет здоровье ComfyUI через `/system_stats`, мониторит очередь, и переключается на облако при перегрузке.

## Makefile targets

```bash
make download-models          # Скачать все модели
make download-models-flux-dev # Только FLUX.1 Dev FP8
make build                    # Собрать Docker-образы
make up                       # Запустить сервисы
make down                     # Остановить
make logs                     # Логи
make health                   # Проверка здоровья
make test                     # Запуск тестов
```
