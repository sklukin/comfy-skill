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
- `sdxl` — use for stylized generations, SDXL ecosystems, or when `negative_prompt` matters

Rules:

- For FLUX models, do **not** send `negative_prompt`; FLUX ignores it
- For FLUX models, control results with `prompt` and `guidance_scale`
- For SDXL, `negative_prompt` is supported and useful
- Generate multiple requested images sequentially, not in parallel
- Check `${IMAGES_API_URL}/status` before submitting new work when service load is uncertain
- Be mindful that the same GPU is shared with TRELLIS.2 / 3D generation; avoid creating concurrent load

## Availability and queue check

First check generator status:

```bash
curl -sf "${IMAGES_API_URL}/status"
```

Interpret the response like this:

- `status=idle` — ready to accept a generation request now
- `status=generating` — generation is already running, but the service can still accept another request
- `status=busy` — queue is full; do not submit a new request yet
- `status=offline` — generation backend is unavailable

Examples:

- `idle`:
  - `ready: true`
  - no active queue pressure
- `generating`:
  - `ready: true`
  - one generation is already running, but another request is allowed
- `busy`:
  - `ready: false`
  - queue is saturated; wait before retrying
- `offline`:
  - `ready: false`
  - ComfyUI / GPU backend is unavailable

Behavior rules:

- If `status=idle`, proceed immediately
- If `status=generating`, you may proceed, but be mindful that latency will be higher
- If `status=busy`, wait and poll `/status` again before submitting
- If `status=offline`, tell the user generation is currently unavailable

You may still use `/health` as a low-level check when diagnosing service issues, but `/status` is the primary readiness endpoint for normal generation flow.

## Text-to-image generation

Use this request shape:

```bash
curl -s -o /tmp/generated.png -w "%{http_code}" \
  -X POST "${IMAGES_API_URL}/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "DESCRIPTION",
    "model": "flux-dev",
    "width": 1024,
    "height": 1024,
    "steps": 20,
    "guidance_scale": 3.5,
    "seed": -1
  }' \
  --max-time 300
```

Supported parameters:

- `prompt` — required
- `model` — `flux-dev`, `flux-schnell`, `sdxl`
- `width`, `height` — 256..2048
- `steps`
- `guidance_scale`
- `seed`
- `negative_prompt` — SDXL only

The response body is a PNG file. Useful metadata may be returned in headers such as `X-Source`, `X-Seed`, and `X-Model`.

## Retry behavior

Before each retry, prefer checking `/status` so you know whether the service is merely busy or actually offline.

If generation returns `503`, retry up to 3 times with a 15 second pause.

Use a pattern like this:

```bash
for i in 1 2 3; do
  STATUS_JSON=$(curl -sf "${IMAGES_API_URL}/status") || exit 1

  if echo "$STATUS_JSON" | grep -q '"status":"offline"'; then
    echo "Generation backend is offline"
    exit 1
  fi

  if echo "$STATUS_JSON" | grep -q '"status":"busy"'; then
    echo "GPU busy, waiting 15 seconds... ($i/3)"
    sleep 15
    continue
  fi

  HTTP_CODE=$(curl -s -o /tmp/generated.png -w "%{http_code}" \
    -X POST "${IMAGES_API_URL}/generate" \
    -H "Content-Type: application/json" \
    -d '{"prompt":"DESCRIPTION","model":"flux-dev"}' \
    --max-time 300)

  if [ "$HTTP_CODE" = "200" ]; then
    break
  fi

  if [ "$HTTP_CODE" = "503" ]; then
    echo "Generation not ready yet, waiting 15 seconds... ($i/3)"
    sleep 15
    continue
  fi

  echo "HTTP $HTTP_CODE"
  break
done
```

Interpret `503` as one of:

- local GPU overload
- backend accepted the request but produced no image yet
- ComfyUI unavailable
- local generation busy because TRELLIS.2 / 3D generation is using the same GPU

The service may automatically fall back to cloud generation (`fal.ai`) when the local GPU is overloaded. If fallback source is visible in headers or response metadata and it matters for privacy/cost, mention it to the user.

## Image-to-image editing

Use the img2img endpoint for modifying an existing image:

```bash
curl -s -o /tmp/edited.png -w "%{http_code}" \
  -X POST "${IMAGES_API_URL}/generate/img2img" \
  -F "image=@/path/to/photo.png" \
  -F "prompt=DESCRIBE THE CHANGES" \
  -F "model=flux-dev" \
  -F "denoise=0.65" \
  --max-time 300
```

Denoise guidance:

- `0.3-0.5` — light edits
- `0.5-0.7` — moderate changes
- `0.7-0.9` — strong regeneration

## Fast preview mode

For very fast previews, use `flux-schnell`:

```bash
curl -s -o /tmp/preview.png \
  -X POST "${IMAGES_API_URL}/generate" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"DESCRIPTION","model":"flux-schnell","steps":4}'
```

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

or for img2img:

```bash
test -s /tmp/edited.png
```

Then:

- tell the user the image is ready
- send the generated image as an attachment/media result
- if generation failed after retries, tell the user clearly what failed
- if the user asked for multiple images, produce and return them one by one
h
