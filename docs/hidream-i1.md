# HiDream-I1 — Vivago AI / HiDream.ai

## Обзор

HiDream-I1 — open-source foundation модель генерации изображений от китайского стартапа HiDream.ai (продукт Vivago). Релиз 7 апреля 2025. Распространяется под лицензией **MIT** — коммерчески свободная, без цензурных фильтров.

На момент релиза обогнала FLUX.1 Dev и SD 3.5 Large по бенчмаркам GenEval, DPG-Bench и HPSv2.1. Сильные стороны — сложные сцены, типографика, следование длинным промптам.

## Архитектура

**17 миллиардов параметров**, Sparse Diffusion Transformer с Mixture-of-Experts:

- **Dual-stream DiT** — раздельная обработка image и text токенов
- **Single-stream DiT** — мультимодальное взаимодействие после dual-stream слоёв
- **Dynamic MoE** — маршрутизация между экспертами в обеих ветках

Техотчёт — "HiDream-I1: A High-Efficient Image Generative Foundation Model with Sparse Diffusion Transformer", arXiv 2505.22705 (28 мая 2025).

## Ключевая особенность: четыре text encoder

HiDream использует **четыре энкодера одновременно** (в ComfyUI — через ноду `QuadrupleCLIPLoader`):

| Encoder | Размер (fp8) | Назначение |
|---|---|---|
| CLIP-L | 237 MB | Base CLIP для визуальных концептов |
| CLIP-G | 1.3 GB | Увеличенный CLIP, больше деталей |
| T5-XXL | 4.9 GB | Длинные промпты, описания |
| **Llama 3.1 8B Instruct** | **8.5 GB** | Глубокое понимание языка, следование инструкциям |

Именно Llama даёт HiDream качественное понимание сложных промптов — главное отличие от FLUX.1 и SD3.5.

## Варианты модели

Все три варианта — один и тот же 17B UNET, различаются только рекомендуемым числом шагов:

| Вариант | Шаги | Назначение |
|---|---|---|
| **HiDream-I1 Full** | ~50 | Максимальное качество |
| **HiDream-I1 Dev** | ~28 | Баланс качества и скорости |
| **HiDream-I1 Fast** | ~16 | Быстрая генерация для итераций |

Related: **HiDream-E1** — инструкционный редактор изображений (E1-Full: 28 апреля 2025; E1-1: 16 июля 2025).

## Файлы моделей (Comfy-Org repackaged)

Репозиторий: `Comfy-Org/HiDream-I1_ComfyUI`

### Diffusion models (UNET)

| Файл | Размер |
|---|---|
| `hidream_i1_fast_fp8.safetensors` | **16 GB** |
| `hidream_i1_dev_fp8.safetensors` | 16 GB |
| `hidream_i1_full_fp8.safetensors` | 16 GB |
| `hidream_i1_fast_bf16.safetensors` | ~32 GB |
| `hidream_i1_dev_bf16.safetensors` | ~32 GB |
| `hidream_i1_full_fp16.safetensors` | ~32 GB |
| `hidream_e1_full_bf16.safetensors` | — (editing) |
| `hidream_e1_1_bf16.safetensors` | — (editing) |

### Text encoders (ВСЕ четыре нужны)

| Файл | Размер |
|---|---|
| `clip_l_hidream.safetensors` | 237 MB |
| `clip_g_hidream.safetensors` | 1.3 GB |
| `t5xxl_fp8_e4m3fn_scaled.safetensors` | 4.9 GB |
| `llama_3.1_8b_instruct_fp8_scaled.safetensors` | **8.5 GB** |
| **Суммарно энкодеры** | **14.9 GB** |

### VAE

| Файл | Размер |
|---|---|
| `vae/ae.safetensors` | 320 MB |

Это тот же VAE, что и у FLUX.1 (`ae.safetensors`), так что если уже скачан — качать повторно не нужно.

### Итого минимальный набор (fp8)

