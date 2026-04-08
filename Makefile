HF_TOKEN ?=
MODEL_DIR := ./models

# HuggingFace base URLs — base models
HF_FLUX_DEV    := https://huggingface.co/Comfy-Org/flux1-dev/resolve/main
HF_FLUX_SCHNELL := https://huggingface.co/Comfy-Org/flux1-schnell/resolve/main
HF_TEXT_ENC    := https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main
HF_VAE        := https://huggingface.co/cocktailpeanut/xulf-dev/resolve/main
HF_SDXL       := https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main

# HuggingFace base URLs — editing & control models (community FP8 quantizations)
HF_FLUX_FILL    := https://huggingface.co/Academia-SD/flux1-Fill-Dev-FP8/resolve/main
HF_FLUX_KONTEXT := https://huggingface.co/6chan/flux1-kontext-dev-fp8/resolve/main
HF_FLUX_DEPTH   := https://huggingface.co/Academia-SD/flux1-Depth-Dev-FP8/resolve/main
HF_FLUX_CANNY   := https://huggingface.co/Academia-SD/flux1-Canny-Dev-FP8/resolve/main
HF_FLUX_REDUX   := https://huggingface.co/Runware/FLUX.1-Redux-dev/resolve/main
HF_CONTROLNET   := https://huggingface.co/Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro-2.0/resolve/main
HF_UPSCALE      := https://huggingface.co/Kim2091/UltraSharp/resolve/main
HF_PULID        := https://huggingface.co/guozinan/PuLID/resolve/main

HF_DL := wget -q --show-progress -c
HF_DL_AUTH := $(HF_DL) --header="Authorization: Bearer $(HF_TOKEN)"

.PHONY: download-models download-models-flux-dev download-models-flux-schnell \
        download-models-sdxl download-models-encoders \
        download-models-flux-fill download-models-flux-kontext \
        download-models-flux-depth download-models-flux-canny \
        download-models-flux-redux download-models-controlnet \
        download-models-upscale download-models-pulid \
        download-models-editing download-models-all \
        build up down logs health test gaming resume queue

# === Model Downloads ===

download-models: download-models-flux-dev download-models-flux-schnell download-models-sdxl download-models-encoders
	@echo "Base models downloaded to $(MODEL_DIR)"

download-models-editing: download-models download-models-flux-fill download-models-flux-kontext download-models-upscale
	@echo "Editing models downloaded to $(MODEL_DIR)"

download-models-all: download-models-editing download-models-flux-depth download-models-flux-canny \
    download-models-flux-redux download-models-controlnet download-models-pulid
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
	@mkdir -p $(MODEL_DIR)/text_encoders $(MODEL_DIR)/vae $(MODEL_DIR)/loras $(MODEL_DIR)/diffusion_models \
		$(MODEL_DIR)/upscale_models $(MODEL_DIR)/controlnet $(MODEL_DIR)/style_models $(MODEL_DIR)/pulid
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
		$(HF_DL) -O "$(MODEL_DIR)/vae/ae.safetensors" \
			"$(HF_VAE)/ae.safetensors" || exit 1; \
	fi

# === Editing & Control Models ===

download-models-flux-fill:
	@mkdir -p $(MODEL_DIR)/diffusion_models
	@if [ -f "$(MODEL_DIR)/diffusion_models/flux1-fill-dev-fp8.safetensors" ]; then \
		echo "skip flux1-fill-dev-fp8.safetensors (exists)"; \
	else \
		echo "downloading flux1-fill-dev-fp8.safetensors (~12GB)..."; \
		$(HF_DL) -O "$(MODEL_DIR)/diffusion_models/flux1-fill-dev-fp8.safetensors" \
			"$(HF_FLUX_FILL)/flux1-Fill-Dev_FP8.safetensors" || exit 1; \
	fi

download-models-flux-kontext:
	@mkdir -p $(MODEL_DIR)/diffusion_models
	@if [ -f "$(MODEL_DIR)/diffusion_models/flux1-kontext-dev-fp8-e4m3fn.safetensors" ]; then \
		echo "skip flux1-kontext-dev-fp8-e4m3fn.safetensors (exists)"; \
	else \
		echo "downloading flux1-kontext-dev-fp8-e4m3fn.safetensors (~12GB)..."; \
		$(HF_DL) -O "$(MODEL_DIR)/diffusion_models/flux1-kontext-dev-fp8-e4m3fn.safetensors" \
			"$(HF_FLUX_KONTEXT)/flux1-kontext-dev-fp8-e4m3fn.safetensors" || exit 1; \
	fi

