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
    torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 \
    --index-url https://download.pytorch.org/whl/cu124

# Clone ComfyUI at a pinned version for reproducibility
ARG COMFYUI_VERSION=v0.21.1
RUN git clone --depth 1 --branch ${COMFYUI_VERSION} \
    https://github.com/comfyanonymous/ComfyUI.git /app/ComfyUI

WORKDIR /app/ComfyUI

# Modern build tooling — required for ComfyUI-Manager 4.x pyproject metadata
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# ComfyUI dependencies
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir requests

# ComfyUI-Manager — v4.x installs via pip (no longer git-cloned into custom_nodes)
ARG COMFYUI_MANAGER_VERSION=4.2.1
RUN pip install --no-cache-dir "comfyui-manager==${COMFYUI_MANAGER_VERSION}"

# ComfyUI-GGUF: GGUF quantized model support (editing models use Q8_0 GGUF)
RUN git clone --depth 1 https://github.com/city96/ComfyUI-GGUF.git \
        /app/ComfyUI/custom_nodes/ComfyUI-GGUF && \
    pip install --no-cache-dir gguf

# Stash the baseline custom_nodes/user contents under /opt/baseline so the
# entrypoint can re-seed them into bind-mounted (possibly empty) volumes on
# first run. Files installed by the user via Manager survive container
# rebuilds because /app/ComfyUI/custom_nodes and /app/ComfyUI/user are
# expected to be mounted from the host.
RUN mkdir -p /opt/baseline/custom_nodes /opt/baseline/user && \
    cp -a /app/ComfyUI/custom_nodes/. /opt/baseline/custom_nodes/ && \
    if [ -d /app/ComfyUI/user ]; then cp -a /app/ComfyUI/user/. /opt/baseline/user/; fi

# Model path configuration (maps volume-mounted dirs)
COPY extra_model_paths.yaml /app/ComfyUI/

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8188

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--listen", "0.0.0.0", \
     "--port", "8188", \
     "--preview-method", "none", \
     "--disable-auto-launch", \
     "--highvram", \
     "--enable-manager"]