| Компонент | Размер |
|---|---|
| UNET fp8 (любой вариант) | 16 GB |
| 4 text encoder | 14.9 GB |
| VAE | 0.3 GB |
| **Всего** | **~31 GB** |

## Совместимость с текущим железом (RTX 4090 24GB + 15GB RAM)

### С `--highvram` (всё в VRAM)

31 GB > 24 GB → **не помещается**.

### Обычный режим (offload в CPU RAM) — НА ГРАНИ

| Компонент | Куда |
|---|---|
| UNET 16 GB | VRAM |
| 4 text encoder (14.9 GB) | CPU RAM |
| Промежуточные буферы | CPU RAM |

Энкодер-стек (**14.9 GB**) занимает почти всю доступную RAM (**15 GB**). Остаётся считанные мегабайты на системные процессы, Docker, ComfyUI runtime и промежуточные буферы.

**Вывод:** высокая вероятность OOM при загрузке, как было с wan-video 14B. Этот сценарий уже проверен на практике — закончился подвисанием VM.

### Варианты обхода

| Подход | Экономия | Минусы |
|---|---|---|
| **GGUF Q4** (UNET) | UNET → ~12 GB | Требует кастомную ноду `ComfyUI-GGUF`, добавляет зависимость, влияет на качество |
| **GGUF Q4** (encoders) | Llama 3.1 → ~4 GB | То же, ещё потеря качества длинных промптов |
| **Выкинуть Llama 3.1** | −8.5 GB RAM | Теряется главное преимущество HiDream, фактически превращается в SD3.5-level |
| **Добавить RAM до 32 GB** | — | Единственное чистое решение |
| **nf4 квантизация** | UNET → ~10 GB | Всплески до 23 GB VRAM в процессе, всё ещё рискованно |

## Интеграция в OpenClaw Images (если решено рисковать)

### Необходимые шаги

1. **Обновить ComfyUI** — нужна версия с поддержкой нод `QuadrupleCLIPLoader` и `hidream` type в `CLIPLoader`. Наш pinned `v0.18.5` поддерживает (HiDream в ComfyUI с апреля 2025).

2. **Makefile** — новая цель `download-models-hidream-fast`:
   ```makefile
   HF_HIDREAM := https://huggingface.co/Comfy-Org/HiDream-I1_ComfyUI/resolve/main/split_files

   download-models-hidream-fast:
       @mkdir -p $(MODEL_DIR)/diffusion_models $(MODEL_DIR)/text_encoders $(MODEL_DIR)/vae
       $(HF_DL) -O "$(MODEL_DIR)/diffusion_models/hidream_i1_fast_fp8.safetensors" \
           "$(HF_HIDREAM)/diffusion_models/hidream_i1_fast_fp8.safetensors"
       $(HF_DL) -O "$(MODEL_DIR)/text_encoders/clip_l_hidream.safetensors" \
           "$(HF_HIDREAM)/text_encoders/clip_l_hidream.safetensors"
       $(HF_DL) -O "$(MODEL_DIR)/text_encoders/clip_g_hidream.safetensors" \
           "$(HF_HIDREAM)/text_encoders/clip_g_hidream.safetensors"
       $(HF_DL) -O "$(MODEL_DIR)/text_encoders/t5xxl_fp8_e4m3fn_scaled.safetensors" \
           "$(HF_HIDREAM)/text_encoders/t5xxl_fp8_e4m3fn_scaled.safetensors"
       $(HF_DL) -O "$(MODEL_DIR)/text_encoders/llama_3.1_8b_instruct_fp8_scaled.safetensors" \
           "$(HF_HIDREAM)/text_encoders/llama_3.1_8b_instruct_fp8_scaled.safetensors"
       $(HF_DL) -O "$(MODEL_DIR)/vae/ae.safetensors" \
           "$(HF_HIDREAM)/vae/ae.safetensors"
   ```

