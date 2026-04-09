# OpenClaw Images — AI Image Generation

Сервис генерации изображений для OpenClaw. Локальная генерация на RTX 4090 через ComfyUI + облачный фолбэк.

## Стек

- **ComfyUI** — headless GPU worker (FLUX.1 Dev FP8, 9-16с на картинку 1024x1024)
- **REST API** — FastAPI, асинхронная очередь задач, маршрутизация между локальным GPU и облаком
- **OpenClaw Skill** — `skill/generate-image/` — учит агента генерировать изображения через API
- **Cloud Fallback** — fal.ai / RunPod при перегрузке GPU

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
| `POST` | `/jobs` | Создать задачу на генерацию (JSON body) |
| `GET` | `/jobs/{id}` | Статус задачи (позиция в очереди, результат) |
| `GET` | `/jobs/{id}/result` | Скачать готовое изображение (PNG) |
| `DELETE` | `/jobs/{id}` | Отменить задачу в очереди |
| `POST` | `/upload` | Загрузить изображение для img2img |
| `GET` | `/health` | Здоровье сервиса, GPU, VRAM |
| `GET` | `/models` | Список установленных моделей |
| `POST` | `/gpu/pause` | Gaming mode — пауза GPU, освобождение VRAM |
| `POST` | `/gpu/resume` | Возобновление GPU |

### Пример генерации

Генерация асинхронная через очередь задач:

```bash
# 1. Отправить задачу
JOB=$(curl -s -X POST http://localhost:8189/jobs \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a cat astronaut, photorealistic", "model": "flux-dev"}')
JOB_ID=$(echo $JOB | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

# 2. Дождаться завершения и скачать
sleep 15
curl -s -o image.png http://localhost:8189/jobs/$JOB_ID/result
```

## Модели

| Модель | VRAM | Время | Назначение |
|--------|------|-------|------------|
| FLUX.1 Dev FP8 | ~12GB | 9-16с | Основная: фотореализм, текст, анатомия |
| FLUX.1 Schnell FP8 | ~12GB | <1с | Быстрое прототипирование |
| SDXL | ~6-8GB | 6-13с | Стилизация, огромная экосистема LoRA |

Файлы хранятся в `models/` (volume-mount, не в Docker image).

## GPU Management

### Gaming Mode

Пауза GPU для игр — модели выгружаются из VRAM, память освобождается:

```bash
make gaming   # Пауза GPU + освобождение VRAM
make resume   # Возобновление (модели загрузятся при следующей генерации)
```

Задачи в очереди ждут возобновления (или уходят в облако при наличии ключей).

### Auto VRAM Cleanup

Через `IDLE_VRAM_FREE_TIMEOUT` секунд простоя (default: 300) модели автоматически выгружаются из VRAM. При следующем запросе загружаются обратно (~3-5с).

## Конфигурация

```bash
cp .env.example .env
```

| Переменная | Описание | Default |
|-----------|----------|---------|
| `FAL_KEY` | API-ключ fal.ai для облачного фолбэка | — |
| `RUNPOD_API_KEY` | API-ключ RunPod | — |
| `RUNPOD_ENDPOINT_ID` | Endpoint ID RunPod | — |
| `MAX_QUEUE_DEPTH` | Макс. очередь ComfyUI до переключения на облако | 3 |
| `IDLE_VRAM_FREE_TIMEOUT` | Секунд простоя до автоочистки VRAM (0 = выкл) | 300 |
| `MAX_QUEUE_JOBS` | Макс. задач в очереди API | 50 |
| `JOB_RESULT_TTL` | Время хранения результатов в секундах | 600 |
| `HF_TOKEN` | Токен HuggingFace (для gated моделей) | — |
| `IMAGES_API_URL` | URL API для OpenClaw skill | http://localhost:8189 |

## OpenClaw Skill

Skill в `skill/generate-image/SKILL.md` учит OpenClaw-агента:
- Генерировать изображения по текстовому описанию
- Редактировать изображения (img2img)
- Обрабатывать ошибки и асинхронную очередь
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
│  │ Job Queue │  │  ← асинхронная очередь + auto VRAM cleanup
│  └─────┬─────┘  │
│  ┌─────▼─────┐  │
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
make gaming                   # Пауза GPU (gaming mode)
make resume                   # Возобновить GPU
make queue                    # Статус очереди задач
```
