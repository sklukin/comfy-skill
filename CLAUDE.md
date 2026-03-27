# OpenClaw Images — AI Image Generation Service

## Назначение

Сервис генерации изображений для OpenClaw. ComfyUI (headless GPU worker) + REST API + OpenClaw skill для интеграции с агентами. Основная модель — FLUX.1 Dev FP8 на RTX 4090.

## Архитектура

```
OpenClaw Agent → skill (curl) → REST API (:8189) → ComfyUI (:8188) → RTX 4090
                                                  ↘ fal.ai / RunPod (cloud fallback)
```

- **ComfyUI** — headless GPU worker, принимает JSON-workflows
- **REST API** — FastAPI, endpoints: `/jobs`, `/jobs/{id}`, `/jobs/{id}/result`, `/upload`, `/status`, `/health`, `/models`, `/gpu/pause`, `/gpu/resume`
- **Job Queue** — асинхронная очередь задач (`queue_manager.py`), поддержка нескольких агентов одновременно
- **Cloud Router** — автоматический фолбэк в fal.ai/RunPod при перегрузке GPU
- **Gaming Mode** — `make gaming` / `make resume` для паузы GPU когда пользователь играет
- **OpenClaw Skill** — `skill/generate-image/SKILL.md`, учит агента вызывать API через curl

## Быстрый старт

```bash
make download-models   # ~30GB, пропускает уже скачанные
make build && make up  # Запуск ComfyUI + API
make health            # Проверка здоровья
```

## Порты

| Сервис | Порт | Назначение |
|--------|------|------------|
| ComfyUI | 8188 | GPU worker (внутренний) |
| Images API | 8189 | REST API для генерации |

## Структура

- `api/` — FastAPI сервер (server.py, comfyui_client.py, cloud_router.py, queue_manager.py, workflows/)
- `comfyui/` — Dockerfile для ComfyUI headless
- `skill/generate-image/` — OpenClaw skill
- `models/` — модели (volume-mount, не в git)

## Модели

Скачиваются через `make download-models`:
- `models/checkpoints/flux1-dev-fp8.safetensors` — основная (~12GB VRAM)
- `models/checkpoints/flux1-schnell-fp8.safetensors` — быстрая (4 шага, <1с)
- `models/text_encoders/` — T5-XXL FP8, CLIP-L
- `models/vae/ae.safetensors`

## Workflows

JSON-шаблоны в `api/workflows/`. Параметры инжектятся через `comfyui_client.py`.

**FLUX.1 Dev**: CFG=1.0 (обязательно для FP8), guidance через FluxGuidance node (default 3.5), Euler sampler, Beta scheduler.

## GPU

RTX 4090 (24GB VRAM). Нельзя запускать одновременно с 3dmodels/TRELLIS.2 под нагрузкой.

## Переменные окружения

См. `.env.example`. Ключевые: `FAL_KEY` (облачный фолбэк), `IMAGES_API_URL` (для skill).