3. **Workflow** `api/workflows/hidream_i1_fast_txt2img.json`:
   - `QuadrupleCLIPLoader` — загружает все 4 энкодера сразу
   - `CLIPTextEncode` (positive + negative; HiDream использует оба)
   - `VAELoader` → `ae.safetensors`
   - `EmptySD3LatentImage`
   - `UNETLoader` → `hidream_i1_fast_fp8.safetensors` с `weight_dtype: fp8_e4m3fn`
   - `ModelSamplingSD3` shift ≈ 3.0
   - `KSampler` — для Fast: 16 шагов, cfg ≈ 5.0, sampler `lcm` или `euler`, scheduler `normal`
   - `VAEDecode` → `SaveImage`

4. **`api/comfyui_client.py`**:
   - Добавить `"hidream-fast": "hidream_i1_fast_txt2img.json"` в `WORKFLOW_MAP`
   - `inject_params` — учесть что HiDream принимает negative prompt (в отличие от FLUX)

5. **`api/server.py`** — добавить `"hidream-fast"` в `VALID_MODELS`.

6. **`skill/generate-image/SKILL.md`** — задокументировать:
   - HiDream сильнее FLUX в понимании длинных промптов
   - Negative prompt работает (в отличие от FLUX)
   - Нецензурированная — предупредить агента о responsibility

### Риски перед интеграцией

1. **OOM при первой загрузке** — энкодер-стек 14.9 GB на 15 GB RAM
2. **Время запуска** — первая загрузка всех 4 энкодеров займёт заметно больше, чем у FLUX.1
3. **Конфликт с flux-dev** — при одновременной загрузке обеих моделей VRAM + RAM не хватит. Нужно полагаться на `IDLE_VRAM_FREE_TIMEOUT` и `/gpu/free`.

## Рекомендация

На текущем железе (RTX 4090 + **только 15 GB RAM**) HiDream-I1 интегрировать **не стоит** — повторит сценарий wan-video 14B с подвисанием VM.

Если HiDream нужен конкретно (из-за нецензурированности, качества понимания промптов или MIT лицензии), путь такой:

1. **Сначала** апгрейд RAM до 32 GB
2. **Потом** интеграция по шагам выше
3. **Альтернатива** — перенести HiDream на отдельную машину с 32+ GB RAM

Для большинства задач FLUX.1 Dev на этом железе работает отлично. Для ускорения — `flux-schnell` или `flux2-klein` (после интеграции).

## Ссылки

- [HiDream-ai/HiDream-I1 (GitHub)](https://github.com/HiDream-ai/HiDream-I1)
- [HiDream-ai/HiDream-I1-Full (Hugging Face)](https://huggingface.co/HiDream-ai/HiDream-I1-Full)
- [HiDream-ai/HiDream-I1-Dev (Hugging Face)](https://huggingface.co/HiDream-ai/HiDream-I1-Dev)
- [HiDream-ai/HiDream-I1-Fast (Hugging Face)](https://huggingface.co/HiDream-ai/HiDream-I1-Fast)
- [Comfy-Org/HiDream-I1_ComfyUI (Hugging Face)](https://huggingface.co/Comfy-Org/HiDream-I1_ComfyUI)
- [Tech report on arXiv (2505.22705)](https://arxiv.org/html/2505.22705v1)
- [ComfyUI Native HiDream-I1 Tutorial](https://docs.comfy.org/tutorials/image/hidream/hidream-i1)
- [ComfyUI HiDream-I1 fp8/gguf/nf4 Tutorial (ComfyUI Wiki)](https://comfyui-wiki.com/en/tutorial/advanced/image/hidream/i1-t2i)
- [HiDream Performance Benchmarks (InstaSD)](https://www.instasd.com/post/hidream-performance-benchmarks-in-comfyui)
- [Decrypt: Vivago's HiDream Beats Major Players](https://decrypt.co/314940/vivago-hidream-image-generator-beats-major-players)
- [HiDream-ai/HiDream-E1-1 (editing model)](https://huggingface.co/HiDream-ai/HiDream-E1-1)
