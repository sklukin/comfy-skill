#!/usr/bin/env python3
import argparse
import json
import mimetypes
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


DEFAULT_BASE_URL = "http://192.168.1.41:8189"
BOUNDARY = "----OpenClawUpscaleBoundary7MA4YWxkTrZu0gW"


def http_json(url: str, timeout: float = 60.0):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_post_json(url: str, payload: dict, timeout: float = 60.0):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_post_multipart_image(url: str, image_path: Path, timeout: float = 120.0):
    mime = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
    body = b"".join([
        f"--{BOUNDARY}\r\n".encode(),
        f"Content-Disposition: form-data; name=\"image\"; filename=\"{image_path.name}\"\r\n".encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        image_path.read_bytes(),
        f"\r\n--{BOUNDARY}--\r\n".encode(),
    ])
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def download_file(url: str, out_path: Path, timeout: float = 120.0):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as r, out_path.open("wb") as f:
        f.write(r.read())


def log_json(prefix: str, payload: dict):
    print(f"{prefix}: {json.dumps(payload, ensure_ascii=False)}", flush=True)


def main():
    p = argparse.ArgumentParser(description="Submit and wait for an Images API 4x upscale job (UltraSharp)")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--input", required=True, help="Path to image to upscale")
    p.add_argument("--output", required=True, help="Path to save upscaled image")
    p.add_argument("--poll-seconds", type=float, default=5.0)
    p.add_argument("--timeout-seconds", type=float, default=300.0)
    args = p.parse_args()

    input_path = Path(args.input)
    if not input_path.exists() or not input_path.is_file():
        print(f"Input image not found: {input_path}", file=sys.stderr)
        return 2

    # Upload source image
    try:
        upload = http_post_multipart_image(f"{args.base_url}/upload", input_path, timeout=120)
        log_json("upload", upload)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"Image upload failed: HTTP {e.code}: {body}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Image upload failed: {e}", file=sys.stderr)
        return 1

    payload = {
        "model": "upscale",
        "input_image": upload["filename"],
    }

    try:
        job = http_post_json(f"{args.base_url}/jobs", payload, timeout=60)
        log_json("job", job)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"Job submission failed: HTTP {e.code}: {body}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Job submission failed: {e}", file=sys.stderr)
        return 1

    job_id = job["job_id"]
    deadline = time.time() + args.timeout_seconds

    while time.time() < deadline:
        try:
            state = http_json(f"{args.base_url}/jobs/{job_id}", timeout=30)
            log_json("state", state)
        except Exception as e:
            print(f"Failed to poll job {job_id}: {e}", file=sys.stderr)
            time.sleep(args.poll_seconds)
            continue

        current = state.get("status")
        if current == "completed":
            out_path = Path(args.output)
            try:
                download_file(f"{args.base_url}/jobs/{job_id}/result", out_path, timeout=120)
            except Exception as e:
                print(f"Failed to download result for job {job_id}: {e}", file=sys.stderr)
                return 1
            if not out_path.exists() or out_path.stat().st_size == 0:
                print("Downloaded file is empty", file=sys.stderr)
                return 1
            print(str(out_path), flush=True)
            return 0

        if current in {"failed", "cancelled"}:
            print(json.dumps(state, ensure_ascii=False), file=sys.stderr)
            return 1

        time.sleep(args.poll_seconds)

    print(f"Timed out waiting for upscale job {job_id}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
