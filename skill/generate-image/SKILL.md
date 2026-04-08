---
name: generate_image
description: Generate images from text prompts, edit existing images (img2img, inpainting, outpainting), via a local image generation API backed by FLUX.1, SDXL, and automatic cloud fallback. Use when the user asks to create an image, make a quick visual concept, generate multiple images sequentially, modify an existing image, inpaint/remove/replace parts of an image, or extend an image.
---

# Generate Image

Use the local image generation service exposed by `IMAGES_API_URL`.

Bundled wrappers live in `scripts/` next to this file:

- `scripts/generate_image_job.py` — text-to-image helper
- `scripts/generate_image_img2img_job.py` — image-to-image helper
- `scripts/generate_image_inpaint_job.py` — inpainting/outpainting helper (FLUX Fill)

Prefer these Python wrappers over ad-hoc shell JSON parsing when you need a reliable local helper.

## Defaults

- Default model: `flux-dev`
- Default size: `1024x1024`
- Default FLUX steps: `20`
- Default FLUX guidance scale: `3.5`
- Default Schnell steps: `4`
- Default SDXL steps: `25`
- Default SDXL guidance scale: `7.0`
- Default seed: `-1`

## Model selection

Choose the model based on the task:

### Text-to-Image (generation from scratch)

| Task | Model | Why |
|------|-------|-----|
| Best quality, details, readable text, hands | `flux-dev` | 20 steps, best anatomy and text rendering |
| Fast preview / rough prototype | `flux-schnell` | 4 steps, <2s |
| Stylized, anime, LoRA ecosystems | `sdxl` | Huge LoRA ecosystem, negative_prompt support |

### Image Editing

| Task | Model | Why |
|------|-------|-----|
| Replace part of image (inpainting) | `flux-fill` | Best open inpainting model, mask-based |
| Extend image (outpainting) | `flux-fill` | Pad canvas, mask empty area |
| Light style/detail changes | `flux-dev` (img2img) | denoise 0.3-0.7 |
| Strong regeneration from reference | `flux-dev` (img2img) | denoise 0.7-0.9 |

### Decision guide

1. User wants a new image from scratch → **text-to-image** (flux-dev / flux-schnell / sdxl)
2. User wants to change part of an existing image → **inpainting** (flux-fill)
3. User wants to extend/uncrop an image → **outpainting** (flux-fill)
4. User wants to restyle or tweak an existing image → **img2img** (flux-dev)
5. User wants a quick draft → **flux-schnell**

### Rules

- For FLUX models, do **not** send `negative_prompt`; FLUX ignores it
- For FLUX models, control results with `prompt` and `guidance_scale`
- For SDXL, `negative_prompt` is supported and useful
- IMG2IMG is only supported with `flux-dev`
- Inpainting requires `flux-fill` with both `input_image` and `mask_image`
- Generate multiple requested images sequentially, not in parallel
- Be mindful that the same GPU is shared with other services; avoid creating concurrent load
- For all generation, the canonical flow is always: `GET /status` → `POST /jobs` → `GET /jobs/{job_id}` → `GET /jobs/{job_id}/result`
- Start with `/status` before the first generation request in a task
- Do not invent or probe alternative generation endpoints when the jobs flow is documented and available

## Availability check

Check generator status before submitting work:

```bash
curl -sf "${IMAGES_API_URL}/status"
```

Status values:

| status | ready | What to do |
|--------|-------|------------|
| `idle` | true | Proceed immediately |
| `generating` | true | Can proceed, but latency will be higher |

In practice, `generating` is a normal and healthy state: one job is already running, but additional jobs can still be submitted and queued.
| `busy` | varies | Can still submit jobs; they will queue. Cloud fallback may activate if configured |
| `paused` | false | GPU unavailable (user is gaming). Do NOT submit jobs. Tell the user generation is paused. |
| `offline` | false | Backend is down. Tell the user generation is unavailable. |

The response also includes:

- `gpu_paused` — `true` if gaming mode is active
- `jobs` — `{total_queued, processing, gpu_paused}` — queue state

## Text-to-image generation

Generation uses an async job queue. This is the canonical and expected flow for text-to-image requests: submit a job, poll for completion, download the result.

Do not assume a synchronous text-to-image endpoint exists. Do not bypass the job queue when `POST /jobs` is available.

### Step 1: Submit job

```bash
JOB=$(curl -sf -X POST "${IMAGES_API_URL}/jobs" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "DESCRIPTION",
    "model": "flux-dev",
    "width": 1024,
    "height": 1024,
    "steps": 20,
    "guidance_scale": 3.5,
    "seed": -1
  }')
JOB_ID=$(echo "$JOB" | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
echo "Job submitted: $JOB_ID"
```

