# FLUX.2 — Black Forest Labs

## Обзор

FLUX.2 — следующее поколение open-weight генеративных моделей от Black Forest Labs. Семейство из четырёх вариантов: Pro, Flex, Dev, Klein. Релиз `[pro]`/`[flex]`/`[dev]` — 25 ноября 2025, `[klein]` — 15 января 2026.

Ключевые улучшения относительно FLUX.1:
- Мульти-референсное редактирование (до десятков похожих вариаций)
- Улучшенный фотореализм
- Более аккуратная типографика
- Лучшее понимание длинных и сложных промптов
- Новый text encoder на основе Mistral-3 Small (dev) или Qwen-3 4B (klein) вместо T5-XXL
- Новый VAE (`flux2-vae.safetensors`, 321 MB) — несовместим с FLUX.1 VAE

## Варианты и размеры

| Вариант | Параметры | Лицензия | Назначение |
|---|---|---|---|
| **FLUX.2 [pro]** | ? | Proprietary (API) | Флагман, только через API Black Forest Labs |
| **FLUX.2 [flex]** | ? | Proprietary (API) | Pro с настраиваемыми шагами/guidance |
| **FLUX.2 [dev]** | 32B | Non-commercial | Open weights, для опенсорсных разработок |
| **FLUX.2 [klein]** | 4B / 9B | **Apache 2.0** | Самая быстрая, коммерчески свободная |

## Файлы моделей (Comfy-Org repackaged)

### FLUX.2 [dev] 32B

Репозиторий: `Comfy-Org/flux2-dev`

| Файл | Размер |
|---|---|
| `diffusion_models/flux2_dev_fp8mixed.safetensors` | **34 GB** |
| `text_encoders/mistral_3_small_flux2_bf16.safetensors` | 34 GB |
| `text_encoders/mistral_3_small_flux2_fp8.safetensors` | **17 GB** |
| `text_encoders/mistral_3_small_flux2_fp4_mixed.safetensors` | ~9 GB |
| `vae/flux2-vae.safetensors` | 321 MB |
| **Минимальный набор (fp8)** | **~51 GB** |

Дополнительно доступны LoRA ускорители:
- `loras/Flux2TurboComfyv2.safetensors`
- `loras/Flux_2-Turbo-LoRA_comfyui.safetensors`

### FLUX.2 [klein] 4B

Репозиторий: `Comfy-Org/vae-text-encorder-for-flux-klein-4b`

| Файл | Размер |
|---|---|
| `diffusion_models/flux-2-klein-4b.safetensors` | 7.3 GB |
| `diffusion_models/flux-2-klein-base-4b.safetensors` | 7.3 GB |
| `text_encoders/qwen_3_4b.safetensors` | 7.5 GB |
| `text_encoders/qwen_3_4b_fp4_flux2.safetensors` | **3.6 GB** |
| `vae/flux2-vae.safetensors` | 321 MB |
| **Минимальный набор (fp4 encoder)** | **~11 GB** |

## Совместимость с текущим железом (RTX 4090 24GB + 15GB RAM)

### FLUX.2 [dev] 32B — НЕ помещается

| Сценарий | UNET | Encoder | Итого | Результат |
|---|---|---|---|---|
| `--highvram` (всё в VRAM) | 34 GB | 17 GB | 51 GB | ❌ 51 > 24 |
| Обычный (offload в RAM) | 34 GB в VRAM | 17 GB в RAM | — | ❌ UNET > VRAM, encoder > RAM |

Для FLUX.2 Dev нужно железо уровня **A6000 (48GB)** или **H100 (80GB)**. На 4090 + 15GB RAM невозможно без радикального квантования (nf4/Q3 GGUF).

### FLUX.2 [klein] 4B — помещается с запасом

| Компонент | Размер |
|---|---|
| UNET 4B | 7.3 GB |
| Qwen-3 4B fp4 | 3.6 GB |
| VAE | 0.3 GB |
| **Итого** | **~11 GB** |
| Свободно в VRAM | ~13 GB для активаций |