download-models-flux-depth:
	@mkdir -p $(MODEL_DIR)/diffusion_models
	@if [ -f "$(MODEL_DIR)/diffusion_models/flux1-depth-dev-fp8.safetensors" ]; then \
		echo "skip flux1-depth-dev-fp8.safetensors (exists)"; \
	else \
		echo "downloading flux1-depth-dev-fp8.safetensors (~12GB)..."; \
		$(HF_DL) -O "$(MODEL_DIR)/diffusion_models/flux1-depth-dev-fp8.safetensors" \
			"$(HF_FLUX_DEPTH)/flux1-Depth-Dev_FP8.safetensors" || exit 1; \
	fi

download-models-flux-canny:
	@mkdir -p $(MODEL_DIR)/diffusion_models
	@if [ -f "$(MODEL_DIR)/diffusion_models/flux1-canny-dev-fp8.safetensors" ]; then \
		echo "skip flux1-canny-dev-fp8.safetensors (exists)"; \
	else \
		echo "downloading flux1-canny-dev-fp8.safetensors (~12GB)..."; \
		$(HF_DL) -O "$(MODEL_DIR)/diffusion_models/flux1-canny-dev-fp8.safetensors" \
			"$(HF_FLUX_CANNY)/flux1-Canny-Dev_FP8.safetensors" || exit 1; \
	fi

download-models-flux-redux:
	@mkdir -p $(MODEL_DIR)/style_models
	@if [ -f "$(MODEL_DIR)/style_models/flux1-redux-dev.safetensors" ]; then \
		echo "skip flux1-redux-dev.safetensors (exists)"; \
	else \
		echo "downloading flux1-redux-dev.safetensors (~123MB)..."; \
		$(HF_DL) -O "$(MODEL_DIR)/style_models/flux1-redux-dev.safetensors" \
			"$(HF_FLUX_REDUX)/flux1-redux-dev.safetensors" || exit 1; \
	fi

download-models-controlnet:
	@mkdir -p $(MODEL_DIR)/controlnet
	@if [ -f "$(MODEL_DIR)/controlnet/flux1-dev-controlnet-union-pro-2.0.safetensors" ]; then \
		echo "skip flux1-dev-controlnet-union-pro-2.0.safetensors (exists)"; \
	else \
		echo "downloading flux1-dev-controlnet-union-pro-2.0.safetensors (~4GB)..."; \
		$(HF_DL) -O "$(MODEL_DIR)/controlnet/flux1-dev-controlnet-union-pro-2.0.safetensors" \
			"$(HF_CONTROLNET)/diffusion_pytorch_model.safetensors" || exit 1; \
	fi

download-models-upscale:
	@mkdir -p $(MODEL_DIR)/upscale_models
	@if [ -f "$(MODEL_DIR)/upscale_models/4x-UltraSharp.pth" ]; then \
		echo "skip 4x-UltraSharp.pth (exists)"; \
	else \
		echo "downloading 4x-UltraSharp.pth (~67MB)..."; \
		$(HF_DL) -O "$(MODEL_DIR)/upscale_models/4x-UltraSharp.pth" \
			"$(HF_UPSCALE)/4x-UltraSharp.pth" || exit 1; \
	fi

download-models-pulid:
	@mkdir -p $(MODEL_DIR)/pulid
	@if [ -f "$(MODEL_DIR)/pulid/pulid_flux_v0.9.1.safetensors" ]; then \
		echo "skip pulid_flux_v0.9.1.safetensors (exists)"; \
	else \
		echo "downloading pulid_flux_v0.9.1.safetensors (~1.1GB)..."; \
		$(HF_DL) -O "$(MODEL_DIR)/pulid/pulid_flux_v0.9.1.safetensors" \
			"$(HF_PULID)/pulid_flux_v0.9.1.safetensors" || exit 1; \
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
