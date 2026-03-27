---
name: generate_image
description: Generate images from text prompts or edit existing images via a local image generation API backed by FLUX.1, SDXL, and automatic cloud fallback. Use when the user asks to create an image, make a quick visual concept, generate multiple images sequentially, or modify an existing image with img2img.
---

# Generate Image

Use the local image generation service exposed by `IMAGES_API_URL`.

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

- `flux-dev` — default; best for image quality, readable text inside images, and anatomy, especially hands
- `flux-schnell` — use for very fast previews and rough prototyping
- `sdxl` — use for stylized generations, SDXL LoRA ecosystems, or when `negative_prompt` matters

Rules:

- For FLUX models, do **not** send `negative_prompt`; FLUX ignores it
- For FLUX models, control results with `prompt` and `guidance_scale`
- For SDXL, `negative_prompt` is supported and useful
- Generate multiple requested images sequentially, not in parallel
- Be mindful that the same GPU is shared with other services; avoid creating concurrent load

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
| `busy` | varies | Can still submit jobs; they will queue. Cloud fallback may activate if configured |
| `paused` | false | GPU unavailable (user is gaming). Do NOT submit jobs. Tell the user generation is paused. |
| `offline` | false | Backend is down. Tell the user generation is unavailable. |

The response also includes:

- `gpu_paused` — `true` if gaming mode is active
- `jobs` — `{total_queued, processing, gpu_paused}` — queue state

## Text-to-image generation

Generation uses an async job queue. Submit a job, poll for completion, download the result.

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
- `model` — `flux-dev`, `flux-schnell`, `sdxl`
- `width`, `height` — 256..2048
- `steps`
- `guidance_scale`
- `seed`
- `negative_prompt` — SDXL only; ignored by FLUX

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

Job statuses: `queued` → `processing` → `completed` / `failed` / `cancelled`

### Step 3: Download result

```bash
curl -sf "${IMAGES_API_URL}/jobs/${JOB_ID}/result" -o /tmp/generated.png
```

Returns PNG with headers `X-Source`, `X-Seed`, `X-Model`.

- HTTP 202 — job is not yet complete (returns JSON with status and position)
- HTTP 410 — job failed, was cancelled, or result expired (results are kept for 10 minutes after completion)

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

Denoise guidance:

- `0.3-0.5` — light edits
- `0.5-0.7` — moderate changes
- `0.7-0.9` — strong regeneration

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

## Retry behavior

If `/status` shows `paused` — do NOT retry. Tell the user GPU is paused for gaming.

If `/status` shows `offline` — do NOT retry. Tell the user generation is unavailable.

If `/status` shows `busy` — you can still submit jobs; they will queue and process when GPU is free. Cloud fallback (fal.ai/RunPod) may activate automatically if configured.

If job submission returns `429` — queue is full (max 50 jobs). Wait 30 seconds and retry.

## Model discovery

If you need to inspect available checkpoints or LoRAs:

```bash
curl -sf "${IMAGES_API_URL}/models"
```

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
