HF_TOKEN ?=
MODEL_DIR := ./models

# HuggingFace base URLs
HF_FLUX_DEV    := https://huggingface.co/Comfy-Org/flux1-dev/resolve/main
HF_FLUX_SCHNELL := https://huggingface.co/Comfy-Org/flux1-schnell/resolve/main
HF_TEXT_ENC    := https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main
HF_VAE        := https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main
HF_SDXL       := https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main

HF_DL := wget -q --show-progress -c
HF_DL_AUTH := $(HF_DL) --header="Authorization: Bearer $(HF_TOKEN)"

.PHONY: download-models download-models-flux-dev download-models-flux-schnell \
        download-models-encoders build up down logs health test gaming resume queue

# === Model Downloads ===

download-models: download-models-flux-dev download-models-flux-schnell download-models-sdxl download-models-encoders
	@echo "All models downloaded to $(MODEL_DIR)"

download-models-flux-dev:
	@mkdir -p $(MODEL_DIR)/checkpoints
	@if [ -f "$(MODEL_DIR)/checkpoints/flux1-dev-fp8.safetensors" ]; then \
		echo "skip flux1-dev-fp8.safetensors (exists)"; \
	else \
		echo "downloading flux1-dev-fp8.safetensors (~12GB)..."; \
		$(HF_DL) -O "$(MODEL_DIR)/checkpoints/flux1-dev-fp8.safetensors" \
			"$(HF_FLUX_DEV)/flux1-dev-fp8.safetensors" || exit 1; \
	fi

download-models-flux-schnell:
	@mkdir -p $(MODEL_DIR)/checkpoints
	@if [ -f "$(MODEL_DIR)/checkpoints/flux1-schnell-fp8.safetensors" ]; then \
		echo "skip flux1-schnell-fp8.safetensors (exists)"; \
	else \
		echo "downloading flux1-schnell-fp8.safetensors (~12GB)..."; \
		$(HF_DL) -O "$(MODEL_DIR)/checkpoints/flux1-schnell-fp8.safetensors" \
			"$(HF_FLUX_SCHNELL)/flux1-schnell-fp8.safetensors" || exit 1; \
	fi

download-models-sdxl:
	@mkdir -p $(MODEL_DIR)/checkpoints
	@if [ -f "$(MODEL_DIR)/checkpoints/sd_xl_base_1.0.safetensors" ]; then \
		echo "skip sd_xl_base_1.0.safetensors (exists)"; \
	else \
		echo "downloading sd_xl_base_1.0.safetensors (~6.9GB)..."; \
		$(HF_DL) -O "$(MODEL_DIR)/checkpoints/sd_xl_base_1.0.safetensors" \
			"$(HF_SDXL)/sd_xl_base_1.0.safetensors" || exit 1; \
	fi

download-models-encoders:
	@mkdir -p $(MODEL_DIR)/text_encoders $(MODEL_DIR)/vae $(MODEL_DIR)/loras $(MODEL_DIR)/diffusion_models
	@if [ -f "$(MODEL_DIR)/text_encoders/t5xxl_fp8_e4m3fn.safetensors" ]; then \
		echo "skip t5xxl_fp8_e4m3fn.safetensors (exists)"; \
	else \
		echo "downloading t5xxl_fp8_e4m3fn.safetensors (~4.9GB)..."; \
		$(HF_DL) -O "$(MODEL_DIR)/text_encoders/t5xxl_fp8_e4m3fn.safetensors" \
			"$(HF_TEXT_ENC)/t5xxl_fp8_e4m3fn.safetensors" || exit 1; \
	fi
	@if [ -f "$(MODEL_DIR)/text_encoders/clip_l.safetensors" ]; then \
		echo "skip clip_l.safetensors (exists)"; \
	else \
		echo "downloading clip_l.safetensors (~246MB)..."; \
		$(HF_DL) -O "$(MODEL_DIR)/text_encoders/clip_l.safetensors" \
			"$(HF_TEXT_ENC)/clip_l.safetensors" || exit 1; \
	fi
	@if [ -f "$(MODEL_DIR)/vae/ae.safetensors" ]; then \
		echo "skip ae.safetensors (exists)"; \
	else \
		echo "downloading ae.safetensors (~300MB)..."; \
		$(HF_DL_AUTH) -O "$(MODEL_DIR)/vae/ae.safetensors" \
			"$(HF_VAE)/ae.safetensors" || exit 1; \
	fi

# === Docker ===

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

health:
	@echo "=== ComfyUI ===" && \
	curl -sf http://localhost:8188/system_stats | python3 -m json.tool && \
	echo "" && \
	echo "=== Images API ===" && \
	curl -sf http://localhost:8189/health | python3 -m json.tool

test:
	cd api && python -m pytest tests/ -v

# === GPU Control ===

gaming:
	@echo "Pausing GPU for gaming..." && \
	curl -sf -X POST http://localhost:8189/gpu/pause | python3 -m json.tool

resume:
	@echo "Resuming GPU..." && \
	curl -sf -X POST http://localhost:8189/gpu/resume | python3 -m json.tool

queue:
	@echo "=== Job Queue ===" && \
	curl -sf http://localhost:8189/status | python3 -m json.tool