С `--highvram` работает чисто, CPU RAM вообще не задействуется. Ожидаемая скорость — <1 секунды на изображение (это и есть цель klein).

## Интеграция в OpenClaw Images

### Шаги интеграции (FLUX.2 [klein] 4B)

1. **Проверить поддержку в ComfyUI** — наш pinned `v0.18.5` может не поддерживать klein (релиз 15 января 2026). Возможно, нужно обновить до v0.18.6+. Проверяется наличием нод `QwenTextEncode` / изменений в `CLIPLoader` type.

2. **Makefile** — новая цель `download-models-flux2-klein`:
   ```makefile
   HF_FLUX2_KLEIN := https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-4b/resolve/main/split_files

   download-models-flux2-klein:
       @mkdir -p $(MODEL_DIR)/diffusion_models $(MODEL_DIR)/text_encoders $(MODEL_DIR)/vae
       $(HF_DL) -O "$(MODEL_DIR)/diffusion_models/flux-2-klein-4b.safetensors" \
           "$(HF_FLUX2_KLEIN)/diffusion_models/flux-2-klein-4b.safetensors"
       $(HF_DL) -O "$(MODEL_DIR)/text_encoders/qwen_3_4b_fp4_flux2.safetensors" \
           "$(HF_FLUX2_KLEIN)/text_encoders/qwen_3_4b_fp4_flux2.safetensors"
       $(HF_DL) -O "$(MODEL_DIR)/vae/flux2-vae.safetensors" \
           "$(HF_FLUX2_KLEIN)/vae/flux2-vae.safetensors"
   ```

3. **Workflow** `api/workflows/flux2_klein_txt2img.json`:
   - `CLIPLoader` с `type` = `qwen3` или `flux2` (уточнить на живом контейнере)
   - `CLIPTextEncode` (позитивный промпт; FLUX игнорирует negative)
   - `VAELoader` → `flux2-vae.safetensors`
   - `EmptySD3LatentImage` или эквивалент (flow matching)
   - `UNETLoader` → `flux-2-klein-4b.safetensors`
   - `KSampler` — параметры предстоит подобрать (klein оптимизирован под 2-4 шага)
   - `VAEDecode` → `SaveImage`

4. **`api/comfyui_client.py`** — добавить в `WORKFLOW_MAP`:
   ```python
   "flux2-klein": "flux2_klein_txt2img.json",
   ```

5. **`api/server.py`** — добавить `"flux2-klein"` в `VALID_MODELS`.

6. **`api/cloud_router.py`** — если fal.ai/RunPod уже поддерживают FLUX.2, можно добавить роут; на момент написания скорее всего ещё нет.

7. **`skill/generate-image/SKILL.md`** — задокументировать новую модель, указать её как быструю альтернативу `flux-schnell`.

### Что нужно выяснить на живом контейнере перед кодом

1. Поддерживает ли ComfyUI v0.18.5 FLUX.2 klein (релиз klein — 15 января 2026).
2. Какое значение `type` принимает `CLIPLoader` для Qwen-3 encoder.
3. Оптимальные параметры `KSampler` для klein: sampler, scheduler, steps, cfg.

## Ссылки

- [Black Forest Labs](https://bfl.ai/)
- [FLUX.2 Day-0 Support in ComfyUI](https://blog.comfy.org/p/flux2-state-of-the-art-visual-intelligence)
- [ComfyUI FLUX.2 Dev Example](https://docs.comfy.org/tutorials/flux/flux-2-dev)
- [Comfy-Org/flux2-dev](https://huggingface.co/Comfy-Org/flux2-dev)
- [Comfy-Org/vae-text-encorder-for-flux-klein-4b](https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-4b)
- [VentureBeat: FLUX.2 launch](https://venturebeat.com/ai/black-forest-labs-launches-flux-2-ai-image-models-to-challenge-nano-banana)
- [VentureBeat: FLUX.2 klein launch](https://venturebeat.com/technology/black-forest-labs-launches-open-source-flux-2-klein-to-generate-ai-images-in)
