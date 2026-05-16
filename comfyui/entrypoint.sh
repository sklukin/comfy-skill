#!/bin/bash
set -euo pipefail

# Seed user-writable dirs from the baseline shipped in the image.
# When custom_nodes/ and user/ are bind-mounted from the host (empty on first
# run), this restores the nodes/files we install at build time without
# overwriting anything the user has added or modified.

BASELINE_NODES=/opt/baseline/custom_nodes
BASELINE_USER=/opt/baseline/user
NODES_DIR=/app/ComfyUI/custom_nodes
USER_DIR=/app/ComfyUI/user

mkdir -p "$NODES_DIR" "$USER_DIR"

if [ -d "$BASELINE_NODES" ]; then
    for src in "$BASELINE_NODES"/*; do
        [ -e "$src" ] || continue
        name=$(basename "$src")
        if [ ! -e "$NODES_DIR/$name" ]; then
            cp -a "$src" "$NODES_DIR/"
        fi
    done
fi

if [ -d "$BASELINE_USER" ]; then
    for src in "$BASELINE_USER"/*; do
        [ -e "$src" ] || continue
        name=$(basename "$src")
        if [ ! -e "$USER_DIR/$name" ]; then
            cp -a "$src" "$USER_DIR/"
        fi
    done
fi

# ComfyUI-Manager v4.x refuses git/pip installs unless network_mode is
# personal_cloud (it treats a non-loopback --listen as 'public' and locks
# everything down). We expose the API on 0.0.0.0 inside a container the user
# controls, so personal_cloud is the right mode. Seed it on first run, and
# coerce it back if the file already exists with the wrong value.
MANAGER_DIR="$USER_DIR/__manager"
MANAGER_CFG="$MANAGER_DIR/config.ini"
mkdir -p "$MANAGER_DIR"
if [ ! -f "$MANAGER_CFG" ]; then
    cat > "$MANAGER_CFG" <<'EOF'
[default]
network_mode = personal_cloud
security_level = normal
EOF
elif grep -q '^network_mode = public' "$MANAGER_CFG"; then
    sed -i 's/^network_mode = public/network_mode = personal_cloud/' "$MANAGER_CFG"
fi

exec python main.py "$@"
