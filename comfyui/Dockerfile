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
ARG COMFYUI_VERSION=v0.3.34
RUN git clone --depth 1 --branch ${COMFYUI_VERSION} \
    https://github.com/comfyanonymous/ComfyUI.git /app/ComfyUI

WORKDIR /app/ComfyUI

# ComfyUI dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Model path configuration (maps volume-mounted dirs)
COPY extra_model_paths.yaml /app/ComfyUI/

EXPOSE 8188

CMD ["python", "main.py", \
     "--listen", "0.0.0.0", \
     "--port", "8188", \
     "--preview-method", "none", \
     "--disable-auto-launch"]