Supported parameters:

- `prompt` — required
- `model` — `flux-dev`, `flux-schnell`, `flux-fill`, `sdxl`
- `width`, `height` — 256..2048
- `steps`
- `guidance_scale`
- `seed`
- `negative_prompt` — SDXL only; ignored by FLUX
- `input_image` — uploaded filename for img2img or inpainting
- `mask_image` — uploaded filename for inpainting (required with `flux-fill`)
- `denoise` — strength for img2img/inpainting (0.0-1.0)

Response:

```json
{"job_id": "abc123...", "status": "queued", "position": 1, "created_at": "..."}
```

### Step 2: Poll for completion

```bash
while true; do
  R=$(curl -sf "${IMAGES_API_URL}/jobs/${JOB_ID}")
  S=$(echo "$R" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  case "$S" in
    completed) echo "Done"; break ;;
    failed) echo "Job failed: $(echo "$R" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error',''))")"; exit 1 ;;
    cancelled) echo "Job cancelled"; exit 1 ;;
    *) echo "Status: $S, waiting..."; sleep 5 ;;
  esac
done
```

Observed in testing:

- `flux-schnell` text-to-image jobs can complete very quickly (single-digit seconds)
- `flux-dev` img2img jobs may take around 1-2 minutes, so do not assume a short poll loop is enough
- `queued` -> `processing` -> `completed` is the expected happy path

Job statuses: `queued` → `processing` → `completed` / `failed` / `cancelled`

### Step 3: Download result

```bash
curl -sf "${IMAGES_API_URL}/jobs/${JOB_ID}/result" -o /tmp/generated.png
```

Returns PNG with headers `X-Source`, `X-Seed`, `X-Model`.

- HTTP 202 — job is not yet complete (returns JSON with status and position)
- HTTP 410 — job failed, was cancelled, or result expired (results are kept for 10 minutes after completion)

Observed in testing:

- Calling `/jobs/${JOB_ID}/result` before completion really does return `202` with JSON like `{"job_id":"...","status":"queued","position":1}`
- Calling `/jobs/${JOB_ID}/result` for a cancelled job returns `410` with a message such as `{"detail":"Job was cancelled"}`

Download the result promptly — completed job results expire after 10 minutes.

## Image-to-image editing

IMG2IMG is only supported with the `flux-dev` model. Do not use `flux-schnell` or `sdxl` for img2img.

Two-step process: upload the source image, then submit a job referencing it.

### Step 1: Upload image

```bash
UPLOAD=$(curl -sf -X POST "${IMAGES_API_URL}/upload" \
  -F "image=@/path/to/photo.png")
FILENAME=$(echo "$UPLOAD" | python3 -c "import sys,json; print(json.load(sys.stdin)['filename'])")
```

### Step 2: Submit img2img job

```bash
JOB=$(curl -sf -X POST "${IMAGES_API_URL}/jobs" \
  -H "Content-Type: application/json" \
  -d "{
    \"prompt\": \"DESCRIBE THE CHANGES\",
    \"model\": \"flux-dev\",
    \"input_image\": \"${FILENAME}\",
    \"denoise\": 0.65
  }")
JOB_ID=$(echo "$JOB" | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
```

Then poll and download as described above.

Recommended bundled wrapper:

```bash
python3 /home/openclaw/.openclaw/workspace/skills/generate_image/scripts/generate_image_img2img_job.py \
  --input /path/to/source.jpg \
  --prompt "DESCRIBE THE CHANGES" \
  --output /tmp/edited.png
```

Denoise guidance:

- `0.3-0.5` — light edits
- `0.5-0.7` — moderate changes
- `0.7-0.9` — strong regeneration

## Inpainting / Outpainting (FLUX Fill)

Use `flux-fill` to replace or generate content in specific areas of an image using a mask.

### When to use

- Replace an object ("remove the cat, put a dog")
- Remove an object ("remove the watermark/text")
- Extend an image (outpainting / uncropping)
- Replace background (combine with background removal for mask)

### Mask format

The mask is a separate image, same dimensions as the source:
- **White** (255) = area to inpaint (replace)
- **Black** (0) = area to keep unchanged
- **Gray** values = partial inpainting (smooth transitions via DifferentialDiffusion)

### Step 1: Upload source image

```bash
UPLOAD_IMG=$(curl -sf -X POST "${IMAGES_API_URL}/upload" \
  -F "image=@/path/to/source.png")
IMG_FILENAME=$(echo "$UPLOAD_IMG" | python3 -c "import sys,json; print(json.load(sys.stdin)['filename'])")
```

