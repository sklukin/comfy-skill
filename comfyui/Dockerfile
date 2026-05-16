FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# System dependencies
RUN apt-get update && apt-get install -y \
    python3.11 python3.11-venv python3.11-dev python3-pip \
    git wget curl \
    libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.11 /usr/bin/python && \
    ln -sf /usr/bin/python3.11 /usr/bin/python3

WORKDIR /app

# PyTorch (large layer — cached separately)
RUN pip install --no-cache-dir \
    torch==2.6.0 torchvision==0.21.0 \
    --index-url https://download.pytorch.org/whl/cu124

# Clone ComfyUI at a pinned version for reproducibility
ARG COMFYUI_VERSION=v0.18.5
RUN git clone --depth 1 --branch ${COMFYUI_VERSION} \
    https://github.com/comfyanonymous/ComfyUI.git /app/ComfyUI

WORKDIR /app/ComfyUI

# ComfyUI dependencies (torchaudio removed — not needed for image generation,
# and its native lib requires CUDA devel headers absent in runtime image)
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir requests && \
    pip uninstall -y torchaudio 2>/dev/null || true

# ComfyUI-Manager — pinned to a release compatible with ComfyUI v0.18.x
ARG COMFYUI_MANAGER_VERSION=3.40
RUN git clone --depth 1 --branch ${COMFYUI_MANAGER_VERSION} \
        https://github.com/ltdrdata/ComfyUI-Manager.git \
        /app/ComfyUI/custom_nodes/ComfyUI-Manager && \
    pip install --no-cache-dir -r /app/ComfyUI/custom_nodes/ComfyUI-Manager/requirements.txt
    
# ComfyUI-GGUF: GGUF quantized model support (editing models use Q8_0 GGUF)
RUN git clone --depth 1 https://github.com/city96/ComfyUI-GGUF.git \
        /app/ComfyUI/custom_nodes/ComfyUI-GGUF && \
    pip install --no-cache-dir gguf

# Model path configuration (maps volume-mounted dirs)
COPY extra_model_paths.yaml /app/ComfyUI/

EXPOSE 8188

CMD ["python", "main.py", \
     "--listen", "0.0.0.0", \
     "--port", "8188", \
     "--preview-method", "none", \
     "--disable-auto-launch", \
     "--highvram"]
