#!/usr/bin/env python3
import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


DEFAULT_BASE_URL = "http://192.168.1.41:8189"


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


def download_file(url: str, out_path: Path, timeout: float = 120.0):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as r, out_path.open("wb") as f:
        f.write(r.read())


def log_json(prefix: str, payload: dict):
    print(f"{prefix}: {json.dumps(payload, ensure_ascii=False)}", flush=True)


def main():
    p = argparse.ArgumentParser(description="Submit and wait for an Images API text2img job")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--prompt", required=True)
    p.add_argument("--model", default="flux-dev")
    p.add_argument("--width", type=int, default=1024)
    p.add_argument("--height", type=int, default=1024)
    p.add_argument("--steps", type=int)
    p.add_argument("--guidance-scale", type=float)
    p.add_argument("--seed", type=int, default=-1)
    p.add_argument("--negative-prompt")
    p.add_argument("--output", required=True)
    p.add_argument("--poll-seconds", type=float, default=5.0)
    p.add_argument("--timeout-seconds", type=float, default=600.0)
    args = p.parse_args()

    if args.steps is None:
        args.steps = 25 if args.model == "sdxl" else (4 if args.model == "flux-schnell" else 20)
    if args.guidance_scale is None:
        args.guidance_scale = 7.0 if args.model == "sdxl" else 3.5

    try:
        status = http_json(f"{args.base_url}/status", timeout=30)
        log_json("status", status)
    except Exception as e:
        print(f"Failed to read generator status: {e}", file=sys.stderr)
        return 2

    if not status.get("ready") or status.get("status") in {"paused", "offline"}:
        print(f"Generator unavailable: {status.get('status')}", file=sys.stderr)
        return 2

    payload = {
        "prompt": args.prompt,
        "model": args.model,
        "width": args.width,
        "height": args.height,
        "steps": args.steps,
        "guidance_scale": args.guidance_scale,
        "seed": args.seed,
    }
    if args.model == "sdxl" and args.negative_prompt:
        payload["negative_prompt"] = args.negative_prompt

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

    print(f"Timed out waiting for image job {job_id}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