### Step 2: Upload mask image

```bash
UPLOAD_MASK=$(curl -sf -X POST "${IMAGES_API_URL}/upload" \
  -F "image=@/path/to/mask.png")
MASK_FILENAME=$(echo "$UPLOAD_MASK" | python3 -c "import sys,json; print(json.load(sys.stdin)['filename'])")
```

### Step 3: Submit inpainting job

```bash
JOB=$(curl -sf -X POST "${IMAGES_API_URL}/jobs" \
  -H "Content-Type: application/json" \
  -d "{
    \"prompt\": \"DESCRIBE WHAT SHOULD APPEAR IN THE MASKED AREA\",
    \"model\": \"flux-fill\",
    \"input_image\": \"${IMG_FILENAME}\",
    \"mask_image\": \"${MASK_FILENAME}\",
    \"denoise\": 1.0
  }")
JOB_ID=$(echo "$JOB" | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
```

Then poll and download as described above.

### Inpainting parameters

- `denoise`: `0.8-1.0` for full replacement, `0.5-0.7` for gentle correction
- `guidance_scale`: `3.5` (same as flux-dev)
- `steps`: `20`
- `prompt`: describes what should be in the masked area, NOT the whole image

### Outpainting (extending an image)

To extend an image beyond its borders:
1. Create a larger canvas and place the original image on it (e.g., centered)
2. Create a mask where the empty/padded area is white and the original image area is black
3. Submit with `flux-fill`, prompt describing what should appear beyond the edges

### Recommended bundled wrapper

```bash
python3 /home/openclaw/.openclaw/workspace/skills/generate_image/scripts/generate_image_inpaint_job.py \
  --input /path/to/source.png \
  --mask /path/to/mask.png \
  --prompt "a golden retriever sitting on the grass" \
  --output /tmp/inpainted.png
```

## Fast preview mode

For very fast previews, use `flux-schnell` with 4 steps:

```bash
JOB=$(curl -sf -X POST "${IMAGES_API_URL}/jobs" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"DESCRIPTION","model":"flux-schnell","steps":4}')
```

## Cancelling a job

If you need to cancel a queued job:

```bash
curl -sf -X DELETE "${IMAGES_API_URL}/jobs/${JOB_ID}"
```

Only works for jobs in `queued` status.

Observed in testing: cancelling a queued job returns HTTP 200 with JSON like `{"job_id":"...","status":"cancelled"}`.

## Retry behavior

If `/status` shows `paused` — do NOT retry. Tell the user GPU is paused for gaming.

If `/status` shows `offline` — do NOT retry. Tell the user generation is unavailable.

If `/status` shows `busy` — you can still submit jobs; they will queue and process when GPU is free. Continue to use the same `/jobs` flow; do not switch to undocumented alternatives. Cloud fallback (fal.ai/RunPod) may activate automatically if configured.

If job submission returns `429` — queue is full (max 50 jobs). Wait 30 seconds and retry.

## Model discovery

If you need to inspect available checkpoints or LoRAs:

```bash
curl -sf "${IMAGES_API_URL}/models"
```

## Bundled wrappers

Use the bundled wrappers when you want deterministic local execution without reimplementing the jobs flow.

Text-to-image:

```bash
python3 /home/openclaw/.openclaw/workspace/skills/generate_image/scripts/generate_image_job.py \
  --prompt "night sky, stars, realistic astronomy photo" \
  --output /tmp/generated.png
```

Image-to-image:

```bash
python3 /home/openclaw/.openclaw/workspace/skills/generate_image/scripts/generate_image_img2img_job.py \
  --input /path/to/source.png \
  --prompt "turn this into a cinematic night scene" \
  --output /tmp/edited.png
```

Inpainting:

```bash
python3 /home/openclaw/.openclaw/workspace/skills/generate_image/scripts/generate_image_inpaint_job.py \
  --input /path/to/source.png \
  --mask /path/to/mask.png \
  --prompt "a golden retriever sitting on the grass" \
  --output /tmp/inpainted.png
```

Keep these scripts as the canonical local wrappers for this skill. If you improve the flow, update the skill-bundled scripts first.

## Returning results

Before replying, verify that the output file exists and is not empty:

```bash
test -s /tmp/generated.png
```

Then:

- tell the user the image is ready
- send the generated image as an attachment/media result
- if generation failed after retries, tell the user clearly what failed
- if the user asked for multiple images, produce and return them one by one

